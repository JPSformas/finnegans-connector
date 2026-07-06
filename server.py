"""Servidor MCP para Finnegans.

Expone el conector como herramientas para agentes (Claude Desktop,
Cursor, etc.). Por diseño de seguridad, esta version es de SOLO LECTURA:
no crea ni modifica datos en Finnegans.

Ejecutar (stdio):
    python server.py

Configuracion en un cliente MCP (ej. Claude Desktop), en su config JSON:
    {
      "mcpServers": {
        "finnegans": {
          "command": "python",
          "args": ["C:\\\\Users\\\\user\\\\finnegans-connector\\\\server.py"]
        }
      }
    }
Las credenciales se leen del archivo .env del proyecto.
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from finnegans import FinnegansClient, FinnegansError

mcp = FastMCP("finnegans")

_client: FinnegansClient | None = None


def get_client() -> FinnegansClient:
    global _client
    if _client is None:
        _client = FinnegansClient(timeout=25)
    return _client


def _fmt(data: Any) -> str:
    if isinstance(data, (dict, list)):
        return json.dumps(data, indent=2, ensure_ascii=False)
    return str(data)


@mcp.tool()
def verificar_conexion() -> str:
    """Verifica que las credenciales sean validas obteniendo un token.

    Devuelve un mensaje de estado (nunca el token completo).
    """
    try:
        token = get_client().get_token(force_refresh=True)
        return f"Conexion OK. Token vigente (longitud {len(token)})."
    except FinnegansError as e:
        return f"Error de conexion: {e}"


@mcp.tool()
def obtener_recurso(endpoint: str, id: str | None = None, parametros: dict | None = None) -> str:
    """Lectura generica de la API de Finnegans.

    Convencion: GET /api/{endpoint}/{id}?ACCESS_TOKEN=...
    El `id` (codigo del maestro) va en el path. `parametros` son
    filtros opcionales (clave/valor).

    Ejemplos de endpoint: "producto", "cliente",
    "ACOrdenesCompraPendientes", "composicionSaldoCliente".
    """
    try:
        return _fmt(get_client().get(endpoint, id=id, params=parametros))
    except FinnegansError as e:
        return f"Error: {e}"


@mcp.tool()
def obtener_producto(codigo: str) -> str:
    """Produccion / Compras: datos de un producto por su codigo de maestro."""
    try:
        return _fmt(get_client().producto(codigo))
    except FinnegansError as e:
        return f"Error: {e}"


@mcp.tool()
def obtener_cliente(codigo: str) -> str:
    """Ventas / Admin: datos de un cliente por su codigo de maestro."""
    try:
        return _fmt(get_client().cliente(codigo))
    except FinnegansError as e:
        return f"Error: {e}"


@mcp.tool()
def saldo_de_cliente(codigo_cliente: str) -> str:
    """Admin/Conta: composicion del saldo de un cliente."""
    try:
        return _fmt(get_client().saldo_cliente(codigo_cliente))
    except FinnegansError as e:
        return f"Error: {e}"


@mcp.tool()
def ordenes_compra_pendientes(proveedor: str) -> str:
    """Compras: ordenes de compra pendientes de un proveedor (por codigo)."""
    try:
        return _fmt(get_client().ordenes_compra_pendientes(proveedor))
    except FinnegansError as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run()
