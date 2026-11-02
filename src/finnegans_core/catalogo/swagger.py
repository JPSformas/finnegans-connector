"""Catalogo de APIs de Finnegans basado en el spec OpenAPI completo (swaggerGlobal).

Fuente de verdad de endpoints: baja el spec (Swagger 2.0) una vez por proceso y
ofrece busqueda, clasificacion por tipo de endpoint y extraccion de operaciones.

Los schemas de body de las entidades no viven en "#/definitions/...": cada uno
esta en otro endpoint del swagger (una ref relativa al host del spec, con la
key adentro). Se bajan a pedido y se cachean aparte. Los schemas de respuesta
NO se bajan nunca: los viewers devuelven un placeholder de error.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx2

from ..config import Settings
from ..secretos import Redactor
from ..vocabulario import sin_acentos, sinonimos_de, variantes

TipoEndpoint = Literal["viewer", "entidad", "otro"]

TIMEOUT_SPEC_SEGUNDOS = 60
TIMEOUT_VO_SEGUNDOS = 30

_METODOS_HTTP = {"get", "post", "put", "delete", "patch"}

# Spec completo, por (url, key). Vive por proceso: son ~580 paths y no cambia.
_SPEC_CACHE: dict[tuple[str, str], dict] = {}

# Schemas de body externos, por URL absoluta. Aparte del spec principal.
_VO_CACHE: dict[str, dict] = {}

_TIPO_EN_TAG = re.compile(r"Tipo:\s*(\w+)")
_TIPOS_POR_NOMBRE: dict[str, TipoEndpoint] = {"viewer": "viewer", "entidadvo": "entidad"}


def limpiar_caches() -> None:
    """Vacia el cache del spec y el de schemas de body (para tests y recargas)."""
    _SPEC_CACHE.clear()
    _VO_CACHE.clear()


class SwaggerError(Exception):
    """Error al cargar o interpretar el spec de swaggerGlobal."""


@dataclass
class Coincidencia:
    path: str
    metodos: list[str]
    tipo: TipoEndpoint
    resumen: str
    puntaje: float
    cobertura: float  # fraccion de conceptos de la consulta encontrados, de 0 a 1


@dataclass
class Operacion:
    metodo: str
    path: str
    resumen: str
    tipo: TipoEndpoint
    parametros: list[dict] = field(default_factory=list)
    tiene_body: bool = False
    body_campos: list[str] = field(default_factory=list)
    body_requeridos: list[str] = field(default_factory=list)
    body_schema_ok: bool = False


# ------------------------------------------------------------- tokenizacion

# Limite de palabra dentro de un identificador camelCase: "ordenPago" -> orden|Pago,
# "getAPIDatos" -> get|API|Datos (la sigla no se parte letra por letra).
_LIMITE_CAMEL = re.compile(r"(?<=[a-z0-9ñ])(?=[A-ZÑ])|(?<=[A-ZÑ])(?=[A-ZÑ][a-zñ])")


def _tokens(texto: str | None) -> list[str]:
    """Parte el texto en palabras buscables.

    Ademas de separar por caracteres no alfanumericos, parte los limites de
    camelCase: Finnegans nombra sus recursos asi ("movimientoFondos",
    "ordenPago"), y sin esto "movimiento de fondos" no matchea ningun endpoint.
    Se conserva tambien el identificador completo para que buscar
    "movimientoFondos" siga funcionando.

    Los acentos se quitan antes de partir: un separador de palabras no puede
    ser la tilde de "tesoreria", que partia la palabra en 'tesorer' y 'a'.
    """
    salida: list[str] = []
    for crudo in re.split(r"[^A-Za-z0-9ñÑ]+", sin_acentos(texto)):
        if not crudo:
            continue
        salida.append(crudo.lower())
        partes = [p.lower() for p in _LIMITE_CAMEL.split(crudo) if p]
        if len(partes) > 1:
            salida.extend(partes)
    return salida


def _conceptos(consulta: str) -> list[frozenset[str]]:
    """Cada palabra de la consulta como el conjunto de formas que la satisfacen.

    Una palabra se da por encontrada si aparece en singular o plural, o si
    aparece alguno de sus sinonimos de negocio. Se agrupan por concepto (y no
    como tokens sueltos) para que un sinonimo no infle el score: "caja" vale
    uno, encuentre 'fondos' o 'cobranza'.
    """
    conceptos: list[frozenset[str]] = []
    for t in dict.fromkeys(_tokens(consulta)):
        formas = set(variantes(t))
        for s in sinonimos_de(t):
            formas |= variantes(s)
        f = frozenset(formas)
        if f and f not in conceptos:
            conceptos.append(f)
    return conceptos


# -------------------------------------------------------------------- refs

def _es_ref_externa(ref: str) -> bool:
    """True si la ref apunta afuera del documento (URL absoluta o relativa)."""
    return ref.startswith(("http://", "https://", "/"))


def _url_de_ref(ref: str, source_url: str) -> str:
    """Convierte una ref relativa en absoluta usando el host del spec."""
    if ref.startswith(("http://", "https://")):
        return ref
    partes = urlsplit(source_url)
    return urlunsplit((partes.scheme, partes.netloc, "", "", "")) + ref


def _primer_segmento(path: str) -> str:
    return path.strip("/").split("/")[0]


def _nombre_de_ref(ref: str) -> str:
    """Nombre legible de una ref, sin su URL: una ref externa lleva la key."""
    if _es_ref_externa(ref):
        nombres = parse_qs(urlsplit(ref).query).get("nombreVO")
        return f"ref a {nombres[0]}" if nombres else "ref externa"
    return f"ref a {ref.split('/')[-1]}"


class SwaggerCatalog:
    def __init__(self, settings: Settings, http: httpx2.Client | None = None) -> None:
        self.settings = settings
        self.http = http if http is not None else httpx2.Client(timeout=TIMEOUT_SPEC_SEGUNDOS)
        self.redactor = Redactor(settings.secretos())
        self._tipos_por_tag: dict[str, TipoEndpoint] | None = None

    # ------------------------------------------------------------------ spec
    def spec(self) -> dict:
        """Spec OpenAPI completo, cacheado por proceso. Levanta SwaggerError."""
        url = (self.settings.swagger_url or "").strip()
        key = self.settings.swagger_key
        if not key:
            raise SwaggerError(
                "Falta la clave del swagger (FINNEGANS_SWAGGER_KEY): sin ella no puedo "
                "cargar la documentacion de APIs de Finnegans."
            )
        clave = (url, key)
        if clave not in _SPEC_CACHE:
            _SPEC_CACHE[clave] = self._bajar_spec(url, key)
        return _SPEC_CACHE[clave]

    def _bajar_spec(self, url: str, key: str) -> dict:
        prefijo = (
            "No pude cargar la documentacion de APIs de Finnegans (swaggerGlobal). "
            "Revisa la conectividad y la clave del swagger. Detalle: "
        )
        try:
            resp = self.http.get(url, params={"key": key}, timeout=TIMEOUT_SPEC_SEGUNDOS,
                                 headers={"Accept": "application/json"})
        except (httpx2.HTTPError, httpx2.InvalidURL, OSError, ValueError) as e:
            raise SwaggerError(self.redactor.limpiar(prefijo + str(e))) from None
        if resp.status_code >= 400:
            # Se redacta el cuerpo entero antes de cortarlo: una key partida por
            # el corte ya no se reconoce y su primera parte quedaria visible.
            detalle = self.redactor.limpiar(resp.text)[:200]
            raise SwaggerError(self.redactor.limpiar(
                f"{prefijo}HTTP {resp.status_code}: {detalle}"))
        try:
            data = resp.json()
        except ValueError:
            raise SwaggerError(self.redactor.limpiar(
                f"{prefijo}la respuesta no es un JSON valido.")) from None
        if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
            raise SwaggerError(self.redactor.limpiar(
                f"{prefijo}la respuesta no tiene la forma de un swagger."))
        return data

    # ------------------------------------------------------------------ tipo
    def _mapa_tipos(self) -> dict[str, TipoEndpoint]:
        if self._tipos_por_tag is None:
            mapa: dict[str, TipoEndpoint] = {}
            for tag in self.spec().get("tags") or []:
                if not isinstance(tag, dict) or not tag.get("name"):
                    continue
                m = _TIPO_EN_TAG.search(tag.get("description") or "")
                tipo = _TIPOS_POR_NOMBRE.get(m.group(1).lower()) if m else None
                if tipo:
                    mapa[tag["name"]] = tipo
            self._tipos_por_tag = mapa
        return self._tipos_por_tag

    def _tipo_de_ops(self, ops: object) -> TipoEndpoint:
        """Tipo segun el primer tag de la primera operacion que lo tenga."""
        if not isinstance(ops, dict):
            return "otro"
        mapa = self._mapa_tipos()
        for m, detail in ops.items():
            if m.lower() in _METODOS_HTTP and isinstance(detail, dict):
                for tag in detail.get("tags") or []:
                    return mapa.get(tag, "otro")
        return "otro"

    def tipo(self, path: str) -> TipoEndpoint:
        """Viewer, entidad u otro. Sale del tag del endpoint, no de su path."""
        paths = self.spec().get("paths") or {}
        ops = paths.get(path)
        if ops is None:
            ops = paths.get("/" + path.lstrip("/"))
        return self._tipo_de_ops(ops)

    # ---------------------------------------------------------------- buscar
    def buscar(self, consulta: str, limite: int = 8) -> list[Coincidencia]:
        conceptos = _conceptos(consulta)
        if not conceptos:
            return []
        resultados: list[Coincidencia] = []
        for path, ops in (self.spec().get("paths") or {}).items():
            if not isinstance(ops, dict):
                continue
            metodos, tags, resumenes, opids = [], [], [], []
            for m, detail in ops.items():
                if m.lower() not in _METODOS_HTTP or not isinstance(detail, dict):
                    continue
                metodos.append(m.upper())
                tags += detail.get("tags") or []
                resumenes.append(detail.get("summary", ""))
                opids.append(detail.get("operationId", ""))
            if not metodos:
                continue
            palabras = set(_tokens(" ".join([path] + tags + resumenes + opids)))
            # El endpoint se indexa tambien por las formas singular/plural de
            # cada palabra, para que la consulta lo alcance venga como venga.
            formas_doc: set[str] = set()
            for w in palabras:
                formas_doc |= variantes(w)
            coincidencias = sum(1 for c in conceptos if c & formas_doc)
            if not coincidencias:
                continue
            # Al termino base (cuantas palabras de la consulta aparecen) se le
            # suma la precision: que proporcion del endpoint explica la
            # consulta. Sin esto "cliente" empata en 1 con /cliente/list y con
            # /reports/getDatosClienteEmpresa, y el recurso exacto se pierde.
            precision = coincidencias / len(palabras)
            resultados.append(Coincidencia(
                path=path,
                metodos=metodos,
                tipo=self._tipo_de_ops(ops),
                resumen=next((r for r in resumenes if r), ""),
                puntaje=float(coincidencias) + precision,
                cobertura=coincidencias / len(conceptos),
            ))
        resultados.sort(key=lambda c: c.puntaje, reverse=True)
        return resultados[:limite]

    # ------------------------------------------------------- schemas de body
    def _bajar_schema_externo(self, url: str) -> dict:
        """Baja y cachea un schema de body que vive en otro endpoint del swagger.

        La ref ya trae su propia key en el query string, asi que no se inyectan
        credenciales. Levanta ante cualquier falla; el llamador degrada.
        """
        if url in _VO_CACHE:
            return _VO_CACHE[url]
        resp = self.http.get(url, timeout=TIMEOUT_VO_SEGUNDOS,
                             headers={"Accept": "application/json"})
        if resp.status_code >= 400:
            raise ValueError(f"HTTP {resp.status_code}")
        data = resp.json()
        _VO_CACHE[url] = data if isinstance(data, dict) else {}
        return _VO_CACHE[url]

    def _resolver_schema(self, schema: object, contexto: dict | None = None) -> tuple[dict, bool]:
        """Resuelve un schema, con o sin $ref. Devuelve (schema, resuelto).

        Si no se pudo resolver, resuelto es False y el llamador debe tratarlo
        como "sin schema" en vez de asumir que el endpoint no tiene campos: de
        lo contrario todo campo enviado aparece como desconocido. `contexto`
        es el documento en el que vive el schema (para sus refs internas).
        """
        if not isinstance(schema, dict):
            return {}, False
        ref = schema.get("$ref")
        if not ref:
            return schema, bool(schema)
        if _es_ref_externa(ref):
            try:
                resuelto = self._bajar_schema_externo(
                    _url_de_ref(ref, self.settings.swagger_url or ""))
            except (httpx2.HTTPError, httpx2.InvalidURL, OSError, ValueError):
                return {}, False
            return resuelto, bool(resuelto.get("properties"))
        nombre = ref.split("/")[-1]  # ej. "#/definitions/ClienteBody"
        for doc in (contexto, self.spec()):
            interno = ((doc or {}).get("definitions") or {}).get(nombre)
            if interno:
                return interno, True
        return {}, False

    def _resolver_parametro(self, p: object) -> dict:
        """Resuelve un parametro declarado como $ref interno.

        Finnegans declara los parametros comunes (ACCESS_TOKEN, codigo,
        updatedSince, createIfNotExists) una sola vez en 'definitions' y los
        referencia. Sin resolverlos, p['name'] es None.
        """
        if not isinstance(p, dict):
            return {}
        ref = p.get("$ref")
        if not ref or _es_ref_externa(ref):
            return p
        nombre = ref.split("/")[-1]
        return (self.spec().get("definitions") or {}).get(nombre, {})

    # -------------------------------------------------------------- ver/campo
    def _analizar(self, ops_path: dict, detail: dict) -> tuple[list[dict], dict | None, bool]:
        """(parametros sin ACCESS_TOKEN, schema del body o None, tiene_body)."""
        # Parametros a nivel path: valen para todos sus metodos (ahi viven
        # ACCESS_TOKEN y el 'codigo' de /recurso/{codigo}).
        comunes = ops_path.get("parameters") or []
        params: list[dict] = []
        vistos: set[tuple[str, str]] = set()
        tiene_body = False
        body: dict | None = None
        for p in list(comunes) + list(detail.get("parameters") or []):
            p = self._resolver_parametro(p)
            if not p:
                continue
            if p.get("in") == "body":
                tiene_body = True
                resuelto, ok = self._resolver_schema(p.get("schema") or {})
                body = resuelto if ok else None
            elif p.get("name") and p.get("name") != "ACCESS_TOKEN":
                clave = (p["name"], p.get("in") or "")
                if clave in vistos:
                    continue  # declarado a nivel path y de operacion
                vistos.add(clave)
                params.append({
                    "nombre": p["name"],
                    "requerido": bool(p.get("required", False)),
                    "ubicacion": p.get("in"),
                    "descripcion": p.get("description", ""),
                })
        return params, body, tiene_body

    def _operaciones_de(self, recurso_o_path: str) -> list[tuple[str, str, dict, dict]]:
        """(metodo, path, detalle, ops_del_path) de lo que matchea el recurso.

        Matchea exacto y, si no hay nada, sin importar mayusculas: Claude suele
        escribir 'movimientofondos' donde el spec dice 'movimientoFondos'.
        """
        objetivo = (recurso_o_path or "").strip("/")
        paths = [(p, o) for p, o in (self.spec().get("paths") or {}).items()
                 if isinstance(o, dict)]
        for normalizar in (lambda t: t, str.lower):
            salida: list[tuple[str, str, dict, dict]] = []
            for path, ops in paths:
                if (normalizar(path.strip("/")) != normalizar(objetivo)
                        and normalizar(_primer_segmento(path)) != normalizar(objetivo)):
                    continue
                for m, detail in ops.items():
                    if m.lower() in _METODOS_HTTP and isinstance(detail, dict):
                        salida.append((m.upper(), path, detail, ops))
            if salida:
                return salida
        return []

    def ver(self, recurso_o_path: str) -> list[Operacion]:
        """Operaciones de un recurso ('cliente') o de un path exacto."""
        resultado: list[Operacion] = []
        for metodo, path, detail, ops in self._operaciones_de(recurso_o_path):
            params, body, tiene_body = self._analizar(ops, detail)
            props = (body or {}).get("properties") or {}
            resultado.append(Operacion(
                metodo=metodo,
                path=path,
                resumen=detail.get("summary", ""),
                tipo=self._tipo_de_ops(ops),
                parametros=params,
                tiene_body=tiene_body,
                body_campos=list(props.keys()),
                body_requeridos=list((body or {}).get("required") or []),
                body_schema_ok=body is not None,
            ))
        return resultado

    def campo(self, recurso_o_path: str, metodo: str, campo: str) -> dict:
        """Sub-propiedades de un campo anidado del body, un nivel de profundidad.

        Para un array de objetos ('ProvinciaItems') devuelve las propiedades de
        sus elementos. Un campo escalar devuelve {}.
        """
        metodo = metodo.upper()
        candidatas = [o for o in self._operaciones_de(recurso_o_path) if o[0] == metodo]
        if not candidatas:
            raise SwaggerError(
                f"No encontre {metodo} para '{recurso_o_path}' en la documentacion.")
        body: dict | None = None
        for _, _, detail, ops in candidatas:
            _, body, _ = self._analizar(ops, detail)
            if body is not None:
                break
        if body is None:
            raise SwaggerError(
                f"{metodo} '{recurso_o_path}' no tiene un schema de body disponible.")
        props = body.get("properties") or {}
        if campo not in props:
            # Exacto primero; si no, sin importar mayusculas.
            campo = next((k for k in props if k.lower() == campo.lower()), campo)
        if campo not in props:
            raise SwaggerError(
                f"El body de {metodo} '{recurso_o_path}' no tiene el campo '{campo}'. "
                f"Campos disponibles: {', '.join(props) or '(ninguno)'}.")
        definicion = props[campo]
        if not isinstance(definicion, dict):
            return {}
        items = definicion.get("items")
        destino = items if isinstance(items, dict) else definicion
        destino, _ = self._resolver_schema(destino, contexto=body)
        sub = destino.get("properties") or {}
        return self._sanear(sub) if isinstance(sub, dict) else {}

    def _sanear(self, valor):
        """Copia segura para devolver: sin refs con key y sin secretos en strings.

        Una propiedad anidada puede ser una ref externa que lleva la key del
        swagger en su query string; se deja solo el nombre.
        """
        if isinstance(valor, dict):
            return {
                k: (_nombre_de_ref(v) if k == "$ref" and isinstance(v, str)
                    else self._sanear(v))
                for k, v in valor.items()
            }
        if isinstance(valor, list):
            return [self._sanear(v) for v in valor]
        if isinstance(valor, str):
            return self.redactor.limpiar(valor)
        return valor
