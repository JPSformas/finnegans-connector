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
from finnegans.discovery import DiscoveryError, get_api, list_methods, search_apis
from finnegans.validator import READ_METHODS, ChangeStore, ValidationError, WRITE_METHODS

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


def get_client() -> FinnegansClient:
    global _client
    if _client is None:
        _client = FinnegansClient(timeout=30)
    return _client


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
def verificar_conexion() -> str:
    """Verifica credenciales de API y acceso al catalogo de documentacion."""
    lines = []
    try:
        token = get_client().get_token(force_refresh=True)
        lines.append(f"API Finnegans: OK (token len={len(token)})")
    except FinnegansError as e:
        lines.append(f"API Finnegans: ERROR - {e}")

    try:
        result = search_apis("producto")
        count = result.get("count", 0) if isinstance(result, dict) else 0
        lines.append(f"Catalogo de APIs: OK ({count} resultados de prueba)")
    except (DiscoveryError, RuntimeError) as e:
        lines.append(f"Catalogo de APIs: ERROR - {e}")

    return "\n".join(lines)


@mcp.tool()
def buscar_api(consulta: str) -> str:
    """Busca APIs de Finnegans por nombre, id o descripcion.

    Usar PRIMERO cuando el usuario pide algo y no sabes que endpoint usar.
    Ejemplo: consulta="ordenes compra pendientes" o "saldo cliente".
    """
    try:
        result = search_apis(consulta)
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
def ver_api(api_id: str) -> str:
    """Obtiene la especificacion de una API: metodos, parametros y body.

    Llamar DESPUES de buscar_api para saber como invocar el endpoint.
    """
    try:
        result = get_api(api_id)
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
def preparar_cambio(
    api_id: str,
    metodo: str,
    id: str | None = None,
    parametros: dict | None = None,
    datos: dict | None = None,
    descripcion: str = "",
) -> str:
    """Prepara una ESCRITURA en Finnegans sin ejecutarla (POST/PUT/DELETE).

    Devuelve un resumen y un ID de confirmacion. MOSTRAR el resumen al
    usuario y ESPERAR que diga 'si' o 'confirmo' antes de llamar ejecutar_cambio.

    Args:
        api_id: id de la API.
        metodo: POST (crear), PUT (actualizar), DELETE (eliminar).
        id: codigo del registro (para PUT/DELETE o POST con path).
        parametros: query params adicionales.
        datos: body JSON con los datos a enviar.
        descripcion: resumen en castellano de lo que se va a hacer.
    """
    metodo = metodo.upper()
    if metodo not in WRITE_METHODS:
        return (
            f"Metodo '{metodo}' no es de escritura. "
            f"Usa consultar_finnegans para lecturas."
        )

    resumen = descripcion or f"{metodo} en {api_id}"
    if id:
        resumen += f" (id: {id})"
    if datos:
        preview = _truncate(datos, 500)
        resumen += f"\nDatos: {preview}"

    try:
        pending = _changes.prepare(
            api_id=api_id,
            metodo=metodo,
            resource_id=id,
            parametros=parametros,
            body=datos,
            resumen=resumen,
        )
        return (
            f"PENDIENTE DE CONFIRMACION\n"
            f"ID: {pending.confirmacion_id}\n"
            f"Accion: {resumen}\n\n"
            f"Mostrale esto al usuario y preguntale si confirma. "
            f"Si dice SI, llama ejecutar_cambio con "
            f"confirmacion_id='{pending.confirmacion_id}' y usuario_confirmo=true."
        )
    except ValidationError as e:
        return f"Error: {e}"


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
