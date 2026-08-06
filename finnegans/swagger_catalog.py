"""Catalogo de APIs de Finnegans basado en el spec OpenAPI completo (swaggerGlobal).

Fuente de verdad de endpoints: baja el spec (Swagger 2.0) una vez, lo cachea
en memoria, y ofrece busqueda y extraccion de operaciones. Solo libreria estandar.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class SwaggerError(Exception):
    """Error al cargar o interpretar el spec de swaggerGlobal."""


_SPEC_CACHE: dict[str, dict] = {}


def _fetch_spec(url: str, key: str, timeout: int = 60) -> dict:
    full = f"{url}?key={urllib.parse.quote(key, safe='')}"
    req = urllib.request.Request(full, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def cargar_spec(url: str, key: str, *, force: bool = False) -> dict:
    """Devuelve el spec OpenAPI cacheado; lo baja en el primer uso o si force."""
    ck = f"{url}|{key}"
    if force or ck not in _SPEC_CACHE:
        try:
            _SPEC_CACHE[ck] = _fetch_spec(url, key)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as e:
            raise SwaggerError(
                "No pude cargar la documentacion de APIs de Finnegans (swaggerGlobal). "
                f"Revisa conectividad y FINNEGANS_SWAGGER_KEY. Detalle: {e}"
            ) from e
    return _SPEC_CACHE[ck]
