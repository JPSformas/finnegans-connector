# Fuente de verdad swaggerGlobal + Diccionario de negocio — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-apuntar el descubrimiento de APIs del conector al spec OpenAPI completo de Finnegans (`swaggerGlobal`, fetcheable por HTTP) como fuente autoritativa, y darle al asistente de los líderes un diccionario de negocio con el hábito de pedir los datos que falten.

**Architecture:** Un módulo nuevo `finnegans/swagger_catalog.py` baja y cachea el spec (Swagger 2.0) y ofrece funciones puras de búsqueda y de extracción de operaciones/paths/parámetros. `server.py` re-apunta `buscar_api`, `ver_api` y el schema de `preparar_cambio` a ese módulo. `consultar_finnegans` accede a los paths reales (`/{entidad}/list`, `/reports/{Nombre}`) y traduce el error `id missing`. El diccionario de negocio es texto en `ASSISTANT_INSTRUCTIONS.md`.

**Tech Stack:** Python 3.10+, solo librería estándar (`urllib`, `json`), `mcp` (FastMCP) ya presente, tests con `unittest`.

## Global Constraints

- Solo **librería estándar** en el cliente HTTP y el catálogo (sin dependencias nuevas). Copiado del diseño Nivel 3.
- El spec de Finnegans es **Swagger 2.0** (`swagger`, `basePath`, `definitions`, `paths`; body como parámetro `in: "body"` con `schema` que puede ser `$ref` a `#/definitions/...`).
- El `key` de swaggerGlobal es **estable** y va en `.env` (`FINNEGANS_SWAGGER_KEY`), **nunca hardcodeado**.
- `swaggerGlobal` es **autoritativa** para paths/params; el MCP `finnegans-api-docs` queda como apoyo secundario, no como verdad de paths.
- Mensajes de error y de usuario **en castellano claro**.
- Tests con `unittest`; correr con `python -m unittest tests.<módulo> -v`.
- Nunca loguear ni imprimir `client_secret`, token completo ni el `key`.

---

### Task 1: Config — variables del spec swaggerGlobal

**Files:**
- Modify: `finnegans/config.py:53-59` (bloque de config del MCP de docs; agregar debajo)
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Settings` (existente).
- Produces: `Settings.swagger_url: str` (default `https://oneteam.finneg.com/BSA/api/swaggerGlobal`), `Settings.swagger_key: str | None`, y `Settings.require_swagger_config() -> None`.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_config.py`:

```python
    def test_swagger_defaults_y_key(self):
        import os
        os.environ.pop("FINNEGANS_SWAGGER_URL", None)
        os.environ.pop("FINNEGANS_SWAGGER_KEY", None)
        s = self._settings({"FINNEGANS_SWAGGER_KEY": "abc123"})
        self.assertEqual(s.swagger_url, "https://oneteam.finneg.com/BSA/api/swaggerGlobal")
        self.assertEqual(s.swagger_key, "abc123")
        s.require_swagger_config()  # no lanza

    def test_require_swagger_config_sin_key_lanza(self):
        import os
        os.environ.pop("FINNEGANS_SWAGGER_KEY", None)
        s = self._settings({})
        with self.assertRaises(RuntimeError):
            s.require_swagger_config()
```

Nota: `_settings` ya hace `Settings(load_env=False)`; agregá `FINNEGANS_SWAGGER_URL` y `FINNEGANS_SWAGGER_KEY` a la lista de claves que limpia al inicio de `_settings`.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m unittest tests.test_config -v`
Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'swagger_url'`).

- [ ] **Step 3: Implementar el mínimo**

En `finnegans/config.py`, después del bloque `docs_*` (línea ~59), agregar:

```python
        # Documentacion OpenAPI completa (swaggerGlobal de oneteam) — fuente de verdad
        self.swagger_url = os.environ.get(
            "FINNEGANS_SWAGGER_URL",
            "https://oneteam.finneg.com/BSA/api/swaggerGlobal",
        ).rstrip("/")
        self.swagger_key = os.environ.get("FINNEGANS_SWAGGER_KEY")
```

Y agregar el método (junto a los otros `require_*`):

```python
    def require_swagger_config(self) -> None:
        if not self.swagger_key:
            raise RuntimeError(
                "Falta FINNEGANS_SWAGGER_KEY en el .env. Es la clave de lectura de "
                "la documentacion OpenAPI de Finnegans (swaggerGlobal). Ver .env.example."
            )
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m unittest tests.test_config -v`
Expected: PASS.

- [ ] **Step 5: Actualizar `.env.example`**

Agregar al final:

```env
# Documentacion OpenAPI completa (fuente de verdad de endpoints).
# El key es de solo lectura de documentacion y es estable.
FINNEGANS_SWAGGER_URL=https://oneteam.finneg.com/BSA/api/swaggerGlobal
FINNEGANS_SWAGGER_KEY=435f45445548
```

- [ ] **Step 6: Commit**

```bash
git add finnegans/config.py tests/test_config.py .env.example
git commit -m "feat(config): settings de swaggerGlobal (URL + key) como fuente de verdad"
```

---

### Task 2: swagger_catalog — cargar y cachear el spec

**Files:**
- Create: `finnegans/swagger_catalog.py`
- Test: `tests/test_swagger_catalog.py`

**Interfaces:**
- Consumes: nada de tareas previas.
- Produces:
  - `class SwaggerError(Exception)`
  - `cargar_spec(url: str, key: str, *, force: bool = False) -> dict` — cachea en memoria por `url|key`; llama a `_fetch_spec` solo en miss o `force`.
  - `_fetch_spec(url: str, key: str, timeout: int = 60) -> dict` — GET real (se monkeypatchea en tests).

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_swagger_catalog.py`:

```python
import unittest
from finnegans import swagger_catalog as sc


class TestCargarSpec(unittest.TestCase):
    def setUp(self):
        sc._SPEC_CACHE.clear()
        self._calls = []

    def _fake_fetch(self, url, key, timeout=60):
        self._calls.append((url, key))
        return {"swagger": "2.0", "paths": {}}

    def test_cachea_tras_primera_carga(self):
        sc._fetch_spec = self._fake_fetch  # type: ignore
        a = sc.cargar_spec("http://x/swaggerGlobal", "k")
        b = sc.cargar_spec("http://x/swaggerGlobal", "k")
        self.assertIs(a, b)
        self.assertEqual(len(self._calls), 1)  # una sola llamada de red

    def test_force_recarga(self):
        sc._fetch_spec = self._fake_fetch  # type: ignore
        sc.cargar_spec("http://x/swaggerGlobal", "k")
        sc.cargar_spec("http://x/swaggerGlobal", "k", force=True)
        self.assertEqual(len(self._calls), 2)

    def test_error_de_red_es_swaggererror(self):
        def boom(url, key, timeout=60):
            raise OSError("sin red")
        sc._fetch_spec = boom  # type: ignore
        with self.assertRaises(sc.SwaggerError):
            sc.cargar_spec("http://x/swaggerGlobal", "k", force=True)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m unittest tests.test_swagger_catalog -v`
Expected: FAIL (`ModuleNotFoundError: finnegans.swagger_catalog`).

- [ ] **Step 3: Implementar el mínimo**

Crear `finnegans/swagger_catalog.py`:

```python
"""Catalogo de APIs de Finnegans basado en el spec OpenAPI completo (swaggerGlobal).

Fuente de verdad de endpoints: baja el spec (Swagger 2.0) una vez, lo cachea
en memoria, y ofrece busqueda y extraccion de operaciones. Solo libreria estandar.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class SwaggerError(Exception):
    """Error al cargar o interpretar el spec de swaggerGlobal."""


_SPEC_CACHE: dict[str, dict] = {}


def _fetch_spec(url: str, key: str, timeout: int = 60) -> dict:
    full = f"{url}?key={urllib.parse.quote(key)}"
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
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m unittest tests.test_swagger_catalog -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add finnegans/swagger_catalog.py tests/test_swagger_catalog.py
git commit -m "feat(swagger): cargar y cachear el spec swaggerGlobal en memoria"
```

---

### Task 3: swagger_catalog — búsqueda de endpoints

**Files:**
- Modify: `finnegans/swagger_catalog.py`
- Test: `tests/test_swagger_catalog.py`

**Interfaces:**
- Consumes: spec dict (de `cargar_spec`).
- Produces: `buscar_endpoints(spec: dict, consulta: str, limite: int = 8) -> list[dict]`, donde cada item es `{"path": str, "metodos": list[str], "tags": list[str], "resumen": str, "score": float}`, ordenado por `score` descendente y filtrando `score == 0`.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_swagger_catalog.py` una fixture compartida y la clase de test:

```python
SPEC = {
    "swagger": "2.0",
    "basePath": "/api",
    "definitions": {
        "ClienteBody": {
            "type": "object",
            "required": ["Codigo", "Nombre"],
            "properties": {
                "Codigo": {"type": "string"},
                "Nombre": {"type": "string"},
                "Limite": {"type": "number"},
            },
        }
    },
    "paths": {
        "/cliente/list": {"get": {"tags": ["cliente"], "summary": "Listar cliente",
            "operationId": "cliente_list",
            "parameters": [{"name": "ACCESS_TOKEN", "in": "query", "required": True}]}},
        "/cliente/{codigo}": {"get": {"tags": ["cliente"], "summary": "Obtener cliente por ID",
            "operationId": "cliente_get",
            "parameters": [{"name": "codigo", "in": "path", "required": True},
                           {"name": "ACCESS_TOKEN", "in": "query", "required": True}]}},
        "/cliente": {"post": {"tags": ["cliente"], "summary": "Crear cliente",
            "operationId": "cliente_post",
            "parameters": [{"name": "ACCESS_TOKEN", "in": "query", "required": True},
                           {"name": "body", "in": "body", "required": True,
                            "schema": {"$ref": "#/definitions/ClienteBody"}}]}},
        "/reports/analisisFacturaVenta": {"get": {"tags": ["reports", "VENTAS"],
            "summary": "Analisis de facturas de venta",
            "operationId": "reports_analisisFacturaVenta",
            "parameters": [{"name": "ACCESS_TOKEN", "in": "query", "required": True},
                           {"name": "FechaDesde", "in": "query", "required": False,
                            "description": "Filtrar por fecha desde"}]}},
    },
}


class TestBuscarEndpoints(unittest.TestCase):
    def test_encuentra_cliente_y_rankea(self):
        r = sc.buscar_endpoints(SPEC, "cliente")
        paths = [x["path"] for x in r]
        self.assertIn("/cliente/list", paths)
        self.assertIn("/cliente/{codigo}", paths)
        self.assertTrue(all(x["score"] > 0 for x in r))

    def test_encuentra_reporte_por_venta(self):
        r = sc.buscar_endpoints(SPEC, "factura de venta")
        self.assertIn("/reports/analisisFacturaVenta", [x["path"] for x in r])

    def test_sin_coincidencias_devuelve_vacio(self):
        self.assertEqual(sc.buscar_endpoints(SPEC, "zzz-inexistente"), [])
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m unittest tests.test_swagger_catalog -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'buscar_endpoints'`).

- [ ] **Step 3: Implementar el mínimo**

Agregar a `finnegans/swagger_catalog.py`:

```python
import re

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
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m unittest tests.test_swagger_catalog -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add finnegans/swagger_catalog.py tests/test_swagger_catalog.py
git commit -m "feat(swagger): busqueda de endpoints sobre el spec (ranking por tokens)"
```

---

### Task 4: swagger_catalog — operaciones, parámetros y schema de body

**Files:**
- Modify: `finnegans/swagger_catalog.py`
- Test: `tests/test_swagger_catalog.py`

**Interfaces:**
- Consumes: spec dict, fixture `SPEC` de Task 3.
- Produces:
  - `resolver_ref(spec: dict, schema: dict) -> dict` — resuelve un `{"$ref": "#/definitions/X"}` a `spec["definitions"]["X"]`; si no hay ref, devuelve el schema tal cual.
  - `ver_endpoint(spec: dict, recurso: str) -> list[dict]` — operaciones del recurso. `recurso` matchea por primer segmento del path (`"cliente"` → `/cliente`, `/cliente/list`, `/cliente/{codigo}`) o por path exacto (`"reports/analisisFacturaVenta"`). Cada item: `{"metodo": str, "path": str, "resumen": str, "parametros": list[dict], "tiene_body": bool, "body_campos": list[str], "body_requeridos": list[str]}`. `parametros` excluye `ACCESS_TOKEN` y el parámetro `body`; cada uno es `{"nombre","requerido","ubicacion","descripcion"}`.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_swagger_catalog.py`:

```python
class TestVerEndpoint(unittest.TestCase):
    def test_operaciones_de_cliente(self):
        ops = sc.ver_endpoint(SPEC, "cliente")
        pares = {(o["metodo"], o["path"]) for o in ops}
        self.assertIn(("GET", "/cliente/list"), pares)
        self.assertIn(("GET", "/cliente/{codigo}"), pares)
        self.assertIn(("POST", "/cliente"), pares)

    def test_params_excluyen_access_token_y_body(self):
        ops = sc.ver_endpoint(SPEC, "cliente")
        get_id = next(o for o in ops if o["path"] == "/cliente/{codigo}")
        nombres = [p["nombre"] for p in get_id["parametros"]]
        self.assertIn("codigo", nombres)
        self.assertNotIn("ACCESS_TOKEN", nombres)

    def test_body_schema_resuelto_por_ref(self):
        ops = sc.ver_endpoint(SPEC, "cliente")
        post = next(o for o in ops if o["metodo"] == "POST")
        self.assertTrue(post["tiene_body"])
        self.assertEqual(sorted(post["body_campos"]), ["Codigo", "Limite", "Nombre"])
        self.assertEqual(sorted(post["body_requeridos"]), ["Codigo", "Nombre"])

    def test_recurso_por_path_exacto_de_reporte(self):
        ops = sc.ver_endpoint(SPEC, "reports/analisisFacturaVenta")
        self.assertEqual(len(ops), 1)
        params = [p["nombre"] for p in ops[0]["parametros"]]
        self.assertIn("FechaDesde", params)
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m unittest tests.test_swagger_catalog -v`
Expected: FAIL (`ver_endpoint` no existe).

- [ ] **Step 3: Implementar el mínimo**

Agregar a `finnegans/swagger_catalog.py`:

```python
def resolver_ref(spec: dict, schema: dict) -> dict:
    if isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]  # ej. "#/definitions/ClienteBody"
        nombre = ref.split("/")[-1]
        return (spec.get("definitions") or {}).get(nombre, {})
    return schema or {}


def _primer_segmento(path: str) -> str:
    return path.strip("/").split("/")[0]


def ver_endpoint(spec: dict, recurso: str) -> list[dict]:
    objetivo = recurso.strip("/")
    ops: list[dict] = []
    for path, metodos in (spec.get("paths") or {}).items():
        if not isinstance(metodos, dict):
            continue
        coincide = path.strip("/") == objetivo or _primer_segmento(path) == objetivo
        if not coincide:
            continue
        for m, detail in metodos.items():
            if m.lower() not in _METODOS_HTTP or not isinstance(detail, dict):
                continue
            params, tiene_body, campos, requeridos = [], False, [], []
            for p in detail.get("parameters") or []:
                if not isinstance(p, dict):
                    continue
                if p.get("in") == "body":
                    tiene_body = True
                    body_schema = resolver_ref(spec, p.get("schema") or {})
                    campos = list((body_schema.get("properties") or {}).keys())
                    requeridos = list(body_schema.get("required") or [])
                elif p.get("name") != "ACCESS_TOKEN":
                    params.append({
                        "nombre": p.get("name"),
                        "requerido": bool(p.get("required", False)),
                        "ubicacion": p.get("in"),
                        "descripcion": p.get("description", ""),
                    })
            ops.append({
                "metodo": m.upper(),
                "path": path,
                "resumen": detail.get("summary", ""),
                "parametros": params,
                "tiene_body": tiene_body,
                "body_campos": campos,
                "body_requeridos": requeridos,
            })
    return ops
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m unittest tests.test_swagger_catalog -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add finnegans/swagger_catalog.py tests/test_swagger_catalog.py
git commit -m "feat(swagger): ver_endpoint con params y schema de body (resuelve \$ref)"
```

---

### Task 5: server.py — `buscar_api` y `ver_api` sobre swaggerGlobal

**Files:**
- Modify: `server.py:122-191` (tools `buscar_api` y `ver_api`)
- Test: `tests/test_server_discovery_swagger.py`

**Interfaces:**
- Consumes: `swagger_catalog.cargar_spec`, `buscar_endpoints`, `ver_endpoint`; `Settings.swagger_url/swagger_key/require_swagger_config`.
- Produces: `buscar_api(consulta: str) -> str` y `ver_api(api_id: str) -> str` resolviendo contra swaggerGlobal. Formato de texto para el agente (paths reales, métodos, params).

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_server_discovery_swagger.py`:

```python
import unittest
import server
from finnegans import swagger_catalog as sc
from tests.test_swagger_catalog import SPEC


class TestServerDiscovery(unittest.TestCase):
    def setUp(self):
        sc._SPEC_CACHE.clear()
        sc._fetch_spec = lambda url, key, timeout=60: SPEC  # type: ignore
        # asegurar que require_swagger_config no falle
        server.get_settings().swagger_key = "k"

    def test_buscar_api_lista_paths_reales(self):
        out = server.buscar_api("cliente")
        self.assertIn("/cliente/list", out)
        self.assertIn("/cliente/{codigo}", out)

    def test_ver_api_muestra_operaciones_y_params(self):
        out = server.ver_api("cliente")
        self.assertIn("/cliente/list", out)
        self.assertIn("POST", out)
        self.assertIn("codigo", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m unittest tests.test_server_discovery_swagger -v`
Expected: FAIL (`buscar_api` sigue usando el MCP / no encuentra los paths de la fixture).

- [ ] **Step 3: Implementar el mínimo**

En `server.py`, agregar el import arriba:

```python
from finnegans import swagger_catalog
```

Reemplazar el cuerpo de `buscar_api` por (sync; ya no async):

```python
@mcp.tool()
def buscar_api(consulta: str) -> str:
    """Busca APIs de Finnegans por nombre, id o descripcion (usa la doc OpenAPI oficial).

    Usar PRIMERO cuando el usuario pide algo y no sabes que endpoint usar.
    """
    s = get_settings()
    try:
        s.require_swagger_config()
        spec = swagger_catalog.cargar_spec(s.swagger_url, s.swagger_key)
    except (RuntimeError, swagger_catalog.SwaggerError) as e:
        return f"No pude acceder a la documentacion de APIs: {e}"
    resultados = swagger_catalog.buscar_endpoints(spec, consulta)
    if not resultados:
        return f"No se encontraron endpoints para '{consulta}'."
    lineas = [f"Encontrados {len(resultados)} endpoints para '{consulta}':"]
    for r in resultados:
        lineas.append(f"- {r['path']}  ({', '.join(r['metodos'])})  {r['resumen']}")
    lineas.append("\nUsa ver_api con el 'path' o el nombre del recurso (ej. 'cliente').")
    return "\n".join(lineas)
```

Reemplazar el cuerpo de `ver_api` por:

```python
@mcp.tool()
def ver_api(api_id: str) -> str:
    """Muestra las operaciones reales de un recurso: metodos, paths y parametros.

    api_id puede ser un recurso ('cliente') o un path exacto ('reports/analisisFacturaVenta').
    """
    s = get_settings()
    try:
        s.require_swagger_config()
        spec = swagger_catalog.cargar_spec(s.swagger_url, s.swagger_key)
    except (RuntimeError, swagger_catalog.SwaggerError) as e:
        return f"No pude acceder a la documentacion de APIs: {e}"
    ops = swagger_catalog.ver_endpoint(spec, api_id)
    if not ops:
        return (f"No encontre operaciones para '{api_id}'. "
                "Proba buscar_api para ver el nombre exacto del recurso.")
    lineas = [f"Operaciones de '{api_id}':\n"]
    for o in ops:
        lineas.append(f"  {o['metodo']} /api{o['path']} — {o['resumen']}")
        if o["parametros"]:
            ps = ", ".join(f"{p['nombre']}{'*' if p['requerido'] else ''} ({p['ubicacion']})"
                           for p in o["parametros"])
            lineas.append(f"    Parametros: {ps}")
        if o["tiene_body"]:
            req = ", ".join(o["body_requeridos"]) or "(sin requeridos)"
            lineas.append(f"    Body: campos {o['body_campos']} | requeridos: {req}")
    lineas.append("\nPara leer: consultar_finnegans. Para escribir: preparar_cambio.")
    return "\n".join(lineas)
```

Nota: quitar `async` de estas dos tools. No borrar `finnegans/discovery.py` ni sus imports usados por otras tools todavía (se limpia en Task 7).

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m unittest tests.test_server_discovery_swagger -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server_discovery_swagger.py
git commit -m "feat(server): buscar_api/ver_api resuelven contra swaggerGlobal"
```

---

### Task 6: `consultar_finnegans` — sub-paths (`/list`, `/reports/…`) y error claro

**Files:**
- Modify: `server.py:194-219` (tool `consultar_finnegans`)
- Test: `tests/test_server_consultar_subpath.py`

**Interfaces:**
- Consumes: `FinnegansClient.request` (existente, ya soporta `api_id` con `/`).
- Produces: `consultar_finnegans(api_id, metodo="GET", id=None, parametros=None) -> str` que acepta `api_id` con sub-path (`"cliente/list"`, `"reports/analisisFacturaVenta"`) y traduce el error `id missing` a un mensaje accionable.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_server_consultar_subpath.py` (usa un stub HTTP local, sin ERP real):

```python
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import server
from finnegans.client import FinnegansClient


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencio
        pass

    def do_GET(self):
        if self.path.startswith("/api/cliente/list"):
            body = json.dumps([{"codigo": "P01093", "nombre": "FORMAS PUBLICITARIAS S.A."}])
            self.send_response(200)
        elif self.path.startswith("/api/cliente?") or self.path == "/api/cliente":
            body = json.dumps({"error": "Bad Request: id missing", "status": 400})
            self.send_response(400)
        else:
            body = json.dumps({"error": "Not Found", "status": 404})
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())


class TestConsultarSubpath(unittest.TestCase):
    def setUp(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        # cliente apuntando al stub, con token fijo
        client = FinnegansClient.__new__(FinnegansClient)
        client.settings = type("S", (), {"base_url": f"http://127.0.0.1:{self.port}"})()
        client.timeout = 5
        client._token = "T"
        client._token_ts = 9e18
        client.token_ttl_seconds = 3600
        server._client = client

    def tearDown(self):
        self.httpd.shutdown()
        server._client = None

    def test_list_subpath_trae_datos(self):
        out = server.consultar_finnegans("cliente/list")
        self.assertIn("P01093", out)

    def test_id_missing_da_mensaje_accionable(self):
        out = server.consultar_finnegans("cliente")
        self.assertIn("/list", out)  # sugiere usar la operacion de listado
        self.assertNotIn("id missing", out.lower())
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m unittest tests.test_server_consultar_subpath -v`
Expected: FAIL (el segundo test: hoy devuelve el `id missing` crudo).

- [ ] **Step 3: Implementar el mínimo**

En `server.py`, reemplazar el `except` de `consultar_finnegans` para traducir el error:

```python
    try:
        data = get_client().request(metodo, api_id, id=id, params=parametros)
        return _truncate(data)
    except FinnegansError as e:
        msg = str(e)
        if "id missing" in msg.lower():
            return (
                f"El endpoint '{api_id}' requiere un codigo en el path "
                f"(ej. '{api_id}/CODIGO'), o usa la operacion de listado "
                f"'{api_id}/list'. Detalle tecnico: {msg}"
            )
        return f"Error en consulta: {msg}"
```

Actualizar el docstring de la tool para documentar que `api_id` acepta sub-paths:

```python
    """Consulta de LECTURA a Finnegans (solo GET).

    api_id puede ser:
      - un recurso con codigo:  api_id='cliente', id='P01093'  -> /api/cliente/P01093
      - un listado:             api_id='cliente/list'          -> /api/cliente/list
      - un reporte:             api_id='reports/analisisFacturaVenta'
    parametros: filtros adicionales como query params (ej. FechaDesde).
    """
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m unittest tests.test_server_consultar_subpath -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server_consultar_subpath.py
git commit -m "feat(server): consultar_finnegans soporta /list y /reports y traduce 'id missing'"
```

---

### Task 7: `preparar_cambio` — schema de escritura desde swaggerGlobal

**Files:**
- Modify: `server.py:222-285` (tool `preparar_cambio`)
- Test: `tests/test_server_preparar.py` (existente; agregar caso)

**Interfaces:**
- Consumes: `swagger_catalog.cargar_spec`, `swagger_catalog.ver_endpoint`.
- Produces: `preparar_cambio` toma `campos_body`/`body_schema` de swaggerGlobal (operación con método == `metodo` para el recurso `api_id`) en vez del MCP `get_api`.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_server_preparar.py` (adaptar imports existentes del archivo):

```python
    def test_preview_usa_campos_de_swaggerglobal(self):
        import server
        from finnegans import swagger_catalog as sc
        from tests.test_swagger_catalog import SPEC
        sc._SPEC_CACHE.clear()
        sc._fetch_spec = lambda url, key, timeout=60: SPEC  # type: ignore
        server.get_settings().swagger_key = "k"
        out = server.preparar_cambio(
            api_id="cliente", metodo="POST",
            datos={"Codigo": "X", "Nombre": "Y"}, descripcion="alta test",
        )
        # el preview referencia los campos documentados del body
        self.assertIn("Codigo", out)
        self.assertIn("Nombre", out)
```

Nota: `preparar_cambio` es `async`; si el test corre sync, envolvé con `asyncio.run(...)`. Si en Task 7 se pasa a sync (recomendado, ya no usa await), llamalo directo.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m unittest tests.test_server_preparar -v`
Expected: FAIL (hoy usa `get_api` del MCP; con la fixture de swaggerGlobal no obtiene el schema).

- [ ] **Step 3: Implementar el mínimo**

En `server.py`, dentro de `preparar_cambio`, reemplazar el bloque que trae el schema por MCP:

```python
    # Traer schema del endpoint desde swaggerGlobal (degradar con aviso si falla)
    campos_body: list[str] = []
    body_schema = None
    try:
        s = get_settings()
        s.require_swagger_config()
        spec = swagger_catalog.cargar_spec(s.swagger_url, s.swagger_key)
        ops = swagger_catalog.ver_endpoint(spec, api_id)
        match = next((o for o in ops if o["metodo"] == metodo), None)
        if match and match["tiene_body"]:
            campos_body = match["body_campos"]
            body_schema = {"properties": {c: {} for c in match["body_campos"]},
                           "required": match["body_requeridos"]}
    except (RuntimeError, swagger_catalog.SwaggerError):
        body_schema = None  # validar_body avisara "sin schema"
```

Quitar `async` de `preparar_cambio` si ya no hay `await` (revisar; `get_api` era el único await). Si queda algún `await`, dejarla async y ajustar el test con `asyncio.run`.

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m unittest tests.test_server_preparar -v`
Expected: PASS (incluidos los casos previos del archivo).

- [ ] **Step 5: Verificar que no rompió el resto**

Run: `python -m unittest discover -s tests -v`
Expected: todos PASS.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server_preparar.py
git commit -m "feat(server): preparar_cambio toma el schema de body de swaggerGlobal"
```

---

### Task 8: `ASSISTANT_INSTRUCTIONS.md` — diccionario de negocio y hábito de preguntar

**Files:**
- Modify: `ASSISTANT_INSTRUCTIONS.md`

**Interfaces:** N/A (documento de texto, sin tests).

- [ ] **Step 1: Agregar la sección de diccionario de negocio**

Insertar antes de "## Ejemplos por area":

```markdown
## Diccionario de negocio (SOUTEX / Formas)

Operamos por **SUCURSAL**. Códigos reales (de `sucursal/list`):

| Código | Sucursal | Uso |
|---|---|---|
| `EMPRE01` | Formas Publicitarias SA | Productiva |
| `4` | Soutex SA | Productiva |
| `7` | FP DEMO | Interna / gestión alternativa |
| `6` | ST Demo | Interna / gestión alternativa |
| `5` | Prueba | Interna |

Las dos compañías reales son **Formas Publicitarias SA** y **Soutex SA**
(cada una con su variante DEMO para asuntos internos).

**Unidades de negocio de Formas Publicitarias SA** (sub-dimensión): "Formas Shop",
"Corporate", "No Estrés". _Qué buscar / cómo filtrar cada una: a completar._

### Mapeos lenguaje natural → API (se completa con el uso)
- "buscar un cliente por nombre" → `cliente/list` y filtrar el resultado por nombre
  (el ERP no busca por nombre; se lista y se filtra).
- "ventas / facturación de un período" → endpoint o reporte de ventas correcto
  (confirmar el primero al enseñar el caso real) con su rango de fechas.

### Convención de rutas Finnegans (importante)
- Un registro por código: `GET /api/{entidad}/{codigo}`.
- Listado: `GET /api/{entidad}/list`.
- Reportes: `GET /api/reports/{Nombre}`.
- `id missing` = falta el segmento del path; usá `/list` o el código.
```

- [ ] **Step 2: Agregar la regla de "pedir los detalles"**

En "## Como trabajas", agregar como punto 1 (y renumerar):

```markdown
1. Si el pedido necesita **sucursal**, **unidad de negocio** o **rango de fechas**
   y el usuario no los especificó, PREGUNTÁ antes de consultar y ofrecé las
   opciones de la tabla de sucursales. No asumas una sucursal por defecto.
```

- [ ] **Step 3: Commit**

```bash
git add ASSISTANT_INSTRUCTIONS.md
git commit -m "docs(assistant): diccionario de negocio (sucursales) y habito de pedir detalles"
```

---

### Task 9: README + limpieza de documentación

**Files:**
- Modify: `README.md` (secciones de troubleshooting `id missing` y estructura del proyecto)

**Interfaces:** N/A.

- [ ] **Step 1: Corregir la sección `Bad Request: id missing`**

Reemplazar el bloque actual (líneas ~644-647) por:

```markdown
### `Bad Request: id missing` al consultar

- El router de Finnegans exige un segmento tras la entidad. Rutas válidas:
  - `GET /api/{entidad}/{codigo}` → un registro.
  - `GET /api/{entidad}/list` → listado completo.
  - `GET /api/reports/{Nombre}` → reportes.
- Si querés listar, usá `api_id='{entidad}/list'`. Si querés un registro, pasá `id`.
```

- [ ] **Step 2: Documentar la fuente de verdad**

Agregar a la sección "## Herramientas MCP expuestas" (o una nota nueva):

```markdown
> **Fuente de verdad de APIs:** el conector resuelve endpoints contra el spec
> OpenAPI completo de Finnegans (`FINNEGANS_SWAGGER_URL` + `FINNEGANS_SWAGGER_KEY`,
> el Swagger de oneteam). El MCP `finnegans-api-docs` queda como apoyo secundario.
```

- [ ] **Step 3: Nota de seguridad (rotación de credencial)**

Agregar a la sección "## Seguridad":

```markdown
- Si el `client_secret` o el `FINNEGANS_SWAGGER_KEY` se exponen (chat, mail),
  rotarlos en Finnegans y actualizar el `.env`.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(readme): convencion /list y /reports, fuente de verdad y rotacion de credenciales"
```

---

## Tarea manual del dueño (fuera del código)

- **Rotar `FINNEGANS_CLIENT_SECRET`** en Finnegans (Usuarios → Keys API) y actualizar
  el `.env`, por haber quedado expuesto en el chat. No es un paso automatizable.

## Self-Review (cobertura del spec)

- Parte 1 (descubrimiento sobre swaggerGlobal): Tasks 1–7. ✓
- Parte 2 (diccionario de negocio texto): Task 8. ✓
- Parte 3 (pedir detalles): Task 8 Step 2. ✓
- Seguridad (key en .env / rotación): Task 1, Task 9, tarea manual. ✓
- Testing (unit sin red, resolución de paths, degradación): Tasks 2–7. ✓
- MCP como secundario (no borrarlo, dejar de ser verdad de paths): Tasks 5 y 7 (nota de no borrar `discovery.py`). ✓
