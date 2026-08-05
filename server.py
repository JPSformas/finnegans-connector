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
from finnegans.config import Settings
from finnegans.audit import AuditLog
from finnegans.discovery import (
    DiscoveryError, get_api, list_methods, search_apis, extraer_schema_escritura,
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
        "3. Para ESCRITURAS usa preparar_cambio, mostra el resumen al usuario "
        "y ESPERA confirmacion explicita ('si', 'confirmo').\n"
        "4. Solo despues de confirmacion llama ejecutar_cambio con "
        "usuario_confirmo=true.\n"
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
async def buscar_api(consulta: str) -> str:
    """Busca APIs de Finnegans por nombre, id o descripcion.

    Usar PRIMERO cuando el usuario pide algo y no sabes que endpoint usar.
    Ejemplo: consulta="ordenes compra pendientes" o "saldo cliente".
    """
    try:
        result = await search_apis(consulta)
        if not isinstance(result, dict):
            return _fmt(result)

        if result.get("status") == "not_found":
            return f"No se encontraron APIs para '{consulta}'."

        candidates = result.get("results", [])
        summary = []
        for c in candidates[:8]:
            summary.append(
                f"- {c.get('id')} ({c.get('confidence', '?')}%): "
                f"{c.get('description', c.get('title', ''))}"
            )
        header = f"Encontradas {result.get('count', len(candidates))} APIs para '{consulta}':\n"
        return header + "\n".join(summary) + "\n\nUsa ver_api con el 'id' elegido."
    except (DiscoveryError, RuntimeError) as e:
        return f"Error buscando APIs: {e}"


@mcp.tool()
async def ver_api(api_id: str) -> str:
    """Obtiene la especificacion de una API: metodos, parametros y body.

    Llamar DESPUES de buscar_api para saber como invocar el endpoint.
    """
    try:
        result = await get_api(api_id)
        if not isinstance(result, dict):
            return _fmt(result)

        if result.get("status") == "not_found":
            return f"API '{api_id}' no encontrada."

        if result.get("status") == "ambiguous":
            candidates = result.get("candidates", [])
            lines = [f"API '{api_id}' es ambigua. Candidatos:"]
            for c in candidates[:5]:
                lines.append(f"  - {c.get('id')}: {c.get('description', '')}")
            return "\n".join(lines)

        methods = list_methods(result)
        if not methods:
            return (
                f"API '{api_id}' encontrada pero sin metodos documentados. "
                "Proba consultar_finnegans con GET y el id del recurso."
            )

        lines = [f"API: {api_id}\nMetodos disponibles:\n"]
        for m in methods:
            lines.append(f"  {m['metodo']} {m['path']} — {m['resumen']}")
            if m["parametros"]:
                params = ", ".join(
                    f"{p['nombre']}{'*' if p['requerido'] else ''}" for p in m["parametros"]
                )
                lines.append(f"    Parametros: {params}")
            if m["tiene_body"]:
                lines.append("    Requiere body JSON (ver schema en ver_api completo)")
        lines.append("\nPara leer: consultar_finnegans. Para escribir: preparar_cambio.")
        return "\n".join(lines)
    except (DiscoveryError, RuntimeError) as e:
        return f"Error obteniendo API: {e}"


@mcp.tool()
def consultar_finnegans(
    api_id: str,
    metodo: str = "GET",
    id: str | None = None,
    parametros: dict | None = None,
) -> str:
    """Consulta de LECTURA a Finnegans (solo GET).

    Args:
        api_id: id de la API (ej. "producto", "ACOrdenesCompraPendientes").
        metodo: debe ser GET (lectura).
        id: codigo del registro en el path (si la API lo requiere).
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
        return f"Error en consulta: {e}"


@mcp.tool()
async def preparar_cambio(
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

    # Traer schema del endpoint (degradar con aviso si falla)
    campos_body: list[str] = []
    body_schema = None
    try:
        spec = await get_api(api_id)
        if isinstance(spec, dict):
            info = extraer_schema_escritura(spec, metodo)
            campos_body = info["campos_body"]
            body_schema = info["body_schema"]
    except (DiscoveryError, RuntimeError):
        body_schema = None  # validar_body avisara "sin schema"

    problemas = validar_body(datos, body_schema) if metodo in ("POST", "PUT") else []
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
def ejecutar_cambio(confirmacion_id: str, usuario_confirmo: bool) -> str:
    """Ejecuta un cambio SOLO si el usuario confirmo explicitamente.

    Args:
        confirmacion_id: ID devuelto por preparar_cambio.
        usuario_confirmo: DEBE ser true. Si es false, no ejecuta nada.
    """
    try:
        pending = _changes.consume(confirmacion_id, usuario_confirmo)
        data = get_client().request(
            pending.metodo,
            pending.api_id,
            id=pending.resource_id,
            params=pending.parametros,
            body=pending.body,
        )
        return f"CAMBIO EJECUTADO OK\n{_truncate(data)}"
    except ValidationError as e:
        return f"No ejecutado: {e}"
    except FinnegansError as e:
        return f"Error al ejecutar: {e}"


if __name__ == "__main__":
    mcp.run()
