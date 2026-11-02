"""Configuracion de la extension: las variables de entorno son la unica fuente.

Claude Desktop inyecta los valores del formulario de instalacion como variables
de entorno; no se lee ningun archivo .env. `from_env` nunca levanta: lo que falte
se informa despues con `faltantes()` para poder explicarselo al usuario.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

BASE_URL_DEFECTO = "https://api.finneg.com"
SWAGGER_URL_DEFECTO = "https://oneteam.finneg.com/BSA/api/swaggerGlobal"
DOCS_MCP_URL_DEFECTO = (
    "https://services.finneg.com/api/1/finnegans-developer-mcp/finnegans-api-docs/mcp"
)


def _valor(env: Mapping[str, str], clave: str, defecto: str = "") -> str:
    return (env.get(clave) or "").strip() or defecto


@dataclass(frozen=True)
class Settings:
    client_id: str = ""
    client_secret: str = ""
    swagger_key: str = ""
    docs_client_id: str = ""
    docs_secret_key: str = ""
    export_dir: str = ""
    base_url: str = BASE_URL_DEFECTO
    swagger_url: str = SWAGGER_URL_DEFECTO
    docs_mcp_url: str = DOCS_MCP_URL_DEFECTO

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        return cls(
            client_id=_valor(env, "FINNEGANS_CLIENT_ID"),
            client_secret=_valor(env, "FINNEGANS_CLIENT_SECRET"),
            swagger_key=_valor(env, "FINNEGANS_SWAGGER_KEY"),
            docs_client_id=_valor(env, "FINNEGANS_DOCS_CLIENT_ID"),
            docs_secret_key=_valor(env, "FINNEGANS_DOCS_SECRET_KEY"),
            export_dir=_valor(
                env, "FINNEGANS_EXPORT_DIR", str(Path.home() / "Documents" / "Finnegans")
            ),
            base_url=_valor(env, "FINNEGANS_BASE_URL", BASE_URL_DEFECTO),
            swagger_url=_valor(env, "FINNEGANS_SWAGGER_URL", SWAGGER_URL_DEFECTO),
            docs_mcp_url=_valor(env, "FINNEGANS_DOCS_MCP_URL", DOCS_MCP_URL_DEFECTO),
        )

    def faltantes(self) -> list[str]:
        """Etiquetas, en el orden del formulario, de las claves obligatorias sin cargar."""
        requeridas = (
            (self.client_id, "Client ID de Finnegans"),
            (self.client_secret, "Client secret de Finnegans"),
            (self.swagger_key, "Clave del swagger"),
            (self.docs_client_id, "Client ID de la documentación"),
            (self.docs_secret_key, "Secret key de la documentación"),
        )
        return [etiqueta for valor, etiqueta in requeridas if not valor]

    def secretos(self) -> list[str]:
        """Valores que nunca deben aparecer en ninguna salida."""
        valores = (
            self.client_id,
            self.client_secret,
            self.swagger_key,
            self.docs_client_id,
            self.docs_secret_key,
        )
        return [v for v in valores if v]
