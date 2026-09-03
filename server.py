"""Agente Finnegans unificado — servidor MCP.

Combina en un solo recurso:
  1. Descubrimiento de APIs (catalogo Finnegans)
  2. Lectura (GET a cualquier endpoint)
  3. Escritura con validacion obligatoria (POST/PUT/DELETE)

Flujo para el agente de IA:
  buscar_api -> ver_api -> consultar_finnegans (lectura)
  buscar_api -> ver_api -> preparar_cambio -> [usuario confirma] -> ejecutar_cambio

Ejecutar:
    python server.py

Configuracion Claude Desktop (claude_desktop_config.json):
    {
      "mcpServers": {
        "finnegans-agent": {
          "command": "python",
          "args": ["C:\\\\FinnegansAgent\\\\server.py"]
        }
      }
    }
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from finnegans import FinnegansClient, FinnegansError
from finnegans import swagger_catalog
from finnegans.config import Settings
from finnegans.audit import AuditLog
from finnegans.discovery import (
    DiscoveryError, search_apis,
)
from finnegans.validator import (
    READ_METHODS, ChangeStore, ValidationError, WRITE_METHODS,
    evaluar_riesgo, validar_body, construir_preview, generar_codigo,
)

mcp = FastMCP(
    "finnegans-agent",
    instructions=(
        "Sos un asistente de Finnegans para lideres no tecnicos. "
        "REGLAS OBLIGATORIAS:\n"
        "1. Antes de consultar o modificar, usa buscar_api y ver_api para "
        "descubrir el endpoint correcto y sus parametros.\n"
        "2. Para LECTURAS usa consultar_finnegans (solo GET).\n"
        "3. Para ESCRITURAS usa preparar_cambio, mostra el PREVIEW completo al "
        "usuario (incluye un codigo de confirmacion) y pedile que tipee ese codigo.\n"
        "4. Solo cuando el usuario tipee el codigo, llama ejecutar_cambio con "
        "ese codigo_confirmacion. NUNCA inventes ni adivines el codigo.\n"
        "5. NUNCA ejecutes escrituras sin confirmacion del usuario.\n"
        "6. Responde siempre en castellano claro, sin tecnicismos."
    ),
)

_client: FinnegansClient | None = None
_changes = ChangeStore()
_settings: Settings | None = None
_audit: AuditLog | None = None


def get_client() -> FinnegansClient:
    global _client
    if _client is None:
        _client = FinnegansClient(timeout=30)
    return _client


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_audit() -> AuditLog:
    global _audit
    if _audit is None:
        s = get_settings()
        _audit = AuditLog(s.audit_log_path, s.operator)
    return _audit


def _fmt(data: Any) -> str:
    if isinstance(data, (dict, list)):
        return json.dumps(data, indent=2, ensure_ascii=False)
    return str(data)


def _truncate(data: Any, max_len: int = 3000) -> str:
    text = _fmt(data)
    if len(text) > max_len:
        return text[:max_len] + f"\n... (recortado, {len(text)} chars total)"
    return text


# ------------------------------------------------------------------ tools
@mcp.tool()
async def verificar_conexion() -> str:
    """Verifica credenciales de API y acceso al catalogo de documentacion."""
    lines = []
    try:
        token = get_client().get_token(force_refresh=True)
        lines.append(f"API Finnegans: OK (token len={len(token)})")
    except FinnegansError as e:
        lines.append(f"API Finnegans: ERROR - {e}")

    try:
        result = await search_apis("producto")
        count = result.get("count", 0) if isinstance(result, dict) else 0
        lines.append(f"Catalogo de APIs: OK ({count} resultados de prueba)")
    except (DiscoveryError, RuntimeError) as e:
        lines.append(f"Catalogo de APIs: ERROR - {e}")

    return "\n".join(lines)


@mcp.tool()
def buscar_api(consulta: str) -> str:
    """Busca APIs de Finnegans por nombre, id o descripcion (usa la doc OpenAPI oficial).

    Usar PRIMERO cuando el usuario pide algo y no sabes que endpoint usar.
    """
    s = get_settings()
    try:
        s.require_swagger_config()
        spec = swagger_catalog.cargar_spec(s.swagger_url, s.swagger_key)
    except (RuntimeError, swagger_catalog.SwaggerError) as e:
        return f"No pude acceder a la documentacion de APIs: {e}"
    resultados = swagger_catalog.buscar_endpoints(spec, consulta)
    if not resultados:
        return f"No se encontraron endpoints para '{consulta}'."
    lineas = [f"Encontrados {len(resultados)} endpoints para '{consulta}':"]
    for r in resultados:
        lineas.append(f"- {r['path']}  ({', '.join(r['metodos'])})  {r['resumen']}")
    lineas.append("\nUsa ver_api con el 'path' o el nombre del recurso (ej. 'cliente').")
    return "\n".join(lineas)


@mcp.tool()
def ver_api(api_id: str) -> str:
    """Muestra las operaciones reales de un recurso: metodos, paths y parametros.

    api_id puede ser un recurso ('cliente') o un path exacto ('reports/analisisFacturaVenta').
    """
    s = get_settings()
    try:
        s.require_swagger_config()
        spec = swagger_catalog.cargar_spec(s.swagger_url, s.swagger_key)
    except (RuntimeError, swagger_catalog.SwaggerError) as e:
        return f"No pude acceder a la documentacion de APIs: {e}"
    ops = swagger_catalog.ver_endpoint(spec, api_id)
    if not ops:
        return (f"No encontre operaciones para '{api_id}'. "
                "Proba buscar_api para ver el nombre exacto del recurso.")
    lineas = [f"Operaciones de '{api_id}':\n"]
    for o in ops:
        lineas.append(f"  {o['metodo']} /api{o['path']} — {o['resumen']}")
        if o["parametros"]:
            ps = ", ".join(f"{p['nombre']}{'*' if p['requerido'] else ''} ({p['ubicacion']})"
                           for p in o["parametros"])
            lineas.append(f"    Parametros: {ps}")
        if o["tiene_body"]:
            if o["body_schema_ok"]:
                req = ", ".join(o["body_requeridos"]) or "(sin requeridos)"
                lineas.append(f"    Body: campos {o['body_campos']} | requeridos: {req}")
            else:
                lineas.append("    Body: requerido, pero no se pudo leer su schema "
                              "de la documentacion.")
    lineas.append("\nPara leer: consultar_finnegans. Para escribir: preparar_cambio.")
    return "\n".join(lineas)


@mcp.tool()
def consultar_finnegans(
    api_id: str,
    metodo: str = "GET",
    id: str | None = None,
    parametros: dict | None = None,
) -> str:
    """Consulta de LECTURA a Finnegans (solo GET).

    api_id puede ser:
      - un recurso con codigo:  api_id='cliente', id='P01093'  -> /api/cliente/P01093
      - un listado:             api_id='cliente/list'          -> /api/cliente/list
      - un reporte:             api_id='reports/analisisFacturaVenta'
    parametros: filtros adicionales como query params (ej. FechaDesde).
    """
    metodo = metodo.upper()
    if metodo not in READ_METHODS:
        return (
            f"Metodo '{metodo}' no permitido en consultar_finnegans. "
            f"Usa preparar_cambio para escrituras ({', '.join(WRITE_METHODS)})."
        )
    try:
        data = get_client().request(metodo, api_id, id=id, params=parametros)
        return _truncate(data)
    except FinnegansError as e:
        msg = str(e)
        if "id missing" in msg.lower():
            return (
                f"El endpoint '{api_id}' requiere un codigo en el path "
                f"(ej. '{api_id}/CODIGO'), o usa la operacion de listado "
                f"'{api_id}/list'."
            )
        return f"Error en consulta: {msg}"


@mcp.tool()
def preparar_cambio(
    api_id: str,
    metodo: str,
    id: str | None = None,
    parametros: dict | None = None,
    datos: dict | None = None,
    descripcion: str = "",
) -> str:
    """Prepara una ESCRITURA en Finnegans sin ejecutarla (POST/PUT/DELETE).

    Devuelve una vista previa VERIFICADA y un codigo de confirmacion.
    MOSTRAR el preview al usuario y pedirle que tipee el codigo. Luego llamar
    ejecutar_cambio con ese codigo.
    """
    metodo = metodo.upper()
    settings = get_settings()
    audit = get_audit()

    if metodo not in WRITE_METHODS:
        return "Metodo no es de escritura. Usa consultar_finnegans para lecturas."

    bloqueado, alto_riesgo, motivo = evaluar_riesgo(
        metodo, id, api_id, settings.allow_delete, settings.high_risk_patterns
    )
    if bloqueado:
        audit.record("rechazado", metodo=metodo, api_id=api_id, resource_id=id,
                     parametros=parametros, body=datos, resultado="bloqueado", detalle=motivo)
        return f"OPERACION BLOQUEADA: {motivo}"

    # Traer schema del endpoint desde swaggerGlobal (degradar con aviso si falla)
    campos_body: list[str] = []
    body_schema = None
    try:
        settings.require_swagger_config()
        spec = swagger_catalog.cargar_spec(settings.swagger_url, settings.swagger_key)
        ops = swagger_catalog.ver_endpoint(spec, api_id)
        match = next((o for o in ops if o["metodo"] == metodo), None)
        if match and match["tiene_body"]:
            campos_body = match["body_campos"]
            # Si el schema no se resolvio, body_schema queda None para que
            # validar_body diga "sin schema" en vez de marcar TODOS los campos
            # como desconocidos.
            body_schema = match["body_schema"]
    except (RuntimeError, swagger_catalog.SwaggerError):
        body_schema = None  # validar_body avisara "sin schema"

    problemas = validar_body(datos, body_schema) if metodo in ("POST", "PUT", "PATCH") else []
    codigo = generar_codigo()
    preview = construir_preview(
        api_id, metodo, id, parametros, datos, campos_body, problemas,
        alto_riesgo, motivo, codigo,
    )

    pending = _changes.prepare(
        api_id=api_id, metodo=metodo, resource_id=id, parametros=parametros,
        body=datos, resumen=descripcion or f"{metodo} en {api_id}",
        codigo=codigo, preview=preview, alto_riesgo=alto_riesgo,
    )
    audit.record("preparado", metodo=metodo, api_id=api_id, resource_id=id,
                 parametros=parametros, body=datos,
                 confirmacion_id=pending.confirmacion_id, detalle=motivo)

    return (
        f"{preview}\n\n"
        f"confirmacion_id: {pending.confirmacion_id}\n"
        f"Cuando el usuario tipee el codigo, llama ejecutar_cambio con "
        f"confirmacion_id='{pending.confirmacion_id}' y codigo_confirmacion=<lo que tipeo>."
    )


@mcp.tool()
def ejecutar_cambio(confirmacion_id: str, codigo_confirmacion: str) -> str:
    """Ejecuta un cambio SOLO si el usuario tipeo el codigo de confirmacion correcto.

    Args:
        confirmacion_id: ID devuelto por preparar_cambio.
        codigo_confirmacion: el codigo que el USUARIO tipeo (no lo inventes).
    """
    audit = get_audit()
    try:
        pending = _changes.consume(confirmacion_id, codigo_confirmacion)
    except ValidationError as e:
        audit.record("rechazado", confirmacion_id=confirmacion_id,
                     codigo_ok=False, resultado="codigo/expiracion", detalle=str(e))
        return f"No ejecutado: {e}"

    try:
        data = get_client().request(
            pending.metodo, pending.api_id, id=pending.resource_id,
            params=pending.parametros, body=pending.body,
        )
    except FinnegansError as e:
        audit.record("error", metodo=pending.metodo, api_id=pending.api_id,
                     resource_id=pending.resource_id, confirmacion_id=confirmacion_id,
                     codigo_ok=True, resultado="error_api", detalle=str(e))
        return f"Error al ejecutar: {e}"

    # Read-back (verificacion posterior)
    rid_efectivo, verificacion = _read_back(pending, data)

    # Pasamos la verificacion CRUDA (dict para POST/PUT) para que redactar()
    # pueda enmascarar secretos antes de persistir en el log de auditoria.
    audit.record("ejecutado", metodo=pending.metodo, api_id=pending.api_id,
                 resource_id=rid_efectivo, confirmacion_id=confirmacion_id,
                 codigo_ok=True, resultado="OK", detalle=verificacion)

    return (
        f"CAMBIO EJECUTADO OK\n{_truncate(data)}\n\n"
        f"Verificacion posterior:\n{_truncate(verificacion)}"
    )


def _read_back(pending, data):
    """Relee el registro afectado para confirmar el estado resultante.

    Devuelve una tupla (rid_efectivo, resultado):
      - rid_efectivo: para POST, el id creado leido de la respuesta
        (Codigo/Id/id) o el resource_id original; en el resto, el resource_id.
      - resultado: para DELETE, un string de confirmacion/AVISO; para POST/PUT,
        el objeto CRUDO parseado que devolvio el GET (sin truncar). Ante un fallo,
        un string corto de mensaje. Nunca lanza excepciones.
    """
    rid = pending.resource_id
    if pending.metodo == "POST" and isinstance(data, dict):
        rid = data.get("Codigo") or data.get("Id") or data.get("id") or rid
    try:
        if not rid:
            return (rid, "(no se pudo identificar el registro para releer)")
        if pending.metodo == "DELETE":
            try:
                get_client().request("GET", pending.api_id, id=rid)
                return (rid, f"AVISO: el registro {rid} todavia responde a GET tras el DELETE.")
            except FinnegansError:
                return (rid, f"Confirmado: el registro {rid} ya no existe (DELETE OK).")
        leido = get_client().request("GET", pending.api_id, id=rid)
        return (rid, leido)
    except FinnegansError as e:
        return (rid, f"(no se pudo releer: {e})")


if __name__ == "__main__":
    mcp.run()
