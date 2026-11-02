"""Servidor MCP de Finnegans: 8 herramientas finas sobre finnegans_core.

Reglas que valen para todas las herramientas:
- Ninguna respuesta supera RESPUESTA_MAX_CHARS. Lo que no entra se pagina,
  se resume o se exporta, y la respuesta dice que se corto y como seguir.
- Ningun error llega crudo al cliente MCP: se traduce a castellano claro.
- Todo texto que sale pasa por el redactor (claves, secretos y token).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import anyio.to_thread
from mcp.server import MCPServer
from mcp_types import ToolAnnotations

from finnegans_core.catalogo.busqueda import buscar_endpoint, formatear_busqueda
from finnegans_core.catalogo.docs_mcp import DocsMcp, DocsMcpError
from finnegans_core.catalogo.swagger import Operacion, SwaggerCatalog, SwaggerError
from finnegans_core.client import FinnegansClient, FinnegansError
from finnegans_core.config import Settings
from finnegans_core.errores import traducir_error
from finnegans_core.exportar import exportar as exportar_archivo
from finnegans_core.guia import guia as guia_tema
from finnegans_core.presupuesto import RESPUESTA_MAX_CHARS, nombre_tabla, resumir_valor
from finnegans_core.secretos import Redactor
from finnegans_core.workspace import ConsultaInvalida, Resumen, Workspace

from .escritura import armar_body, diff
from .instrucciones import INSTRUCCIONES

METODOS_ESCRITURA = ("POST", "PUT", "PATCH", "DELETE")

# Tope de filas de busqueda: las del swagger (hasta 8) mas las que solo
# encontro la documentacion.
_BUSQUEDA_MAX_FILAS = 16
_RESUMEN_BUSQUEDA_MAX = 160
# Espacio para la lista de columnas en el resumen de una tabla grande.
_COLUMNAS_MAX_CHARS = 2500
_TIPO_COLUMNA_MAX = 60
_DESCRIPCION_MAX = 100
_RESPUESTA_API_MAX = 300
# Reserva para encabezados y pies alrededor de un listado.
_RESERVA = 600
# Loggers HTTP que en INFO escriben la URL completa: el token se pide con
# client_id/client_secret en el query string y el swagger lleva su key ahi.
# Claude Desktop guarda el stderr del servidor en su log.
_LOGGERS_HTTP = ("httpx2", "httpcore2", "httpx", "httpcore")


# ------------------------------------------------------------------ helpers


def _ajustar(texto: str, como_seguir: str) -> str:
    """El texto entero si entra; si no, cortado en un salto de linea y avisado."""
    if len(texto) <= RESPUESTA_MAX_CHARS:
        return texto
    plantilla = (
        "\n\n… (respuesta cortada para que entre en el chat: se muestran {n} de "
        f"{len(texto)} caracteres. {como_seguir})"
    )
    limite = RESPUESTA_MAX_CHARS - len(plantilla.format(n=len(texto)))
    corte = texto.rfind("\n", 0, limite + 1)
    if corte < limite // 2:
        corte = limite
    parte = texto[:corte].rstrip()
    return parte + plantilla.format(n=len(parte))


def _a_json(datos: Any) -> str:
    return json.dumps(datos, ensure_ascii=False, default=str)


def _mensaje_error(e: BaseException, api_id: str = "", id: str | None = None) -> str:
    """Texto en castellano para cualquier error del core (aun sin redactar)."""
    if isinstance(e, FinnegansError):
        return traducir_error(api_id, str(e), id)
    if isinstance(e, (SwaggerError, DocsMcpError, ConsultaInvalida, ValueError)):
        return str(e)
    if isinstance(e, TypeError):
        return f"Hay un valor que no se puede convertir a JSON: {e}"
    if isinstance(e, OSError):
        return f"No pude acceder al archivo o a la carpeta: {e}"
    return (
        f"Ocurrió un error inesperado ({type(e).__name__}): {e}. "
        "Si se repite, avisale a IT."
    )


def _formatear_parametro(p: dict) -> str:
    partes = [p.get("nombre") or "?"]
    extra = [x for x in (p.get("ubicacion"), "requerido" if p.get("requerido") else None) if x]
    if extra:
        partes.append(f"({', '.join(extra)})")
    texto = " ".join(partes)
    if p.get("descripcion"):
        texto += f": {resumir_valor(p['descripcion'], _DESCRIPCION_MAX)}"
    return texto


def _formatear_operacion(o: Operacion) -> str:
    linea = f"{o.metodo} {o.path} [{o.tipo}]"
    if o.resumen:
        linea += f" — {resumir_valor(o.resumen, _DESCRIPCION_MAX)}"
    lineas = [linea]
    if o.parametros:
        lineas.append("  Parámetros: " + "; ".join(_formatear_parametro(p) for p in o.parametros))
    if o.tiene_body:
        if not o.body_schema_ok:
            lineas.append("  Body: lleva body, pero su schema no está disponible en la documentación.")
        elif o.body_campos:
            requeridos = set(o.body_requeridos)
            campos = ", ".join(c + ("*" if c in requeridos else "") for c in o.body_campos)
            lineas.append(f"  Body ({len(o.body_campos)} campos, * = requerido): {campos}")
        else:
            lineas.append("  Body: el schema no declara campos.")
    return "\n".join(lineas)


def _formatear_columnas(tabla: str, columnas: list[tuple[str, str]]) -> str:
    """Columnas con su tipo, acotadas: un STRUCT puede ocupar cientos de KB."""
    partes: list[str] = []
    usado = 0
    tipos_cortados = False
    for nombre, tipo in columnas:
        if len(tipo) > _TIPO_COLUMNA_MAX:
            tipo = tipo[: _TIPO_COLUMNA_MAX - 1] + "…"
            tipos_cortados = True
        item = f"{nombre} ({tipo})"
        if usado + len(item) + 2 > _COLUMNAS_MAX_CHARS:
            break
        partes.append(item)
        usado += len(item) + 2
    texto = ", ".join(partes)
    resto = len(columnas) - len(partes)
    if resto:
        texto += (
            f" … y {resto} columnas más (para verlas: consultar(\"SELECT column_name "
            f"FROM (DESCRIBE {tabla})\"))"
        )
    if tipos_cortados:
        texto += (
            "\n(Los tipos largos están cortados con …; para ver uno completo: "
            f"consultar(\"SELECT column_name, column_type FROM (DESCRIBE {tabla}) "
            "WHERE column_name = '...'\"))"
        )
    return texto


# ------------------------------------------------------------------ servidor


def crear_servidor(
    settings: Settings,
    client: FinnegansClient | None = None,
    swagger: SwaggerCatalog | None = None,
    docs: DocsMcp | None = None,
    workspace: Workspace | None = None,
) -> MCPServer:
    """Arma el servidor con sus 8 herramientas. Cada dependencia se puede inyectar."""
    for nombre in _LOGGERS_HTTP:
        logging.getLogger(nombre).setLevel(logging.WARNING)
    client = client if client is not None else FinnegansClient(settings)
    swagger = swagger if swagger is not None else SwaggerCatalog(settings)
    docs = docs if docs is not None else DocsMcp(settings)
    workspace = workspace if workspace is not None else Workspace()
    redactor_propio = Redactor(settings.secretos())
    # Las herramientas sincronicas corren en hilos: DuckDB no se comparte en paralelo.
    candado = threading.RLock()

    def limpiar(texto: object) -> str:
        salida = str(texto)
        redactor = getattr(client, "redactor", None)
        if redactor is not None:
            salida = redactor.limpiar(salida)  # conoce tambien el token
        return redactor_propio.limpiar(salida)

    def responder(texto: object, como_seguir: str = "Pedí algo más acotado.") -> str:
        return _ajustar(limpiar(texto), como_seguir)

    server = MCPServer("finnegans", instructions=INSTRUCCIONES)

    # ------------------------------------------------------- buscar_endpoint

    @server.tool(
        name="buscar_endpoint",
        description=(
            "Busca qué endpoint de la API de Finnegans sirve para un pedido, en el "
            "swagger y en la documentación a la vez. Devuelve hasta 8 opciones con "
            "path, métodos, tipo y de qué fuente salió cada una, más notas cuando "
            "hay que preguntarle al usuario. Usala antes de leer o escribir."
        ),
        annotations=ToolAnnotations(
            title="Buscar endpoint", read_only_hint=True, idempotent_hint=True,
            open_world_hint=True,
        ),
        structured_output=False,
    )
    async def buscar_endpoint_tool(consulta: str) -> str:
        try:
            r = await buscar_endpoint(consulta, swagger, docs)
            sobran = len(r.filas) - _BUSQUEDA_MAX_FILAS
            r.filas = r.filas[:_BUSQUEDA_MAX_FILAS]
            for f in r.filas:
                f.resumen = resumir_valor(f.resumen, _RESUMEN_BUSQUEDA_MAX)
            texto = formatear_busqueda(r)
            if sobran > 0:
                texto += (
                    f"\n(Hay {sobran} resultados más de la documentación que no muestro; "
                    "si ninguno sirve, buscá con palabras más específicas.)"
                )
        except Exception as e:  # noqa: BLE001 - ningun error sale crudo
            texto = _mensaje_error(e)
        return responder(texto, "Buscá con palabras más específicas.")

    # ---------------------------------------------------------- ver_endpoint

    def _ver_operaciones(path: str) -> str:
        ops = swagger.ver(path)
        if not ops:
            return (
                f"No encontré '{path}' en la documentación de APIs. Usá buscar_endpoint "
                "para dar con el nombre correcto."
            )
        pie = ""
        if any(o.body_campos for o in ops):
            pie = (
                "\n\nLos campos anidados (listas como ...Items u objetos) se muestran "
                "solo por nombre; para ver sus subcampos: ver_endpoint(path, campo=...)."
            )
        detalle = "\n\n".join(_formatear_operacion(o) for o in ops) + pie
        if len(detalle) <= RESPUESTA_MAX_CHARS:
            return detalle
        # No entra el detalle: lista compacta de operaciones y como acotar.
        lineas: list[str] = []
        usado = 0
        for o in ops:
            linea = f"- {o.metodo} {o.path} [{o.tipo}]"
            if o.resumen:
                linea += f" — {resumir_valor(o.resumen, 50)}"
            if usado + len(linea) + 1 > RESPUESTA_MAX_CHARS - _RESERVA:
                break
            lineas.append(linea)
            usado += len(linea) + 1
        faltan = len(ops) - len(lineas)
        encabezado = (
            f"'{path}' tiene {len(ops)} operaciones: son demasiadas para mostrar su "
            "detalle. "
        )
        if faltan:
            encabezado += f"Muestro las primeras {len(lineas)} (faltan {faltan}). "
        encabezado += (
            "Para ver parámetros y body pedí un path exacto, por ejemplo "
            f"ver_endpoint('{ops[0].path}'), o usá buscar_endpoint para encontrar el "
            "que necesitás."
        )
        return encabezado + "\n\n" + "\n".join(lineas)

    def _ver_campo(path: str, campo: str) -> str:
        ops = swagger.ver(path)
        if not ops:
            return (
                f"No encontré '{path}' en la documentación de APIs. Usá buscar_endpoint "
                "para dar con el nombre correcto."
            )
        con_body = [o.metodo for o in ops if o.tiene_body]
        if not con_body:
            return f"'{path}' no tiene operaciones con body, así que no tiene el campo '{campo}'."
        orden = [m for m in ("PUT", "POST", "PATCH") if m in con_body]
        orden += [m for m in dict.fromkeys(con_body) if m not in orden]
        ultimo: SwaggerError | None = None
        for metodo in orden:
            try:
                sub = swagger.campo(path, metodo, campo)
            except SwaggerError as e:
                ultimo = e
                continue
            if not sub:
                return (
                    f"El campo '{campo}' del body de {metodo} '{path}' es un valor simple: "
                    "no tiene subcampos."
                )
            lineas = [f"Subcampos de '{campo}' (body de {metodo} '{path}'):"]
            for nombre, d in sub.items():
                d = d if isinstance(d, dict) else {}
                linea = f"- {nombre}"
                tipo = d.get("type")
                if tipo:
                    linea += f" ({tipo})"
                if tipo in ("object", "array") or "$ref" in d or "properties" in d:
                    linea += " [anidado]"
                if d.get("description"):
                    linea += f": {resumir_valor(d['description'], _DESCRIPCION_MAX)}"
                lineas.append(linea)
            return "\n".join(lineas)
        return str(ultimo)

    @server.tool(
        name="ver_endpoint",
        description=(
            "Muestra las operaciones de un recurso ('cliente') o de un path exacto "
            "('/reports/ACOrdenesCompraPendientes'): método, parámetros (con los "
            "requeridos marcados) y campos del body. Con campo='ProvinciaItems' "
            "detalla un campo anidado del body, un nivel."
        ),
        annotations=ToolAnnotations(
            title="Ver endpoint", read_only_hint=True, idempotent_hint=True,
            open_world_hint=True,
        ),
        structured_output=False,
    )
    def ver_endpoint_tool(path: str, campo: str | None = None) -> str:
        try:
            texto = _ver_campo(path, campo) if campo else _ver_operaciones(path)
        except Exception as e:  # noqa: BLE001
            texto = _mensaje_error(e, path)
        return responder(texto, "Pedí un path exacto o un campo puntual.")

    # ------------------------------------------------------------------ leer

    def _presentar_lectura(datos: Any, resumen: Resumen) -> str:
        if resumen.tabla is None:
            if isinstance(datos, list) and not datos:
                return resumen.nota or "La API devolvió una lista vacía (sin filas)."
            texto = datos if isinstance(datos, str) else _a_json(datos)
            directo = (
                "La API devolvió algo sin forma de tabla (no quedó cargado en el "
                f"workspace):\n{texto}"
            )
            if len(limpiar(directo)) <= RESPUESTA_MAX_CHARS:
                return directo
            return resumen.nota or "La API devolvió algo sin forma de tabla."

        t = resumen.tabla
        filas = resumen.filas
        uso = f"consultar(\"SELECT ... FROM {t}\")"
        if filas == 1:
            uso += f" o usala como base='{t}' en escribir"
        encabezado = (
            f"Cargué la respuesta en la tabla {t} ({filas} "
            f"fila{'s' if filas != 1 else ''}). Podés trabajarla con {uso}."
        )
        if filas <= RESPUESTA_MAX_CHARS // 10:
            directo = f"{encabezado}\n\n{_a_json(datos)}"
            if len(limpiar(directo)) <= RESPUESTA_MAX_CHARS:
                return directo

        partes = [
            f"Cargué la respuesta en la tabla {t}: {filas} fila{'s' if filas != 1 else ''} "
            f"y {len(resumen.columnas)} columnas. No la muestro entera porque no entra "
            "en el chat.",
            "Columnas: " + _formatear_columnas(t, resumen.columnas),
        ]
        if resumen.muestra:
            partes.append(f"Muestra (primeras filas, celdas largas cortadas con …):\n{resumen.muestra}")
        if resumen.nota:
            partes.append(f"Nota: {resumen.nota}")
        cierre = (
            f"Para analizarla usá {uso} (con ORDER BY si vas a paginar), o exportar "
            "para bajarla completa a Excel."
        )
        partes.append(cierre)
        return "\n\n".join(partes)

    @server.tool(
        name="leer",
        description=(
            "Lee de Finnegans con GET (nunca modifica nada). La respuesta queda "
            "cargada como tabla en el workspace (nombre automático, o el que pases "
            "en tabla). Si es chica devuelve el JSON; si es grande, solo el nombre de "
            "la tabla, cantidad de filas, columnas y una muestra: seguí con consultar "
            "o exportar. Los params van tal cual los escribe el swagger."
        ),
        annotations=ToolAnnotations(
            title="Leer de Finnegans", read_only_hint=True, idempotent_hint=True,
            open_world_hint=True,
        ),
        structured_output=False,
    )
    def leer_tool(
        path: str,
        id: str | None = None,
        params: dict | None = None,
        tabla: str | None = None,
    ) -> str:
        try:
            datos = client.request("GET", path, id=id, params=params)
        except Exception as e:  # noqa: BLE001
            return responder(_mensaje_error(e, path, id))
        nombre = nombre_tabla(tabla) if tabla else nombre_tabla(path, id)
        try:
            with candado:
                resumen = workspace.cargar(nombre, datos)
            texto = _presentar_lectura(datos, resumen)
        except Exception as e:  # noqa: BLE001
            texto = _mensaje_error(e)
        return responder(texto, f"Usá consultar sobre la tabla {nombre} para ver el resto.")

    # ------------------------------------------------------------- consultar

    @server.tool(
        name="consultar",
        description=(
            "SQL de solo lectura (DuckDB) sobre las tablas que cargó leer: SELECT, "
            "WITH, SHOW TABLES, DESCRIBE tabla, SUMMARIZE tabla. Devuelve una página "
            "que entra en el chat, el total de filas y cómo pedir la siguiente "
            "(desde=N). Los campos anidados se abren con UNNEST."
        ),
        annotations=ToolAnnotations(
            title="Consultar el workspace", read_only_hint=True, idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=False,
    )
    def consultar_tool(sql: str, desde: int = 0) -> str:
        try:
            with candado:
                texto = workspace.consultar(sql, desde)
        except ConsultaInvalida as e:
            texto = f"{e}\nPara ver qué tablas hay cargadas: consultar(\"SHOW TABLES\")."
        except Exception as e:  # noqa: BLE001
            texto = _mensaje_error(e)
        return responder(texto, "Pedí menos columnas o filas, o usá exportar.")

    # -------------------------------------------------------------- exportar

    @server.tool(
        name="exportar",
        description=(
            "Ejecuta una consulta SQL de solo lectura sobre el workspace y guarda el "
            "resultado completo en un archivo xlsx o csv en la carpeta de exportación "
            "configurada (nunca pisa un archivo existente). Devuelve la ruta y la "
            "cantidad de filas."
        ),
        annotations=ToolAnnotations(
            title="Exportar a archivo", read_only_hint=False, destructive_hint=False,
            idempotent_hint=False, open_world_hint=False,
        ),
        structured_output=False,
    )
    def exportar_tool(sql: str, formato: str = "xlsx", nombre: str | None = None) -> str:
        fmt = (formato or "xlsx").strip().lower().lstrip(".")
        if fmt not in ("xlsx", "csv"):
            return responder(f"No sé exportar en formato '{formato}': usá 'xlsx' o 'csv'.")
        try:
            with candado:
                columnas, filas = workspace.ejecutar(sql)
            carpeta = (
                Path(settings.export_dir) if settings.export_dir
                else Path.home() / "Documents" / "Finnegans"
            )
            base = nombre or f"finnegans-{datetime.now():%Y%m%d-%H%M%S}"
            ruta = exportar_archivo(columnas, filas, carpeta, base, fmt)
        except ConsultaInvalida as e:
            return responder(f"{e}\nPara ver qué tablas hay cargadas: consultar(\"SHOW TABLES\").")
        except Exception as e:  # noqa: BLE001
            return responder(_mensaje_error(e))
        return responder(
            f"Listo: exporté {len(filas)} fila{'s' if len(filas) != 1 else ''} "
            f"a {ruta}"
        )

    # -------------------------------------------------------------- escribir

    def _registro_base(base: str) -> tuple[dict | None, str | None]:
        """(registro, None) o (None, mensaje para Claude)."""
        try:
            with candado:
                crudo = workspace.crudo(base)
        except KeyError:
            return None, (
                f"No hay ninguna tabla '{base}' cargada en el workspace. Primero cargá "
                "el registro con leer(path, id=CODIGO) y pasá como base el nombre de "
                "tabla que te devuelva."
            )
        if isinstance(crudo, list) and len(crudo) == 1 and isinstance(crudo[0], dict):
            return crudo[0], None
        if isinstance(crudo, dict):
            return crudo, None
        if isinstance(crudo, list) and len(crudo) > 1:
            return None, (
                f"La tabla '{base}' tiene {len(crudo)} registros y base tiene que ser uno "
                "solo. Cargá el registro puntual con leer(path, id=CODIGO) y usá esa "
                "tabla como base."
            )
        return None, (
            f"La tabla '{base}' no contiene un registro (un objeto JSON). Cargá el "
            "registro con leer(path, id=CODIGO) y usá esa tabla como base."
        )

    def _tipo_endpoint(path: str) -> str:
        """Tipo del endpoint segun el swagger; prueba el path y luego su recurso."""
        tipo = swagger.tipo(path)
        if tipo != "otro":
            return tipo
        recurso = path.strip("/").split("/")[0].lower()
        for p in swagger.spec().get("paths") or {}:
            if p.strip("/").split("/")[0].lower() == recurso:
                t = swagger.tipo(p)
                if t != "otro":
                    return t
        return tipo

    @server.tool(
        name="escribir",
        description=(
            "Escribe en Finnegans (producción) de inmediato: POST, PUT, PATCH o "
            "DELETE. Para modificar un registro cargalo antes con leer y pasá "
            "base=<tabla> + cambios={campo: valor}: se manda el registro completo con "
            "solo esos campos cambiados. O mandá el registro completo en body. "
            "params va en la URL (por ejemplo {'createIfNotExists': '1'} para upsert). "
            "Devuelve el estado y, en entidades, qué campos cambiaron y cuáles cambió "
            "la API por su cuenta: mostráselo al usuario."
        ),
        annotations=ToolAnnotations(
            title="Escribir en Finnegans", read_only_hint=False, destructive_hint=True,
            idempotent_hint=False, open_world_hint=True,
        ),
        structured_output=False,
    )
    def escribir_tool(
        metodo: str,
        path: str,
        id: str | None = None,
        body: dict | None = None,
        base: str | None = None,
        cambios: dict | None = None,
        params: dict | None = None,
    ) -> str:
        estado = {"enviado": False}
        try:
            return _escribir(estado, metodo, path, id, body, base, cambios, params)
        except Exception as e:  # noqa: BLE001 - ningun error sale crudo
            if estado["enviado"]:
                aviso = (
                    "Finnegans aceptó la escritura, pero falló algo al armar el resumen. "
                    "Verificá el registro con leer antes de seguir."
                )
            else:
                aviso = "No se envió nada a Finnegans."
            return responder(f"{aviso}\n{_mensaje_error(e, path, id)}")

    def _escribir(estado, metodo, path, id, body, base, cambios, params) -> str:
        m = (metodo or "").strip().upper()
        if m not in METODOS_ESCRITURA:
            return responder(
                f"escribir solo hace POST, PUT, PATCH o DELETE (llegó '{metodo}'). "
                "Para leer datos usá leer."
            )
        destino = f"{path.strip('/')}/{id}" if id else path.strip("/")
        if m == "DELETE":
            if body is not None or base is not None or cambios:
                return responder(
                    "DELETE no lleva body, base ni cambios: indicá solo path e id. No se "
                    "envió nada a Finnegans."
                )
            enviado: dict = {}
            antes = None
        else:
            antes = None
            if base is not None:
                antes, problema = _registro_base(base)
                if problema:
                    return responder(problema + " No se envió nada a Finnegans.")
            try:
                enviado = armar_body(body, antes, cambios)
            except ValueError as e:
                return responder(f"{e} No se envió nada a Finnegans.")
            if not enviado:
                return responder(
                    f"Falta el body para {m}: pasá el registro completo en body, o base + "
                    "cambios. No se envió nada a Finnegans."
                )

        try:
            respuesta = client.request(
                m, path, id=id, params=params, body=enviado if m != "DELETE" else None,
            )
        except TypeError as e:
            return responder(
                "No se envió nada a Finnegans: el body tiene un valor que no se puede "
                f"convertir a JSON ({e})."
            )
        except Exception as e:  # noqa: BLE001
            return responder(f"La escritura {m} {destino} falló.\n{_mensaje_error(e, path, id)}")
        estado["enviado"] = True

        if m == "DELETE":
            lineas = [f"Registro eliminado: DELETE {destino} se ejecutó correctamente."]
        else:
            lineas = [f"{m} {destino}: listo, Finnegans aceptó la escritura."]
        if respuesta not in (None, "", {}, []):
            lineas.append(f"Respuesta de la API: {resumir_valor(respuesta, _RESPUESTA_API_MAX)}")
        if m not in ("PUT", "POST"):
            return responder("\n".join(lineas))

        try:
            tipo = _tipo_endpoint(path)
        except Exception as e:  # noqa: BLE001
            lineas.append(
                "La escritura se hizo, pero no pude confirmar en el swagger el tipo del "
                f"endpoint, así que no releí el registro: {_mensaje_error(e)}"
            )
            return responder("\n".join(lineas))
        if tipo != "entidad":
            return responder("\n".join(lineas))

        codigo = id or (str(enviado.get("Codigo")) if enviado.get("Codigo") else None)
        if not codigo:
            lineas.append(
                "No releí el registro para compararlo: no sé su código (pasá id o "
                "incluí Codigo en el body)."
            )
            return responder("\n".join(lineas))
        ruta_lectura = path.strip("/")
        if id is None and ruta_lectura.endswith("/" + codigo):
            ruta_lectura = ruta_lectura[: -len(codigo) - 1]
        try:
            despues = client.request("GET", ruta_lectura, id=codigo)
        except Exception as e:  # noqa: BLE001
            lineas.append(
                "La escritura se hizo, pero no pude releer el registro para compararlo: "
                f"{_mensaje_error(e, ruta_lectura, codigo)}"
            )
            return responder("\n".join(lineas))
        if isinstance(despues, list) and len(despues) == 1:
            despues = despues[0]
        if not isinstance(despues, dict):
            lineas.append("La relectura no devolvió un registro para comparar.")
            return responder("\n".join(lineas))

        if base is not None:
            try:
                with candado:
                    workspace.cargar(base, despues)
                lineas.append(
                    f"Actualicé la tabla {base} con el registro releído: para otro cambio "
                    "usala de nuevo como base."
                )
            except Exception as e:  # noqa: BLE001
                lineas.append(f"No pude actualizar la tabla {base}: {_mensaje_error(e)}")
        encabezado = "\n".join(lineas)
        disponible = RESPUESTA_MAX_CHARS - len(encabezado) - 2
        texto = encabezado + "\n\n" + diff(antes, enviado, despues, max_chars=disponible)
        return responder(texto, f"Para ver el registro completo: leer('{ruta_lectura}', id='{codigo}').")

    # ------------------------------------------------------------------ guia

    @server.tool(
        name="guia",
        description=(
            "Reglas del negocio y de la API de Finnegans: sucursales, iibb, rutas, "
            "tipos, escrituras, clientes, parametros. Sin tema devuelve la lista."
        ),
        annotations=ToolAnnotations(
            title="Guía de negocio", read_only_hint=True, idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=False,
    )
    def guia_tool(tema: str | None = None) -> str:
        try:
            texto = guia_tema(tema)
        except Exception as e:  # noqa: BLE001
            texto = _mensaje_error(e)
        return responder(texto, "Pedí otro tema con guia(tema).")

    # ---------------------------------------------------- verificar_conexion

    def _diagnostico_token(e: BaseException) -> str:
        bajo = str(e).lower()
        if "no se pudo conectar" in bajo:
            return (
                "No pude conectarme a Finnegans: puede ser internet o que el servicio "
                "esté caído. Volvé a probar en unos minutos."
            )
        if "finnegans_base_url" in bajo:
            return "La dirección de la API (FINNEGANS_BASE_URL) no es válida."
        return "Finnegans rechazó la clave: revisá el Client ID / secret de Finnegans."

    @server.tool(
        name="verificar_conexion",
        description=(
            "Revisa la configuración de la extensión: que estén todas las claves, que "
            "Finnegans dé un token, que cargue el swagger y que responda la "
            "documentación. Dice en castellano qué clave está mal."
        ),
        annotations=ToolAnnotations(
            title="Verificar conexión", read_only_hint=True, idempotent_hint=True,
            open_world_hint=True,
        ),
        structured_output=False,
    )
    async def verificar_conexion_tool() -> str:
        lineas = ["Verificación de la conexión con Finnegans:"]
        faltan = settings.faltantes()
        if faltan:
            lineas.append(
                "Faltan claves en la configuración de la extensión: "
                + ", ".join(faltan) + ". Cargalas en la configuración de la extensión "
                "en Claude Desktop."
            )

        if settings.client_id and settings.client_secret:
            try:
                await anyio.to_thread.run_sync(client.token, True)
                lineas.append("- API de Finnegans (token): OK")
            except Exception as e:  # noqa: BLE001
                lineas.append(f"- API de Finnegans (token): ERROR. {_diagnostico_token(e)}")
        else:
            lineas.append(
                "- API de Finnegans (token): sin verificar, falta el Client ID / secret "
                "de Finnegans."
            )

        if settings.swagger_key:
            try:
                spec = await anyio.to_thread.run_sync(swagger.spec)
                n = len(spec.get("paths") or {})
                lineas.append(f"- Swagger (catálogo de APIs): OK ({n} endpoints)")
            except Exception as e:  # noqa: BLE001
                if any(f"http {c}" in str(e).lower() for c in (401, 403)):
                    detalle = "Finnegans rechazó la Clave del swagger."
                else:
                    detalle = f"Revisá la conectividad y la Clave del swagger. Detalle: {e}"
                lineas.append(f"- Swagger (catálogo de APIs): ERROR. {detalle}")
        else:
            lineas.append("- Swagger (catálogo de APIs): sin verificar, falta la Clave del swagger.")

        if settings.docs_client_id and settings.docs_secret_key:
            try:
                await docs.buscar("cliente")
                lineas.append("- Documentación de Finnegans (MCP de docs): OK")
            except Exception as e:  # noqa: BLE001
                lineas.append(
                    "- Documentación de Finnegans (MCP de docs): ERROR. No respondió o "
                    "rechazó las claves (Client ID de la documentación / Secret key de la "
                    "documentación). La búsqueda sigue funcionando solo con el swagger. "
                    f"Detalle: {resumir_valor(e, _RESPUESTA_API_MAX)}"
                )
        else:
            lineas.append(
                "- Documentación de Finnegans (MCP de docs): sin verificar, faltan sus "
                "claves. La búsqueda funciona solo con el swagger."
            )
        return responder("\n".join(lineas))

    return server


def main() -> None:
    """Punto de entrada de la extension: servidor MCP por stdio."""
    crear_servidor(Settings.from_env()).run()


if __name__ == "__main__":
    main()
