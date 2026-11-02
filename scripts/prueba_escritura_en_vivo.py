"""Prueba de escritura EN VIVO contra Finnegans, con registros descartables.

ATENCION: esto escribe en PRODUCCION. Crea, modifica y borra un cliente de
prueba (nombre "ZZ PRUEBA MCP - borrar") pasando por las mismas herramientas MCP
que usa Claude. El cliente plantilla que elijas solo se LEE: de ahi salen los
campos obligatorios del alta.

En el alta Finnegans IGNORA el Codigo del body (se manda ZZ-PRUEBA-MCP) y le
asigna su propio codigo, que devuelve en "id". La prueba sigue ese codigo. Hay
una guarda interna que aborta antes de enviar: solo se escribe sobre codigos que
empiezan con ZZ-PRUEBA-MCP o sobre un codigo CONFIRMADO, es decir uno que la
prueba releyo y vio que se llama "ZZ PRUEBA MCP...", esta inactivo y no existia
antes de la corrida (o, para los restos de corridas anteriores, que se llama asi
y esta inactivo).

Elegi una plantilla de BAJO VALOR: un cliente real pero sin importancia (el
script no la modifica, pero la lee y copia de ahi los campos obligatorios).

Finnegans rechaza el alta de cliente (HTTP 500) si faltan dos campos que el
swagger no marca requeridos. Los valores que funcionaron en la primera prueba en
vivo son CategoriaFiscalCodigo=CF e IdentificacionTributariaCodigo=SINIDENTIFICACION
(con esos no hace falta numero): pasalos con --campo.

Uso (las claves van por variables de entorno, nunca desde un archivo .env):

    uv run python scripts/prueba_escritura_en_vivo.py ^
        --si-escribir-en-produccion --plantilla CODIGO_DE_UN_CLIENTE ^
        --campo CategoriaFiscalCodigo=CF ^
        --campo IdentificacionTributariaCodigo=SINIDENTIFICACION

Pasos:
  1. Lee cliente/list y cliente/ZZ-PRUEBA-MCP por id: busca restos de corridas
     anteriores, por codigo (ZZ-PRUEBA-MCP*) y por nombre (ZZ PRUEBA MCP*, que
     ahora tienen codigo numerico). Lee cada resto: solo se borra si se llama
     ZZ PRUEBA MCP... (y, si su codigo es numerico, si ademas esta inactivo).
  2. Lee la plantilla (y guarda una foto), arma el alta con SOLO los campos
     obligatorios del swagger (sin ids ni guids a ninguna profundidad, salvo
     referencias conocidas como ProvinciaID dentro de las listas) mas los --campo,
     y decide como dejarla inactiva. Si hay campos "unicos" (CUIT, documento,
     email...) aborta salvo que pases --permitir-copiar-campos-unicos.
  3. Borra los restos que hubiera.
  4. POST del cliente de prueba. Verifica que la plantilla quedo identica a su
     foto, averigua el codigo que asigno Finnegans (el "id" de la respuesta; si no
     viene, el unico cliente nuevo llamado "ZZ PRUEBA MCP - borrar") y lo confirma:
     lo relee y verifica nombre, inactivo y que no existia antes. Si no puede
     confirmarlo, aborta sin borrar nada.
  5. PUT con base + cambios (cambia el Nombre) y verifica el resumen.
  6. PUT con el registro completo en body.
  7. DELETE y verifica que la API dice que ya no existe, que no queda nada en
     cliente/list y que la plantilla sigue igual.

Sale con codigo distinto de cero ante cualquier resultado inesperado.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import re
import sys
from typing import Any, Callable, Mapping

from finnegans_core.config import Settings
from finnegans_core.workspace import Workspace
from finnegans_mcp.escritura import TITULO_CAMBIADOS, TITULO_PROPIOS
from finnegans_mcp.server import crear_servidor

PREFIJO = "ZZ-PRUEBA-MCP"
CODIGO_PRUEBA = PREFIJO
# Todo nombre que la prueba le pone a su registro empieza asi: un resto cuyo
# nombre no empiece asi puede ser un cliente real y no se toca.
NOMBRE_PREFIJO = "ZZ PRUEBA MCP"
NOMBRE_ALTA = "ZZ PRUEBA MCP - borrar"
NOMBRE_EDITADO = "ZZ PRUEBA MCP - editado"
NOMBRE_BODY = "ZZ PRUEBA MCP - body completo"
RECURSO = "cliente"
# Tope de restos a borrar: mas que esto es raro y se aborta en vez de borrar.
MAX_RESTOS = 20

# Cada lectura usa una tabla nueva (zz_prueba_<base>_<n>): una lectura fallida no
# reemplaza la tabla, y si se reusara el nombre se verian datos viejos.
NO_VOLVER_A_CORRER = "No vuelvas a correr la prueba hasta revisar los dos clientes a mano."
TABLA_LISTA = "zz_prueba_lista"
TABLA_PLANTILLA = "zz_prueba_plantilla"
TABLA_PRUEBA = "zz_prueba_registro"
TABLA_VERIFICACION = "zz_prueba_verificacion"

# Claves que identifican un registro: si viajaran en el alta, Finnegans podria
# modificar la plantilla en vez de crear uno nuevo.
_CLAVE_IDENTIDAD = re.compile(r"^(?i:id|guid|uuid)$|^(?i:id)[A-Z_]|(?i:_?id)$")
# Dentro de las listas, algunos XxxID son referencias a otro maestro
# (ProvinciaID = "BSAS"): sacarlas deja la fila incompleta y Finnegans rechaza el
# alta. Solo se conservan las de esta lista, vistas en clientes reales; cualquier
# otra clave con forma de id (ContactoID, OrganizacionID...) puede ser el id de una
# fila de la plantilla y se saca. Si falta una referencia, el alta falla: no se
# adivina.
_REFERENCIAS_ANIDADAS = frozenset({"provinciaid", "actividadiibbid"})
# Campos que suelen ser unicos en Finnegans (un duplicado rechaza el alta).
_CLAVE_UNICA = re.compile(
    r"cuit|cuil|documento|nrodoc|email|mail|correo|nroinscripcion|dni", re.IGNORECASE)
_INACTIVOS = {"n", "no", "false", "0"}

_NO_EXISTE = "No existe '"
_OK_ESCRITURA = "listo, Finnegans aceptó la escritura"
_OK_DELETE = "Registro eliminado"
_SIN_RELECTURA = "no pude releer"
_AVISOS_FALLO = ("falló", "No se envió", "No sé si", _SIN_RELECTURA)

# Lo que escribir dice tras un alta: "Finnegans ignoró el Codigo enviado 'A' y le
# asignó 'X'" o "Finnegans le asignó al registro nuevo el código 'X'".
_RE_ASIGNADO = re.compile(r"le asignó (?:al registro nuevo el código )?'([^']+)'")
_RE_RESPUESTA = re.compile(r"^Respuesta de la API: (.*)$", re.MULTILINE)
_RE_ID_JSON = re.compile(r'"id"\s*:\s*(?:"([^"]*)"|(-?\d+))', re.IGNORECASE)

_FLAGS_ACTIVO = ("activo",)
# Valor "activo" de un campo de texto -> el que lo deja inactivo.
_TEXTO_A_INACTIVO = {"s": "N", "si": "N", "sí": "N", "y": "N", "yes": "N",
                     "true": "false", "1": "0"}
_TEXTO_YA_INACTIVO = {"n", "no", "false", "0"}


class ErrorPrueba(Exception):
    """Un paso no dio lo esperado: la prueba se detiene con codigo != 0."""


# ----------------------------------------------------------------- utilidades


def _normal(codigo: Any) -> str:
    return str(codigo).strip().casefold()


def _clave(registro: Mapping[str, Any], nombre: str, defecto: str) -> str:
    """Clave real del registro que coincide con `nombre` sin importar mayusculas."""
    for k in registro:
        if str(k).lower() == nombre:
            return k
    return defecto


def _unico(registro: Any) -> dict | None:
    if isinstance(registro, list) and len(registro) == 1:
        registro = registro[0]
    return registro if isinstance(registro, dict) else None


def _partes_del_resumen(texto: str) -> tuple[str, str]:
    """(seccion 'cambiados', seccion 'por su cuenta') del resumen de escribir."""
    if TITULO_CAMBIADOS not in texto or TITULO_PROPIOS not in texto:
        raise ErrorPrueba(
            "La respuesta de escribir no trae el resumen de cambios "
            f"('{TITULO_CAMBIADOS}' / '{TITULO_PROPIOS}')."
        )
    cambiados, propios = texto.split(TITULO_PROPIOS, 1)
    return cambiados, propios


def _estado_inactivo(valor: Any) -> Any:
    """El valor que deja inactivo un registro, con el mismo tipo que el de la plantilla."""
    if valor is None or isinstance(valor, bool):
        return False
    if isinstance(valor, int):
        return 0
    if isinstance(valor, str):
        clave = valor.strip().lower()
        if clave in _TEXTO_A_INACTIVO:
            inactivo = _TEXTO_A_INACTIVO[clave]
            return inactivo.upper() if valor.strip().isupper() else inactivo.lower()
        if clave in _TEXTO_YA_INACTIVO:
            return valor
    raise ErrorPrueba(
        f"No sé cómo dejar inactivo un registro cuyo campo de estado vale {valor!r}: "
        "no se escribió nada."
    )


def _lista_de_body(texto_ver_endpoint: str, solo_requeridos: bool) -> list[str]:
    for linea in texto_ver_endpoint.splitlines():
        m = re.match(r"\s*Body \(.*?\):\s*(.*)$", linea)
        if m:
            nombres = []
            for parte in m.group(1).split(", "):
                parte = parte.strip()
                requerido = parte.endswith("*")
                parte = parte.rstrip("*")
                if re.fullmatch(r"[A-Za-z0-9_]+", parte) and (requerido or not solo_requeridos):
                    nombres.append(parte)
            return nombres
    return []


def campos_de_body(texto_ver_endpoint: str) -> list[str]:
    """Nombres de los campos del body, tal como los lista ver_endpoint."""
    return _lista_de_body(texto_ver_endpoint, False)


def campos_requeridos(texto_ver_endpoint: str) -> list[str]:
    """Campos del body marcados con * (requeridos) en ver_endpoint."""
    return _lista_de_body(texto_ver_endpoint, True)


def campo_activo(plantilla: Mapping[str, Any], texto_ver_endpoint: str) -> str:
    """Nombre del campo que marca activo/inactivo: de la plantilla o del swagger.

    Aborta si no hay uno reconocible: no se adivina.
    """
    for k in plantilla:
        if str(k).lower() in _FLAGS_ACTIVO:
            return k
    for k in campos_de_body(texto_ver_endpoint):
        if k.lower() in _FLAGS_ACTIVO:
            return k
    raise ErrorPrueba(
        "No pude determinar el campo que marca un cliente como activo/inactivo: no está "
        "entre los campos de la plantilla ni en el body de POST cliente según el swagger "
        "(busqué 'Activo'). Para no crear un cliente activo por error, no se escribió nada."
    )


def _sin_identidad(valor: Any, sacadas: set[str], anidado: bool = False) -> Any:
    """Copia sin las claves de identidad (id, guid, IdXxx, XxxId), a toda profundidad.

    La unica excepcion son las referencias de _REFERENCIAS_ANIDADAS dentro de
    listas u objetos anidados (ProvinciaID...).
    """
    if isinstance(valor, dict):
        limpio = {}
        for k, v in valor.items():
            referencia = anidado and str(k).lower() in _REFERENCIAS_ANIDADAS
            if _CLAVE_IDENTIDAD.search(str(k)) and not referencia:
                sacadas.add(str(k))
            else:
                limpio[k] = _sin_identidad(v, sacadas, True)
        return limpio
    if isinstance(valor, list):
        return [_sin_identidad(v, sacadas, True) for v in valor]
    return valor


def referencias_copiadas(valor: Any, ruta: str = "") -> list[str]:
    """Rutas de las claves con forma de id que quedan en el alta (referencias)."""
    encontradas: list[str] = []
    if isinstance(valor, dict):
        for k, v in valor.items():
            aqui = f"{ruta}.{k}" if ruta else str(k)
            if _CLAVE_IDENTIDAD.search(str(k)):
                encontradas.append(aqui)
            encontradas += referencias_copiadas(v, aqui)
    elif isinstance(valor, list):
        for v in valor:
            encontradas += referencias_copiadas(v, ruta + "[]")
    return sorted(set(encontradas))


def claves_unicas(valor: Any, ruta: str = "") -> list[str]:
    """Rutas de clave (sin valores) que parecen campos unicos, a toda profundidad."""
    encontradas: list[str] = []
    if isinstance(valor, dict):
        for k, v in valor.items():
            aqui = f"{ruta}.{k}" if ruta else str(k)
            if _CLAVE_UNICA.search(str(k)):
                encontradas.append(aqui)
            encontradas += claves_unicas(v, aqui)
    elif isinstance(valor, list):
        for v in valor:
            encontradas += claves_unicas(v, ruta + "[]")
    return sorted(set(encontradas))


def armar_alta(plantilla: dict, flag: str, requeridos: list[str] | None = None,
               copiar_resto: bool = False) -> tuple[dict, list[str]]:
    """Body del alta: solo los campos requeridos del swagger tomados de la plantilla.

    Solo con copiar_resto se parte de toda la plantilla. Sin lista de requeridos y
    sin copiar_resto se aborta: no se copia la plantilla entera en silencio. En todos
    los casos se sacan las claves de identidad a cualquier profundidad (salvo las
    referencias de _REFERENCIAS_ANIDADAS dentro de listas) y despues se
    pisan codigo, nombre y estado (inactivo). Devuelve (body, claves de identidad
    sacadas).
    """
    if not requeridos and not copiar_resto:
        raise ErrorPrueba(
            "No pude determinar los campos requeridos del alta de cliente (el swagger no "
            "los lista o no está disponible), así que no sé qué copiar de la plantilla. No "
            "se escribió nada. Si querés copiar toda la plantilla (sin ids ni guids, salvo "
            "referencias como ProvinciaID), pasá --copiar-resto-de-la-plantilla."
        )
    if copiar_resto:
        origen = plantilla
    else:
        pedidos = {r.lower() for r in requeridos}
        origen = {k: v for k, v in plantilla.items() if str(k).lower() in pedidos}
    sacadas: set[str] = set()
    body = _sin_identidad(copy.deepcopy(origen), sacadas)
    body[_clave(plantilla, "codigo", "Codigo")] = CODIGO_PRUEBA
    body[_clave(plantilla, "nombre", "Nombre")] = NOMBRE_ALTA
    body[flag] = _estado_inactivo(plantilla.get(flag))
    return body, sorted(sacadas)


def _esta_inactivo(registro: Mapping[str, Any], flag: str) -> bool:
    valor = registro.get(_clave(registro, flag.lower(), flag), "<falta>")
    if valor is False or (isinstance(valor, int) and not isinstance(valor, bool) and valor == 0):
        return True
    return isinstance(valor, str) and valor.strip().lower() in _INACTIVOS


def _claves_distintas(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str]:
    return sorted(str(k) for k in set(a) | set(b) if a.get(k, "<falta>") != b.get(k, "<falta>"))


def _id_de(datos: Any) -> str | None:
    if not isinstance(datos, dict):
        return None
    for k, v in datos.items():
        if str(k).lower() == "id" and not isinstance(v, (bool, dict, list)) and v is not None:
            texto = str(v).strip()
            if texto:
                return texto
    return None


def codigo_asignado(texto: str) -> str | None:
    """Codigo que Finnegans le asigno al alta, segun la salida de escribir.

    Primero el aviso de escribir ("le asignó 'X'"); si no esta, el "id" de la linea
    "Respuesta de la API: {...}" (que puede venir cortada con …). None si no hay.
    """
    m = _RE_ASIGNADO.search(texto or "")
    if m and m.group(1).strip():
        return m.group(1).strip()
    for linea in _RE_RESPUESTA.findall(texto or ""):
        try:
            datos = json.loads(linea)
        except ValueError:
            datos = None
        if isinstance(datos, dict):
            asignado = _id_de(datos)
            if asignado:
                return asignado
            continue
        m = _RE_ID_JSON.search(linea)
        if m:
            asignado = (m.group(1) if m.group(1) is not None else m.group(2)).strip()
            if asignado:
                return asignado
    return None


# --------------------------------------------------------------------- prueba


class Prueba:
    """Un recorrido completo contra un servidor MCP ya armado."""

    def __init__(self, server: Any, workspace: Workspace,
                 salida: Callable[[str], None] = print, *,
                 permitir_campos_unicos: bool = False,
                 copiar_resto: bool = False,
                 campos_extra: Mapping[str, str] | None = None) -> None:
        self.server = server
        self.workspace = workspace
        self.salida = salida
        self.permitir_campos_unicos = permitir_campos_unicos
        self.copiar_resto = copiar_resto
        self.campos_extra = dict(campos_extra or {})
        self.paso = 0
        self.n_tabla = 0
        self.pendiente_de_borrar = False
        self.plantilla: str | None = None
        # Foto cruda de la plantilla: la limpieza solo borra si sigue identica.
        self.foto: dict | None = None
        self.tabla_prueba = ""
        # Codigos (normalizados) que existian antes del alta: los del paso 1 y la
        # plantilla, menos los restos que la prueba misma borro.
        self.previos: set[str] = set()
        # Codigo que Finnegans le asigno al alta (todavia sin confirmar).
        self.asignado: str | None = None
        # Codigo del alta ya releido y confirmado como de la prueba.
        self.confirmado: str | None = None
        # Codigos sin el prefijo que la guarda deja pasar: el alta confirmada y los
        # restos releidos y confirmados.
        self.confirmados: set[str] = set()

    # -- entrada/salida ----------------------------------------------------

    def titulo(self, texto: str) -> None:
        self.paso += 1
        self.salida(f"\n=== Paso {self.paso}: {texto} ===")

    def _tabla_nueva(self, base: str) -> str:
        self.n_tabla += 1
        return f"{base}_{self.n_tabla}"

    def _invocar(self, herramienta: str, **argumentos: Any) -> str:
        argumentos = {k: v for k, v in argumentos.items() if v is not None}
        self.salida(f"--> {herramienta}({_resumen_args(argumentos)})")
        r = asyncio.run(self.server.call_tool(herramienta, argumentos))
        texto = "".join(c.text for c in r.content)
        self.salida(texto)
        if r.is_error:
            raise ErrorPrueba(f"La herramienta {herramienta} devolvió un error.")
        return texto

    def llamar(self, herramienta: str, **argumentos: Any) -> str:
        """Llama una herramienta de LECTURA por el registro del servidor.

        `escribir` no se puede llamar por aca: solo por `self.escribir`, que tiene la guarda.
        """
        if herramienta == "escribir":
            raise ErrorPrueba("Guarda: escribir solo se llama por Prueba.escribir.")
        return self._invocar(herramienta, **argumentos)

    def _registro_a_escribir(self, body: dict | None, base: str | None) -> dict | None:
        if isinstance(body, dict):
            return body
        if base is not None:
            try:
                return _unico(self.workspace.crudo(base))
            except KeyError:
                return None
        return None

    def permitido(self, codigo: Any) -> bool:
        """True si la guarda deja escribir sobre `codigo`.

        Solo los que empiezan con ZZ-PRUEBA-MCP (exacto) o los que la prueba ya releyo
        y confirmo (el alta, con el codigo que asigno Finnegans, y los restos).
        """
        return isinstance(codigo, str) and (
            codigo.startswith(PREFIJO) or codigo in self.confirmados)

    def escribir(self, metodo: str, *, id: str | None = None, body: dict | None = None,
                 base: str | None = None, cambios: dict | None = None) -> str:
        """escribir sobre cliente, con la guarda (falla cerrada).

        Solo se escribe sobre codigos ZZ-PRUEBA-MCP* o confirmados (ver `permitido`).
        Un POST siempre manda un codigo ZZ-PRUEBA-MCP*.
        """
        if metodo not in ("POST", "PUT", "DELETE"):
            raise ErrorPrueba(f"Guarda: el método {metodo} no se usa en esta prueba.")
        if metodo == "POST" and id is not None:
            raise ErrorPrueba("Guarda: un POST va con body y sin id.")
        if metodo == "DELETE" and (body is not None or base is not None or cambios):
            raise ErrorPrueba("Guarda: un DELETE va solo con id.")
        registro = None
        if metodo != "DELETE":
            # El codigo que se va a mandar (body, o la base) tiene que estar y ser de prueba.
            registro = self._registro_a_escribir(body, base)
            if registro is None:
                raise ErrorPrueba(
                    f"Guarda: no hay un registro (body o base) para {metodo}: no se envió nada."
                )
            cod_body = registro.get(_clave(registro, "codigo", "Codigo"))
            de_prueba = (isinstance(cod_body, str) and cod_body.startswith(PREFIJO)
                         if metodo == "POST" else self.permitido(cod_body))
            if not de_prueba:
                raise ErrorPrueba(
                    f"Guarda: el registro a enviar trae el código {cod_body!r}, que no "
                    f"empieza con {PREFIJO} ni es el cliente de prueba confirmado (o falta). "
                    "No se envió nada."
                )
            if metodo == "PUT" and _normal(cod_body) != _normal(id):
                raise ErrorPrueba(
                    f"Guarda: el registro a enviar trae el código {cod_body!r} pero el PUT va "
                    f"a {id!r}. No se envió nada."
                )
        objetivo = id if metodo != "POST" else registro.get(_clave(registro, "codigo", "Codigo"))
        if not self.permitido(objetivo):
            raise ErrorPrueba(
                f"Guarda: me negué a hacer {metodo} sobre el código {objetivo!r}: solo se "
                f"escribe sobre códigos que empiezan con {PREFIJO} o sobre el cliente de "
                "prueba ya releído y confirmado. No se envió nada."
            )
        if cambios and any(str(k).lower() == "codigo" for k in cambios):
            raise ErrorPrueba("Guarda: los cambios no pueden tocar el código. No se envió nada.")
        texto = self._invocar("escribir", metodo=metodo, path=RECURSO, id=id, body=body,
                              base=base, cambios=cambios)
        # Tras un alta, que escribir no pueda releer con el Codigo del body es lo
        # esperable (Finnegans asigna otro): el codigo se averigua despues.
        avisos = [a for a in _AVISOS_FALLO if not (metodo == "POST" and a == _SIN_RELECTURA)]
        if any(a in texto for a in avisos):
            raise ErrorPrueba(f"escribir {metodo} {objetivo} no terminó bien (ver arriba).")
        ok = _OK_DELETE if metodo == "DELETE" else _OK_ESCRITURA
        if ok not in texto:
            raise ErrorPrueba(f"escribir {metodo} {objetivo}: no vi la confirmación '{ok}'.")
        return texto

    # -- lecturas verificadas -----------------------------------------------

    def _cargada(self, tabla: str) -> bool:
        """True si la tabla esta en el workspace. Los nombres son nuevos en cada lectura,
        asi que existir prueba que ESTA lectura cargo datos (el formato del texto de
        leer cambia segun el tamano y no sirve para esto)."""
        try:
            self.workspace.crudo(tabla)
        except KeyError:
            return False
        return True

    def leer_registro(self, codigo: str, base_tabla: str, *,
                      puede_no_existir: bool = False) -> tuple[dict | None, str]:
        """(registro, tabla). Exige que el workspace tenga la carga o que leer diga 'No existe'.

        Cualquier otra cosa (un error, un timeout, una lista vacia) es un fallo: no se
        interpreta como 'no existe'. Con puede_no_existir devuelve (None, tabla) ante
        el aviso de que no existe.
        """
        tabla = self._tabla_nueva(base_tabla)
        texto = self.llamar("leer", path=RECURSO, id=codigo, tabla=tabla)
        if self._cargada(tabla):
            registro = _unico(self.workspace.crudo(tabla))
            if registro is None:
                raise ErrorPrueba(f"'{codigo}' no se leyó como un registro (objeto JSON).")
            cod = registro.get(_clave(registro, "codigo", "Codigo"))
            if cod is None or _normal(cod) != _normal(codigo):
                raise ErrorPrueba(
                    f"Pedí el cliente '{codigo}' y Finnegans devolvió el código {cod!r}."
                )
            return registro, tabla
        if texto.startswith(_NO_EXISTE):
            if puede_no_existir:
                return None, tabla
            raise ErrorPrueba(f"El cliente '{codigo}' no existe en Finnegans.")
        raise ErrorPrueba(
            f"No pude confirmar la lectura del cliente '{codigo}': la respuesta no es un "
            "registro cargado ni el aviso de que no existe. No lo tomo como 'no existe'."
        )

    def leer_prueba(self) -> dict:
        registro, tabla = self.leer_registro(self.confirmado, TABLA_PRUEBA)
        self.tabla_prueba = tabla
        return registro

    def _leer_lista(self) -> str:
        """Carga cliente/list en una tabla nueva y devuelve su nombre."""
        tabla = self._tabla_nueva(TABLA_LISTA)
        self.llamar("leer", path=f"{RECURSO}/list", tabla=tabla)
        if not self._cargada(tabla):
            raise ErrorPrueba(
                "No pude cargar cliente/list (la respuesta no confirma la carga): no puedo "
                "saber qué registros de prueba hay."
            )
        return tabla

    def _filas(self, sql: str) -> list[tuple]:
        try:
            _, filas, hay_mas = self.workspace.ejecutar_con_tope(sql)
        except Exception as e:  # noqa: BLE001
            raise ErrorPrueba(f"No pude consultar cliente/list ({sql}): {e}") from e
        if hay_mas:
            raise ErrorPrueba(f"cliente/list tiene más filas de las que puedo revisar ({sql}).")
        return filas

    def restos(self, guardar_previos: bool = False) -> list[str]:
        """Restos de prueba que hay hoy (solo lectura): por codigo y por nombre, en
        cliente/list, y ZZ-PRUEBA-MCP por id directo.

        Con guardar_previos anota todos los codigos del listado (para saber despues
        cual es el cliente nuevo).
        """
        tabla = self._leer_lista()
        sql = (f"SELECT Codigo, Nombre FROM {tabla} "
               f"WHERE CAST(Codigo AS VARCHAR) LIKE '{PREFIJO}%' "
               f"OR CAST(Nombre AS VARCHAR) LIKE '{NOMBRE_PREFIJO}%' "
               "ORDER BY Codigo")
        self.llamar("consultar", sql=sql)
        filas = self._filas(sql)
        codigos = [str(f[0]) for f in filas]
        raros = [str(c) for c, n in filas
                 if not (str(c).startswith(PREFIJO)
                         or (isinstance(n, str) and n.startswith(NOMBRE_PREFIJO)))]
        if raros:
            raise ErrorPrueba(f"La búsqueda de restos devolvió códigos ajenos: {raros[:5]}")
        if len(codigos) > MAX_RESTOS:
            raise ErrorPrueba(
                f"Hay {len(codigos)} registros de prueba ({PREFIJO}* o '{NOMBRE_PREFIJO}*', "
                f"más de {MAX_RESTOS}): es raro, revisalos a mano antes de borrar nada."
            )
        if guardar_previos:
            self.previos = {_normal(f[0]) for f in self._filas(f"SELECT Codigo FROM {tabla}")}
        # Por si /list no muestra los inactivos: tambien se pregunta por el id directo.
        directo, _ = self.leer_registro(CODIGO_PRUEBA, TABLA_VERIFICACION, puede_no_existir=True)
        if directo is not None:
            if guardar_previos:
                self.previos.add(_normal(CODIGO_PRUEBA))
            if CODIGO_PRUEBA not in codigos:
                codigos.append(CODIGO_PRUEBA)
        return codigos

    def verificar_restos(self, restos: list[str]) -> None:
        """Lee cada resto y aborta (sin escribir nada) si no es de la prueba.

        Un resto que no se llama 'ZZ PRUEBA MCP...' puede ser un cliente real (por
        ejemplo, la plantilla pisada por un alta anterior): no se borra. Un resto con
        codigo numerico (encontrado por nombre) ademas tiene que estar inactivo; recien
        entonces la guarda deja borrarlo.
        """
        for codigo in restos:
            registro, _ = self.leer_registro(codigo, TABLA_VERIFICACION)
            nombre = registro.get(_clave(registro, "nombre", "Nombre"))
            if not isinstance(nombre, str) or not nombre.startswith(NOMBRE_PREFIJO):
                raise ErrorPrueba(
                    f"El resto '{codigo}' se llama {nombre!r}, que no empieza con "
                    f"'{NOMBRE_PREFIJO}': puede ser un cliente real y no lo borro. No se "
                    f"escribió nada. Revisá a mano, en Finnegans, el cliente '{codigo}' y "
                    f"la plantilla '{self.plantilla}'. {NO_VOLVER_A_CORRER}"
                )
            if codigo.startswith(PREFIJO):
                continue
            flag = next((k for k in registro if str(k).lower() in _FLAGS_ACTIVO), "Activo")
            if not _esta_inactivo(registro, flag):
                raise ErrorPrueba(
                    f"El resto '{codigo}' ({nombre!r}) está ACTIVO o sin el campo {flag}: "
                    "no lo borro. No se escribió nada. Revisalo y borralo a mano en "
                    f"Finnegans. {NO_VOLVER_A_CORRER}"
                )
            self.confirmados.add(codigo)

    def leer_plantilla(self, codigo: str) -> dict:
        registro, _ = self.leer_registro(codigo, TABLA_PLANTILLA)
        return registro

    def estado_plantilla(self) -> str | None:
        """None si la plantilla sigue identica a su foto; si no, que le paso."""
        try:
            ahora, _ = self.leer_registro(self.plantilla, TABLA_PLANTILLA, puede_no_existir=True)
        except Exception as e:  # noqa: BLE001
            return f"no pude releerla ({e})"
        if ahora is None:
            return "YA NO EXISTE con su código"
        if ahora != self.foto:
            return f"CAMBIÓ (campos: {_claves_distintas(self.foto, ahora)})"
        return None

    def cliente_de_prueba(self) -> str:
        """Como nombrarle a Juan el cliente de prueba en un aviso."""
        if self.asignado:
            return f"el cliente de prueba '{self.asignado}'"
        return (f"el cliente de prueba (se mandó con el código {CODIGO_PRUEBA}, pero "
                f"Finnegans le asigna otro: buscalo por el nombre '{NOMBRE_ALTA}')")

    def verificar_plantilla(self) -> None:
        """La plantilla tiene que seguir igual que antes del alta."""
        problema = self.estado_plantilla()
        if problema is not None:
            raise ErrorPrueba(
                f"La plantilla '{self.plantilla}' {problema}. Revisá a mano, en Finnegans, el "
                f"cliente '{self.plantilla}' y {self.cliente_de_prueba()} (el alta podría "
                "haberla pisado, y el cliente de prueba puede haber quedado ACTIVO). "
                f"{NO_VOLVER_A_CORRER}"
            )

    def averiguar_asignado(self, texto_post: str) -> str:
        """Codigo que Finnegans le asigno al alta (todavia sin confirmar).

        Sale de la respuesta del POST. Si no viene, se busca el unico cliente nuevo
        llamado NOMBRE_ALTA en un cliente/list fresco (y por id directo con
        ZZ-PRUEBA-MCP, por si /list no muestra los inactivos). Si no hay exactamente
        uno, aborta: la limpieza no borra nada sin un codigo confirmado.
        """
        asignado = codigo_asignado(texto_post)
        if asignado:
            self.salida(f"Código que asignó Finnegans (según la respuesta): {asignado}")
            return asignado
        self.salida("La respuesta del alta no trae el código asignado: lo busco por nombre.")
        tabla = self._leer_lista()
        nombre_sql = NOMBRE_ALTA.replace("'", "''")
        filas = self._filas(f"SELECT Codigo FROM {tabla} WHERE Nombre = '{nombre_sql}'")
        candidatos: dict[str, str] = {}
        for (codigo,) in filas:
            if _normal(codigo) not in self.previos:
                candidatos[_normal(codigo)] = str(codigo)
        directo, _ = self.leer_registro(CODIGO_PRUEBA, TABLA_VERIFICACION, puede_no_existir=True)
        if (directo is not None and _normal(CODIGO_PRUEBA) not in self.previos
                and directo.get(_clave(directo, "nombre", "Nombre")) == NOMBRE_ALTA):
            candidatos[_normal(CODIGO_PRUEBA)] = CODIGO_PRUEBA
        if len(candidatos) != 1:
            raise ErrorPrueba(
                "No pude saber qué código le asignó Finnegans al cliente de prueba: la "
                f"respuesta no lo trae y encontré {len(candidatos)} clientes nuevos llamados "
                f"'{NOMBRE_ALTA}' ({sorted(candidatos.values())[:5]}). No borro nada. "
                f"Buscá a mano, en Finnegans, los clientes llamados '{NOMBRE_ALTA}', "
                f"revisalos y borralos si son de la prueba; revisá también la plantilla "
                f"'{self.plantilla}'. {NO_VOLVER_A_CORRER}"
            )
        asignado = next(iter(candidatos.values()))
        self.salida(f"Código del cliente nuevo (buscado por nombre): {asignado}")
        return asignado

    def confirmar_asignado(self, codigo: str, flag: str) -> dict:
        """Relee el alta y la confirma: nombre de prueba, inactiva y nueva.

        Recien despues de esto la guarda deja escribir sobre `codigo`.
        """
        registro, tabla = self.leer_registro(codigo, TABLA_PRUEBA)
        nombre = registro.get(_clave(registro, "nombre", "Nombre"))
        if not isinstance(nombre, str) or not nombre.startswith(NOMBRE_PREFIJO):
            raise ErrorPrueba(
                f"El cliente '{codigo}' (el que asignó Finnegans) se llama {nombre!r}, que no "
                f"empieza con '{NOMBRE_PREFIJO}': puede ser un cliente real y no lo toco. "
                f"Revisá a mano, en Finnegans, el cliente '{codigo}', los clientes llamados "
                f"'{NOMBRE_ALTA}' y la plantilla '{self.plantilla}'. {NO_VOLVER_A_CORRER}"
            )
        if not _esta_inactivo(registro, flag):
            raise ErrorPrueba(
                f"El alta quedó ACTIVA o sin el campo {flag} (el cliente '{codigo}' tiene "
                f"{registro.get(_clave(registro, flag.lower(), flag), '<falta>')!r}): se aborta."
            )
        if _normal(codigo) in self.previos:
            raise ErrorPrueba(
                f"El cliente '{codigo}' ya existía antes del alta: no es el cliente nuevo y no "
                f"lo toco. Revisá a mano, en Finnegans, el cliente '{codigo}' y los clientes "
                f"llamados '{NOMBRE_ALTA}'. {NO_VOLVER_A_CORRER}"
            )
        self.confirmados.add(codigo)
        self.confirmado = codigo
        self.tabla_prueba = tabla
        self.salida(f"Confirmado: '{codigo}' es el cliente de prueba (nombre, inactivo y nuevo).")
        return registro

    # -- corrida ----------------------------------------------------------------

    def correr(self, plantilla: str) -> None:
        if plantilla.startswith(PREFIJO):
            raise ErrorPrueba(f"La plantilla no puede ser un {PREFIJO}*: elegí un cliente real.")
        self.plantilla = plantilla
        try:
            self._correr(plantilla)
        except BaseException:
            self._limpiar_tras_fallo()
            raise

    def _correr(self, plantilla: str) -> None:
        # Primero todo lo que solo lee: si algo no cierra, no se escribio nada.
        self.titulo("Buscar restos de corridas anteriores (cliente/list, por código, "
                    "por nombre y por id)")
        restos = self.restos(guardar_previos=True)
        self.salida(f"Restos encontrados: {restos or 'ninguno'}")
        self.verificar_restos(restos)

        self.titulo(f"Leer la plantilla '{plantilla}' (solo lectura) y ver el alta de cliente")
        molde = self.leer_plantilla(plantilla)
        self.foto = copy.deepcopy(molde)
        self.previos.add(_normal(molde.get(_clave(molde, "codigo", "Codigo"), plantilla)))
        ver = self.llamar("ver_endpoint", path=RECURSO, metodo="POST")
        flag = campo_activo(molde, ver)
        requeridos = campos_requeridos(ver)
        alta, sacadas = armar_alta(molde, flag, requeridos, self.copiar_resto)
        # Finnegans pide campos que el swagger no marca como requeridos (la categoria
        # fiscal, por ejemplo): se fijan con --campo en vez de copiar mas de la plantilla.
        alta.update(self.campos_extra)
        self.salida(f"Campos requeridos del swagger: {requeridos or '(no pude leerlos)'}")
        if self.campos_extra:
            self.salida(f"Campos fijados con --campo: {self.campos_extra}")
        self.salida(f"Claves de identidad sacadas del alta: {sacadas or 'ninguna'}")
        self.salida("Referencias a otros maestros que se copian tal cual: "
                    f"{referencias_copiadas(alta) or 'ninguna'}")
        self.salida(f"Campo de estado: {flag} = {alta[flag]!r} (plantilla: {molde.get(flag)!r})")
        unicas = claves_unicas(alta)
        if unicas:
            self.salida(f"Campos que parecen únicos y viajarían en el alta: {unicas}")
            if not self.permitir_campos_unicos:
                raise ErrorPrueba(
                    f"El alta copiaría campos que suelen ser únicos ({', '.join(unicas)}) y "
                    "Finnegans podría rechazarla o duplicarlos. No se escribió nada. Elegí "
                    "otra plantilla, o pasá --permitir-copiar-campos-unicos si no importa."
                )
        clave_nombre = _clave(alta, "nombre", "Nombre")

        if restos:
            self.titulo("Borrar restos")
            for codigo in restos:
                self.escribir("DELETE", id=codigo)
                # Ya no existe: si Finnegans reusa el codigo, el cliente nuevo es el nuestro.
                self.previos.discard(_normal(codigo))

        self.titulo(f"Alta (POST) del cliente de prueba '{NOMBRE_ALTA}', inactivo")
        self.pendiente_de_borrar = True
        texto_post = self.escribir("POST", body=alta)

        self.titulo("Verificar el alta: plantilla intacta, código asignado, nombre e inactivo")
        self.verificar_plantilla()  # antes que nada: un alta que pisa la plantilla es lo peor
        self.asignado = self.averiguar_asignado(texto_post)
        self.confirmar_asignado(self.asignado, flag)
        codigo = self.confirmado

        self.titulo(f"Editar '{codigo}' con PUT base + cambios")
        texto = self.escribir("PUT", id=codigo, base=self.tabla_prueba,
                              cambios={clave_nombre: NOMBRE_EDITADO})
        cambiados, _ = _partes_del_resumen(texto)
        if clave_nombre not in cambiados or NOMBRE_EDITADO not in cambiados:
            raise ErrorPrueba(
                f"El resumen no muestra el cambio de {clave_nombre} a '{NOMBRE_EDITADO}'."
            )

        self.titulo(f"Editar '{codigo}' con PUT y el registro completo en body")
        actual = self.leer_prueba()
        if actual.get(clave_nombre) != NOMBRE_EDITADO:
            raise ErrorPrueba(
                f"Tras el PUT con base el nombre quedó {actual.get(clave_nombre)!r}, "
                f"se esperaba {NOMBRE_EDITADO!r}."
            )
        body = copy.deepcopy(actual)
        body[clave_nombre] = NOMBRE_BODY
        texto = self.escribir("PUT", id=codigo, body=body)
        _partes_del_resumen(texto)  # sin base no hay 'antes': se verifica releyendo
        registro = self.leer_prueba()
        if registro.get(clave_nombre) != NOMBRE_BODY:
            raise ErrorPrueba(
                f"Tras el PUT con body el nombre quedó {registro.get(clave_nombre)!r}, "
                f"se esperaba {NOMBRE_BODY!r}."
            )

        self.titulo(f"Baja (DELETE) de '{codigo}' y verificación")
        self.escribir("DELETE", id=codigo)
        self.pendiente_de_borrar = False
        quedo, _ = self.leer_registro(codigo, TABLA_VERIFICACION, puede_no_existir=True)
        if quedo is not None:
            raise ErrorPrueba(f"El cliente de prueba '{codigo}' sigue existiendo después del "
                              "DELETE.")

        self.titulo("Verificar que no quedó nada en cliente/list y que la plantilla sigue igual")
        quedan = self.restos()
        if quedan:
            raise ErrorPrueba(f"Quedaron registros de prueba: {quedan}")
        self.verificar_plantilla()
        self.salida(
            f"\nTodo en orden: Finnegans le asignó el código '{codigo}' al cliente de prueba, "
            f"que se creó, editó y borró; no queda ningún {PREFIJO}* ni '{NOMBRE_PREFIJO}*' "
            "y la plantilla no cambió."
        )

    def _limpiar_tras_fallo(self) -> None:
        """Si la prueba se corto con el registro creado, intenta borrarlo.

        Solo borra el codigo del alta si fue confirmado (releido: nombre de prueba,
        inactivo y nuevo) o si empieza con ZZ-PRUEBA-MCP. Antes relee la plantilla: si
        ya no esta, cambio o no se puede leer, el alta podria ser la propia plantilla y
        NO se borra nada.
        """
        if not self.pendiente_de_borrar:
            return
        problema = self.estado_plantilla()
        if problema is not None:
            self.salida(
                f"\n--- La prueba se cortó y NO borro nada automáticamente: la plantilla "
                f"'{self.plantilla}' {problema}. Revisá a mano en Finnegans el cliente "
                f"'{self.plantilla}' y {self.cliente_de_prueba()} (puede haber "
                f"quedado ACTIVO). {NO_VOLVER_A_CORRER} ---"
            )
            return
        objetivo = self.confirmado
        if objetivo is None and self.asignado and self.asignado.startswith(PREFIJO):
            objetivo = self.asignado
        if objetivo is None:
            self.salida(
                "\n--- La prueba se cortó y NO borro nada automáticamente: no pude confirmar "
                f"qué cliente creó el alta. Revisá a mano en Finnegans "
                f"{self.cliente_de_prueba()} y los clientes llamados '{NOMBRE_ALTA}' "
                f"(puede haber quedado ACTIVO), y borralo si es de la prueba. "
                f"{NO_VOLVER_A_CORRER} ---"
            )
            return
        self.salida(f"\n--- La prueba se cortó: intento borrar el cliente de prueba '{objetivo}' ---")
        try:
            self.escribir("DELETE", id=objetivo)
            self.pendiente_de_borrar = False
        except Exception as e:  # noqa: BLE001
            self.salida(
                f"No pude borrar el cliente de prueba '{objetivo}' ({e}). Revisalo y borralo "
                f"a mano en Finnegans, y revisá también la plantilla '{self.plantilla}'."
            )


def _resumen_args(argumentos: Mapping[str, Any]) -> str:
    partes = []
    for k, v in argumentos.items():
        txt = repr(v)
        partes.append(f"{k}={txt if len(txt) <= 60 else txt[:57] + '...'}")
    return ", ".join(partes)


# ----------------------------------------------------------------------- main


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Prueba de escritura en vivo con un cliente descartable ('ZZ PRUEBA MCP - "
            "borrar'). ESCRIBE EN PRODUCCIÓN. Finnegans ignora el código del alta "
            "(ZZ-PRUEBA-MCP) y asigna el suyo: la prueba lo sigue y solo escribe sobre "
            "él después de releerlo y confirmar que es el cliente nuevo de prueba."
        ),
        add_help=True,
    )
    p.add_argument("--si-escribir-en-produccion", action="store_true",
                   help="confirmación obligatoria: esta prueba escribe en producción")
    p.add_argument("--plantilla", metavar="CODIGO",
                   help="código de un cliente existente, de BAJO VALOR (solo se lee), del "
                        "que se copian los campos obligatorios del alta")
    p.add_argument("--permitir-copiar-campos-unicos", action="store_true",
                   help="permite que el alta copie campos que suelen ser únicos (CUIT, "
                        "documento, email...); sin esto la prueba aborta antes de escribir")
    p.add_argument("--copiar-resto-de-la-plantilla", action="store_true",
                   help="si el alta con solo los campos requeridos es rechazada: copia toda "
                        "la plantilla (sin ids ni guids, salvo referencias como ProvinciaID)")
    p.add_argument("--campo", metavar="CLAVE=VALOR", action="append", default=[],
                   help="fija un campo del alta que Finnegans pide aunque el swagger no lo "
                        "marque requerido; repetible. Los que funcionaron en la primera "
                        "prueba en vivo: --campo CategoriaFiscalCodigo=CF --campo "
                        "IdentificacionTributariaCodigo=SINIDENTIFICACION (sin ellos el alta "
                        "de cliente da HTTP 500). No sirve para el código, el nombre ni el "
                        "estado activo")
    return p


_CAMPOS_FIJOS = {"codigo", "nombre", *_FLAGS_ACTIVO}


def _campos_extra(pares: list[str]) -> dict[str, str]:
    """Convierte los --campo CLAVE=VALOR; ValueError con el motivo si alguno no sirve."""
    campos: dict[str, str] = {}
    for par in pares:
        clave, igual, valor = par.partition("=")
        clave = clave.strip()
        if not igual or not re.fullmatch(r"[A-Za-z0-9_]+", clave):
            raise ValueError(f"--campo {par!r} no tiene la forma CLAVE=VALOR.")
        if clave.lower() in _CAMPOS_FIJOS:
            raise ValueError(f"--campo no puede cambiar '{clave}': lo fija la prueba.")
        campos[clave] = valor
    return campos


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None, *,
         client: Any = None, swagger: Any = None, docs: Any = None,
         salida: Callable[[str], None] = print) -> int:
    args = _parser().parse_args(argv)
    faltan = []
    if not args.si_escribir_en_produccion:
        faltan.append("--si-escribir-en-produccion")
    if not args.plantilla or not args.plantilla.strip():
        faltan.append("--plantilla CODIGO")
    try:
        campos_extra = _campos_extra(args.campo)
    except ValueError as e:
        print(f"{e} No se hizo nada.", file=sys.stderr)
        return 2
    if faltan:
        print(
            "Esta prueba ESCRIBE en Finnegans de producción (crea, modifica y borra un "
            f"cliente '{NOMBRE_ALTA}'). No se hizo nada: faltan {' y '.join(faltan)}.\n"
            "Ejemplo: uv run python scripts/prueba_escritura_en_vivo.py "
            "--si-escribir-en-produccion --plantilla CODIGO_DE_UN_CLIENTE "
            "--campo CategoriaFiscalCodigo=CF "
            "--campo IdentificacionTributariaCodigo=SINIDENTIFICACION",
            file=sys.stderr,
        )
        return 2

    settings = Settings.from_env() if env is None else Settings.from_env(env)
    sin_cargar = settings.faltantes()
    if sin_cargar:
        print(
            "Faltan variables de entorno de la configuración: "
            + ", ".join(sin_cargar)
            + ". Cargalas en la terminal (FINNEGANS_CLIENT_ID, FINNEGANS_CLIENT_SECRET, "
            "FINNEGANS_SWAGGER_KEY, FINNEGANS_DOCS_CLIENT_ID, FINNEGANS_DOCS_SECRET_KEY). "
            "No se hizo nada.",
            file=sys.stderr,
        )
        return 2

    plantilla = args.plantilla.strip()
    workspace = Workspace()
    try:
        server = crear_servidor(settings, client=client, swagger=swagger, docs=docs,
                                workspace=workspace)
        salida(
            f"PRUEBA DE ESCRITURA EN PRODUCCIÓN. Plantilla (solo lectura): {plantilla}. "
            f"Solo se escribe sobre códigos {PREFIJO}* o sobre el cliente de prueba que "
            "Finnegans cree, después de releerlo y confirmarlo."
        )
        Prueba(
            server, workspace, salida,
            permitir_campos_unicos=args.permitir_copiar_campos_unicos,
            copiar_resto=args.copiar_resto_de_la_plantilla,
            campos_extra=campos_extra,
        ).correr(plantilla)
    except ErrorPrueba as e:
        print(f"\nPRUEBA FALLIDA: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"\nPRUEBA FALLIDA por un error inesperado ({type(e).__name__}): {e}",
              file=sys.stderr)
        return 1
    finally:
        workspace.cerrar()
    salida("\nPRUEBA OK: todos los pasos dieron lo esperado (alta con el código que "
           "asignó Finnegans, dos PUT y la baja).")
    return 0


if __name__ == "__main__":
    # La consola de Windows no siempre es UTF-8: que los acentos no salgan rotos.
    for _flujo in (sys.stdout, sys.stderr):
        if hasattr(_flujo, "reconfigure"):
            _flujo.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
