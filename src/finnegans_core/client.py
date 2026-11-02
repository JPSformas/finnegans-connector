"""Cliente HTTP de la API de Finnegans (Teamplace / F3) sobre httpx2.

- Autenticacion client_credentials; el token se cachea en memoria 1 hora.
- Inyecta ACCESS_TOKEN en cada llamada y reintenta una vez ante 401/403.
- Todo mensaje de error pasa por el Redactor: ni credenciales ni tokens salen.
"""
from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote

import httpx2

from .config import Settings
from .secretos import Redactor

TTL_TOKEN_SEGUNDOS = 3600
TIMEOUT_SEGUNDOS = 30


class FinnegansError(Exception):
    """Error generico de la API de Finnegans."""


class FinnegansAuthError(FinnegansError):
    """Error de autenticacion (credenciales / token / direccion)."""


class FinnegansClient:
    def __init__(self, settings: Settings, http: httpx2.Client | None = None) -> None:
        self.settings = settings
        self.http = http if http is not None else httpx2.Client(timeout=TIMEOUT_SEGUNDOS)
        self.redactor = Redactor(settings.secretos())
        self._token: str | None = None
        self._token_ts = 0.0

    # ---------------------------------------------------------------- util
    def _base(self, exc: type[FinnegansError]) -> str:
        base = (self.settings.base_url or "").strip().rstrip("/")
        if not base.lower().startswith(("http://", "https://")):
            raise exc(
                self.redactor.limpiar(
                    "FINNEGANS_BASE_URL no es una direccion valida: tiene que "
                    f"empezar con https:// y llego como {base!r}. Revisa ese "
                    "campo de la configuracion (el valor correcto es "
                    "https://api.finneg.com)."
                )
            )
        return base

    # ---------------------------------------------------------------- auth
    def _pedir_token(self) -> str:
        url = self._base(FinnegansAuthError) + "/api/oauth/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
        }
        try:
            resp = self.http.get(url, params=params)
        except (httpx2.HTTPError, httpx2.InvalidURL, OSError, ValueError) as e:
            raise FinnegansAuthError(
                self.redactor.limpiar(f"No se pudo conectar a Finnegans: {e}")
            ) from None
        if resp.status_code >= 400:
            raise FinnegansAuthError(
                self.redactor.limpiar(
                    f"Fallo la autenticacion (HTTP {resp.status_code}). Revisa el "
                    f"Client ID y el Client secret. Detalle: {resp.text[:300]}"
                )
            )
        raw = resp.text.strip()
        token = raw
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                token = data.get("access_token") or data.get("token") or data.get("Token") or ""
        except json.JSONDecodeError:
            pass
        if not isinstance(token, str) or not token:
            raise FinnegansAuthError("La respuesta de autenticacion no contiene un token.")
        self.redactor.agregar(token)
        return token

    def token(self, forzar: bool = False) -> str:
        """Token valido; re-autentica si vencio o se fuerza."""
        vencido = (time.monotonic() - self._token_ts) > TTL_TOKEN_SEGUNDOS
        if forzar or self._token is None or vencido:
            self._token = self._pedir_token()
            self._token_ts = time.monotonic()
        return self._token

    # ------------------------------------------------------------- request
    def request(
        self,
        metodo: str,
        path: str,
        id: str | None = None,
        params: dict | None = None,
        body: Any = None,
    ) -> Any:
        """Llama a /api/{path}[/{id}] y devuelve el JSON parseado (o texto)."""
        return self._request(metodo.upper(), path, id, params, body, reintentar=True)

    def _request(self, metodo, path, id, params, body, reintentar):
        base = self._base(FinnegansError)
        ruta = f"/api/{path.strip('/')}"
        if id is not None:
            ruta += f"/{quote(str(id), safe='')}"
        query = dict(params or {})
        query["ACCESS_TOKEN"] = self.token()

        kwargs: dict[str, Any] = {"params": query, "headers": {"Accept": "application/json"}}
        if body is not None and metodo in {"POST", "PUT", "PATCH"}:
            kwargs["content"] = json.dumps(body, ensure_ascii=False).encode("utf-8")
            kwargs["headers"]["Content-Type"] = "application/json"

        try:
            resp = self.http.request(metodo, base + ruta, **kwargs)
        except (httpx2.HTTPError, httpx2.InvalidURL, OSError, ValueError) as e:
            raise FinnegansError(
                self.redactor.limpiar(f"No se pudo conectar a Finnegans ({path}): {e}")
            ) from None

        if resp.status_code in (401, 403) and reintentar:
            self.token(forzar=True)
            return self._request(metodo, path, id, params, body, reintentar=False)
        if resp.status_code >= 400:
            raise FinnegansError(
                self.redactor.limpiar(
                    f"Error en {metodo} {path} (HTTP {resp.status_code}): {resp.text[:400]}"
                )
            )
        try:
            return resp.json()
        except ValueError:
            return resp.text
