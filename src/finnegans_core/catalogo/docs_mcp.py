"""Cliente del MCP de documentacion de Finnegans (herramienta `search_apis`).

El servicio remoto indexa las APIs con su descripcion. Aca solo se usa para
buscar: cada resultado trae el id de la API (por ejemplo `ACOrdenesCompraDetalle`),
que corresponde al ultimo tramo del path del swagger (`/reports/ACOrdenesCompraDetalle`).

Los errores salen siempre como `DocsMcpError` con los secretos redactados: las
claves viajan en headers, pero un error de transporte puede repetirlas.
"""
from __future__ import annotations

import json
from typing import Any

import anyio
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ..config import Settings
from ..secretos import Redactor

TIMEOUT_SEGUNDOS = 30


class DocsMcpError(Exception):
    """El MCP de documentacion no respondio o respondio algo inesperado."""


def _campo(obj: Any, *nombres: str) -> Any:
    """Lee un campo de un dict (por alias JSON) o de un objeto (por atributo)."""
    for nombre in nombres:
        if isinstance(obj, dict):
            if nombre in obj:
                return obj[nombre]
        elif hasattr(obj, nombre):
            return getattr(obj, nombre)
    return None


def _texto_de(resultado: Any) -> str:
    partes = []
    for bloque in _campo(resultado, "content") or []:
        texto = _campo(bloque, "text")
        if texto:
            partes.append(str(texto))
    return " ".join(partes)


class DocsMcp:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redactor = Redactor(settings.secretos())

    async def buscar(self, consulta: str) -> list[dict]:
        """APIs que el MCP de documentacion asocia a la consulta: {path, resumen}."""
        if not (self._settings.docs_client_id and self._settings.docs_secret_key):
            raise DocsMcpError(
                "Faltan las credenciales de la documentación (client id y secret key)."
            )
        try:
            with anyio.fail_after(TIMEOUT_SEGUNDOS):
                crudo = await self._llamar(consulta)
            return self.parsear(crudo)
        except DocsMcpError as e:
            raise DocsMcpError(self._redactor.limpiar(e)) from None
        except Exception as e:  # transporte, timeout, ExceptionGroup de anyio...
            detalle = self._redactor.limpiar(f"{type(e).__name__}: {e}")
            raise DocsMcpError(
                f"No se pudo consultar la documentación de Finnegans ({detalle[:300]})"
            ) from None

    async def _llamar(self, consulta: str) -> Any:
        headers = {
            "x-client-id": self._settings.docs_client_id,
            "x-secret-key": self._settings.docs_secret_key,
        }
        async with httpx2.AsyncClient(headers=headers, timeout=TIMEOUT_SEGUNDOS) as http:
            async with streamable_http_client(
                self._settings.docs_mcp_url, http_client=http
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as sesion:
                    await sesion.initialize()
                    return await sesion.call_tool("search_apis", {"query": consulta})

    @staticmethod
    def parsear(resultado: Any) -> list[dict]:
        """Convierte el resultado de la herramienta en [{path, resumen}].

        Acepta el `CallToolResult` o su volcado JSON (claves camelCase).
        """
        if _campo(resultado, "isError", "is_error"):
            raise DocsMcpError(_texto_de(resultado) or "Error en el MCP de documentación")
        cuerpo = _campo(resultado, "structuredContent", "structured_content")
        if not isinstance(cuerpo, dict):
            try:
                cuerpo = json.loads(_texto_de(resultado))
            except (json.JSONDecodeError, TypeError):
                raise DocsMcpError("Respuesta inesperada del MCP de documentación") from None
        if not isinstance(cuerpo, dict):
            raise DocsMcpError("Respuesta inesperada del MCP de documentación")
        filas = []
        for item in cuerpo.get("results") or []:
            if not isinstance(item, dict):
                continue
            ident = str(item.get("id") or item.get("title") or "").strip()
            if ident:
                filas.append({
                    "path": ident,
                    "resumen": str(item.get("description") or "").strip(),
                })
        return filas
