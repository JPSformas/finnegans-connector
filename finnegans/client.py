"""Cliente HTTP para la API de Finnegans (Teamplace / F3).

Diseño:
- Autenticacion por client_credentials -> token (texto plano).
- Cache del token en memoria; se re-autentica solo cuando hace falta.
- Metodo generico `get()` que inyecta ACCESS_TOKEN en cada llamada.
- Metodos de conveniencia por area (lectura).
- Nunca loguea el client_secret ni el token completo.

Solo usa la libreria estandar (sin dependencias externas) para que
sea facil de correr y auditar.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import Settings


class FinnegansError(Exception):
    """Error generico de la API de Finnegans."""


class FinnegansAuthError(FinnegansError):
    """Error de autenticacion (credenciales / token)."""


class FinnegansClient:
    """Cliente de lectura para la API de Finnegans.

    Ejemplo:
        client = FinnegansClient()
        data = client.get("clienteList")
    """

    def __init__(
        self,
        settings: Settings | None = None,
        timeout: int = 30,
        token_ttl_seconds: int = 3600,
    ) -> None:
        self.settings = settings or Settings()
        self.settings.require_credentials()
        self.timeout = timeout
        self.token_ttl_seconds = token_ttl_seconds
        self._token: str | None = None
        self._token_ts: float = 0.0

    # ---------------------------------------------------------------- auth
    def _fetch_token(self) -> str:
        params = {
            "grant_type": "client_credentials",
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
        }
        url = f"{self.settings.base_url}/api/oauth/token?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace").strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise FinnegansAuthError(
                f"Fallo la autenticacion (HTTP {e.code}). Revisa client_id/client_secret. Detalle: {body[:300]}"
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise FinnegansAuthError(f"No se pudo conectar a Finnegans: {e}") from e

        # El endpoint puede devolver el token en texto plano o en JSON.
        token = raw
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                token = data.get("access_token") or data.get("token") or data.get("Token") or ""
        except json.JSONDecodeError:
            pass

        if not token:
            raise FinnegansAuthError("La respuesta de autenticacion no contiene un token.")
        return token

    def get_token(self, force_refresh: bool = False) -> str:
        """Devuelve un token valido, re-autenticando si expiro o se fuerza."""
        expired = (time.time() - self._token_ts) > self.token_ttl_seconds
        if force_refresh or self._token is None or expired:
            self._token = self._fetch_token()
            self._token_ts = time.time()
        return self._token

    # ------------------------------------------------------------- request
    def get(
        self,
        endpoint: str,
        id: str | None = None,
        params: dict[str, Any] | None = None,
        _retry_on_auth: bool = True,
    ) -> Any:
        """GET generico contra la API, inyectando el ACCESS_TOKEN.

        Args:
            endpoint: nombre del recurso, ej. "clienteList" o "cliente".
            id: id opcional para endpoints de tipo /recurso/{id}.
            params: filtros/query params adicionales.

        Returns:
            El cuerpo parseado (dict/list si es JSON, o texto).
        """
        endpoint = endpoint.strip("/")
        query = dict(params or {})
        query["ACCESS_TOKEN"] = self.get_token()

        path = f"/api/{endpoint}"
        if id is not None:
            path += f"/{urllib.parse.quote(str(id))}"
        url = f"{self.settings.base_url}{path}?" + urllib.parse.urlencode(query)

        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code in (401, 403) and _retry_on_auth:
                self.get_token(force_refresh=True)
                return self.get(endpoint, id=id, params=params, _retry_on_auth=False)
            raise FinnegansError(
                f"Error en GET {endpoint} (HTTP {e.code}): {body[:400]}"
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise FinnegansError(f"No se pudo conectar a Finnegans ({endpoint}): {e}") from e

        if "application/json" in ctype:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
        # Puede venir JSON aunque el content-type no lo indique.
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    # ------------------------------------------------- conveniencia / areas
    # Convencion CONFIRMADA contra la API real de esta cuenta:
    #   GET /api/{recurso}/{codigo}?ACCESS_TOKEN=...   (el id va en el PATH)
    # Un codigo inexistente devuelve 404; uno valido devuelve 200 + datos.
    # Los "List"/reportes requieren parametros definidos en el
    # "Diccionario de APIs" del espacio de trabajo (ver README).

    def producto(self, codigo: str) -> Any:
        """Produccion / Compras: un producto por su codigo del maestro."""
        return self.get("producto", id=codigo)

    def cliente(self, codigo: str) -> Any:
        """Ventas / Admin: un cliente por su codigo del maestro."""
        return self.get("cliente", id=codigo)

    def saldo_cliente(self, codigo_cliente: str) -> Any:
        """Admin/Conta: composicion del saldo de un cliente."""
        return self.get("composicionSaldoCliente", id=codigo_cliente)

    def ordenes_compra_pendientes(self, proveedor: str) -> Any:
        """Compras: ordenes de compra pendientes de un proveedor (por codigo)."""
        return self.get("ACOrdenesCompraPendientes", id=proveedor)

    def ordenes_compra_finalizadas(self, proveedor: str) -> Any:
        """Compras: ordenes de compra finalizadas de un proveedor (por codigo)."""
        return self.get("ACOrdenesCompraFinalizadas", id=proveedor)
