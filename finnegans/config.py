"""Carga de configuracion desde variables de entorno y .env.

Prioridad: variables de entorno reales > archivo .env.
No imprime ni expone secretos.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | os.PathLike | None = None) -> None:
    """Carga pares KEY=VALUE de un archivo .env al entorno.

    No sobreescribe variables ya definidas en el entorno real.
    """
    if path is None:
        path = Path(__file__).resolve().parent.parent / ".env"
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class Settings:
    """Configuracion del conector."""

    def __init__(self, load_env: bool = True) -> None:
        if load_env:
            load_dotenv()
        self.base_url = os.environ.get("FINNEGANS_BASE_URL", "https://api.finneg.com").rstrip("/")
        self.client_id = os.environ.get("FINNEGANS_CLIENT_ID")
        self.client_secret = os.environ.get("FINNEGANS_CLIENT_SECRET")
        self.workspace = os.environ.get("FINNEGANS_WORKSPACE")

    def require_credentials(self) -> None:
        missing = [
            name
            for name, val in (
                ("FINNEGANS_CLIENT_ID", self.client_id),
                ("FINNEGANS_CLIENT_SECRET", self.client_secret),
            )
            if not val
        ]
        if missing:
            raise RuntimeError(
                "Faltan credenciales: " + ", ".join(missing) + ". "
                "Configuralas en el archivo .env (ver .env.example)."
            )
