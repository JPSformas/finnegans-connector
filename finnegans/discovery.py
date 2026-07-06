"""Cliente del MCP de documentacion de Finnegans (catalogo de APIs).

Consulta el servicio remoto de Finnegans para buscar APIs y obtener
sus especificaciones OpenAPI. Usado por el agente para decidir que
endpoint llamar segun la pregunta del usuario.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from .config import Settings


class DiscoveryError(Exception):
    """Error al consultar el catalogo de APIs."""


def _parse_tool_result(result: Any) -> Any:
    """Extrae JSON del resultado de una tool MCP."""
    if result.isError:
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        raise DiscoveryError(" ".join(parts) or "Error en MCP de documentacion")

    for block in result.content:
        if hasattr(block, "text") and block.text:
            try:
                return json.loads(block.text)
            except json.JSONDecodeError:
                return block.text
    return None


async def _call_docs_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    settings = Settings()
    settings.require_docs_credentials()

    headers = {
        "x-client-id": settings.docs_client_id or "",
        "x-secret-key": settings.docs_secret_key or "",
    }
    async with streamablehttp_client(settings.docs_mcp_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return _parse_tool_result(result)


def search_apis(query: str) -> dict[str, Any]:
    """Busca APIs por nombre, id o descripcion."""
    return asyncio.run(_call_docs_tool("search_apis", {"query": query}))


def get_api(api_id: str) -> dict[str, Any]:
    """Obtiene la especificacion OpenAPI de una API."""
    return asyncio.run(_call_docs_tool("get_api", {"api": api_id}))


def list_methods(api_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Resume los metodos HTTP disponibles de una API."""
    structure = api_spec.get("request_structure") or api_spec.get("api") or {}
    paths = structure.get("paths") or {}
    methods: list[dict[str, Any]] = []

    for path, ops in paths.items():
        if not isinstance(ops, dict):
            continue
        for http_method, detail in ops.items():
            if http_method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                params = []
                if isinstance(detail, dict):
                    for p in detail.get("parameters") or []:
                        if isinstance(p, dict) and p.get("name") != "ACCESS_TOKEN":
                            params.append(
                                {
                                    "nombre": p.get("name"),
                                    "requerido": p.get("required", False),
                                    "ubicacion": p.get("in"),
                                    "descripcion": p.get("description", ""),
                                }
                            )
                methods.append(
                    {
                        "metodo": http_method.upper(),
                        "path": path,
                        "resumen": detail.get("summary", "") if isinstance(detail, dict) else "",
                        "parametros": params,
                        "tiene_body": bool(
                            isinstance(detail, dict) and detail.get("requestBodySchema")
                        ),
                    }
                )
    return methods
