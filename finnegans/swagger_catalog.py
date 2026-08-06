"""Catalogo de APIs de Finnegans basado en el spec OpenAPI completo (swaggerGlobal).

Fuente de verdad de endpoints: baja el spec (Swagger 2.0) una vez, lo cachea
en memoria, y ofrece busqueda y extraccion de operaciones. Solo libreria estandar.
"""
from __future__ import annotations

import json
import re
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


_METODOS_HTTP = {"get", "post", "put", "delete", "patch"}


def _tokens(texto: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (texto or "").lower()) if t]


def buscar_endpoints(spec: dict, consulta: str, limite: int = 8) -> list[dict]:
    q = set(_tokens(consulta))
    if not q:
        return []
    resultados: list[dict] = []
    for path, ops in (spec.get("paths") or {}).items():
        if not isinstance(ops, dict):
            continue
        metodos, tags, resumenes, opids = [], [], [], []
        for m, detail in ops.items():
            if m.lower() not in _METODOS_HTTP or not isinstance(detail, dict):
                continue
            metodos.append(m.upper())
            tags += detail.get("tags") or []
            resumenes.append(detail.get("summary", ""))
            opids.append(detail.get("operationId", ""))
        if not metodos:
            continue
        texto = " ".join([path] + tags + resumenes + opids)
        palabras = set(_tokens(texto))
        score = len(q & palabras)
        if score:
            resultados.append({
                "path": path,
                "metodos": metodos,
                "tags": sorted(set(tags)),
                "resumen": next((r for r in resumenes if r), ""),
                "score": float(score),
            })
    resultados.sort(key=lambda x: x["score"], reverse=True)
    return resultados[:limite]
