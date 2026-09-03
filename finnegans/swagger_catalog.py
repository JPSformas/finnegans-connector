"""Catalogo de APIs de Finnegans basado en el spec OpenAPI completo (swaggerGlobal).

Fuente de verdad de endpoints: baja el spec (Swagger 2.0) una vez, lo cachea
en memoria, y ofrece busqueda y extraccion de operaciones. Solo libreria estandar.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request


class SwaggerError(Exception):
    """Error al cargar o interpretar el spec de swaggerGlobal."""


_SPEC_CACHE: dict[str, dict] = {}

# Los schemas de body de Finnegans no viven en "#/definitions/...": cada uno
# esta en otro endpoint del swagger. Se cachean aparte del spec principal.
_VO_CACHE: dict[str, dict] = {}

# Clave con la que guardamos, dentro del spec, la URL de donde se bajo. Hace
# falta para resolver las refs relativas de body contra el mismo host.
_SOURCE_URL_KEY = "x-finnegans-source-url"


def _fetch_spec(url: str, key: str, timeout: int = 60) -> dict:
    full = f"{url}?key={urllib.parse.quote(key, safe='')}"
    req = urllib.request.Request(full, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def cargar_spec(url: str, key: str, *, force: bool = False) -> dict:
    """Devuelve el spec OpenAPI cacheado; lo baja en el primer uso o si force."""
    ck = f"{url}|{key}"
    if force or ck not in _SPEC_CACHE:
        try:
            spec = _fetch_spec(url, key)
            if isinstance(spec, dict):
                spec[_SOURCE_URL_KEY] = url
            _SPEC_CACHE[ck] = spec
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as e:
            raise SwaggerError(
                "No pude cargar la documentacion de APIs de Finnegans (swaggerGlobal). "
                f"Revisa conectividad y FINNEGANS_SWAGGER_KEY. Detalle: {e}"
            ) from e
    return _SPEC_CACHE[ck]


_METODOS_HTTP = {"get", "post", "put", "delete", "patch"}


def _tokens(texto: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (texto or "").lower()) if t]


def buscar_endpoints(spec: dict, consulta: str, limite: int = 8) -> list[dict]:
    q = set(_tokens(consulta))
    if not q:
        return []
    resultados: list[dict] = []
    for path, ops in (spec.get("paths") or {}).items():
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
        texto = " ".join([path] + tags + resumenes + opids)
        palabras = set(_tokens(texto))
        score = len(q & palabras)
        if score:
            resultados.append({
                "path": path,
                "metodos": metodos,
                "tags": sorted(set(tags)),
                "resumen": next((r for r in resumenes if r), ""),
                "score": float(score),
            })
    resultados.sort(key=lambda x: x["score"], reverse=True)
    return resultados[:limite]


def _es_ref_externa(ref: str) -> bool:
    """True si la ref apunta afuera del documento (URL absoluta o relativa)."""
    return ref.startswith(("http://", "https://", "/"))


def _url_de_ref(ref: str, source_url: str) -> str:
    """Convierte una ref relativa en absoluta usando el host del spec."""
    if ref.startswith(("http://", "https://")):
        return ref
    partes = urllib.parse.urlsplit(source_url)
    return urllib.parse.urlunsplit((partes.scheme, partes.netloc, "", "", "")) + ref


def _bajar_schema_externo(url: str, timeout: int = 30) -> dict:
    """Baja y cachea un schema de body que vive en otro endpoint del swagger.

    La ref ya trae su propia key en el query string, asi que no hay que
    inyectar credenciales.
    """
    if url in _VO_CACHE:
        return _VO_CACHE[url]
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    _VO_CACHE[url] = data if isinstance(data, dict) else {}
    return _VO_CACHE[url]


def _resolver_body_schema(spec: dict, schema: dict) -> tuple[dict, bool]:
    """Resuelve el schema de un parametro body.

    Devuelve (schema, resuelto). Si no se pudo resolver, resuelto es False y
    el llamador debe tratarlo como "sin schema" en vez de asumir que el
    endpoint no tiene campos: de lo contrario todo campo enviado aparece como
    desconocido.
    """
    if not isinstance(schema, dict):
        return {}, False
    if "$ref" not in schema:
        return schema, bool(schema)

    ref = schema["$ref"]
    if _es_ref_externa(ref):
        source = spec.get(_SOURCE_URL_KEY) or ""
        if not source and not ref.startswith(("http://", "https://")):
            return {}, False
        try:
            resuelto = _bajar_schema_externo(_url_de_ref(ref, source))
        except (urllib.error.URLError, TimeoutError, OSError,
                ValueError, json.JSONDecodeError):
            return {}, False
        return resuelto, bool(resuelto.get("properties"))

    nombre = ref.split("/")[-1]  # ej. "#/definitions/ClienteBody"
    interno = (spec.get("definitions") or {}).get(nombre, {})
    return interno, bool(interno)


def resolver_ref(spec: dict, schema: dict) -> dict:
    """Resuelve un $ref interno o externo; devuelve {} si no se pudo."""
    resuelto, _ = _resolver_body_schema(spec, schema)
    return resuelto


def _primer_segmento(path: str) -> str:
    return path.strip("/").split("/")[0]


def ver_endpoint(spec: dict, recurso: str) -> list[dict]:
    objetivo = recurso.strip("/")
    ops: list[dict] = []
    for path, metodos in (spec.get("paths") or {}).items():
        if not isinstance(metodos, dict):
            continue
        coincide = path.strip("/") == objetivo or _primer_segmento(path) == objetivo
        if not coincide:
            continue
        for m, detail in metodos.items():
            if m.lower() not in _METODOS_HTTP or not isinstance(detail, dict):
                continue
            params, tiene_body, campos, requeridos = [], False, [], []
            body_schema: dict | None = None
            body_ok = False
            for p in detail.get("parameters") or []:
                if not isinstance(p, dict):
                    continue
                if p.get("in") == "body":
                    tiene_body = True
                    resuelto, body_ok = _resolver_body_schema(spec, p.get("schema") or {})
                    body_schema = resuelto if body_ok else None
                    campos = list((resuelto.get("properties") or {}).keys())
                    requeridos = list(resuelto.get("required") or [])
                elif p.get("name") != "ACCESS_TOKEN":
                    params.append({
                        "nombre": p.get("name"),
                        "requerido": bool(p.get("required", False)),
                        "ubicacion": p.get("in"),
                        "descripcion": p.get("description", ""),
                    })
            ops.append({
                "metodo": m.upper(),
                "path": path,
                "resumen": detail.get("summary", ""),
                "parametros": params,
                "tiene_body": tiene_body,
                "body_campos": campos,
                "body_requeridos": requeridos,
                "body_schema_ok": body_ok,
                "body_schema": body_schema,
            })
    return ops
