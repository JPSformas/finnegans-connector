# Conector Finnegans Nivel 3 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolucionar el PoC `finnegans-connector` para que ~20 usuarios no técnicos consulten y modifiquen el ERP Finnegans vía Claude Desktop, con confirmación de escritura de Nivel 3 (vista previa verificada + lista negra + código de confirmación + read-back) y auditoría por operador.

**Architecture:** Se conserva la estructura del PoC (`config`/`client`/`discovery`/`validator`/`server`) y las 6 tools MCP. Se endurece únicamente el camino de escritura y se agrega auditoría e instalador. El descubrimiento ya está `async` en disco; su "arreglo" es reiniciar el proceso MCP y verificar.

**Tech Stack:** Python 3.10+, SDK `mcp>=1.2.0` (solo `server.py`), resto stdlib. Tests con `unittest` (stdlib), corridos con `python -m unittest`.

## Global Constraints

- Python 3.10+ (usar `from __future__ import annotations` en cada módulo nuevo).
- El paquete `finnegans/` NO agrega dependencias externas (solo stdlib). El SDK `mcp` se usa solo en `server.py`.
- Todo docstring/comentario/salida al usuario en **castellano**.
- NUNCA loguear ni exponer `client_secret`, `client_id` completo ni el token de acceso. El parámetro `ACCESS_TOKEN` debe removerse antes de cualquier log.
- Empresa: SOUTEX. Áreas: Administración, Ventas, Marketing, Producción, Compras.
- Tests se ejecutan desde la raíz del proyecto (`C:\Users\user\finnegans-connector`).

---

### Task 1: Verificar y desbloquear el descubrimiento (fix de runtime)

El código `async` de `discovery.py`/`server.py` ya está en disco; el proceso MCP corría una versión vieja. Esta tarea confirma que la versión de disco funciona de punta a punta y deja un test de regresión de que las tools del server NO usan `asyncio.run`.

**Files:**
- Test: `tests/test_no_asyncio_run_in_tools.py`
- Modify (si el test falla): `finnegans/discovery.py`, `server.py`

**Interfaces:**
- Consumes: `finnegans.discovery.search_apis` (async), `finnegans.discovery.get_api` (async).
- Produces: garantía de que `server.py` y `discovery.py` no invocan `asyncio.run` (el que queda en `verify_setup.py` es correcto y queda excluido).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_no_asyncio_run_in_tools.py
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestNoAsyncioRunInTools(unittest.TestCase):
    def test_server_and_discovery_no_asyncio_run(self):
        for rel in ("server.py", "finnegans/discovery.py"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn(
                "asyncio.run", src,
                f"{rel} no debe llamar asyncio.run (rompe dentro del event loop del MCP)",
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify current state**

Run: `python -m unittest tests.test_no_asyncio_run_in_tools -v`
Expected: PASS (el código en disco ya está limpio). Si FALLA, quitar el `asyncio.run` del archivo señalado reemplazándolo por `await` en la tool async correspondiente, y volver a correr.

- [ ] **Step 3: Verificación funcional manual (una sola vez)**

Con `.env` configurado, correr:
Run: `python verify_setup.py`
Expected: los checks 4 (API), 5 (Catálogo de APIs) y 6 (server MCP) en `[OK]`. El check 5 confirma que `search_apis` devuelve resultados reales.

- [ ] **Step 4: Reinicio del proceso MCP**

Documentar en el commit: tras cualquier cambio de código, Claude Desktop debe reiniciarse para recargar el server MCP (el proceso es de larga vida y no toma cambios en caliente).

- [ ] **Step 5: Commit**

```bash
git add tests/test_no_asyncio_run_in_tools.py
git commit -m "test: regresion de descubrimiento (sin asyncio.run en tools MCP)"
```

---

### Task 2: Extender configuración (operador, auditoría, política de riesgo)

**Files:**
- Modify: `finnegans/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.operator: str`, `Settings.audit_log_path: str`, `Settings.allow_delete: bool`, `Settings.high_risk_patterns: list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import unittest
from finnegans.config import Settings


class TestSettingsNuevo(unittest.TestCase):
    def _settings(self, env):
        import os
        for k in ("FINNEGANS_OPERATOR", "FINNEGANS_AUDIT_LOG",
                  "FINNEGANS_ALLOW_DELETE", "FINNEGANS_HIGH_RISK_PATTERNS",
                  "FINNEGANS_CLIENT_ID", "FINNEGANS_CLIENT_SECRET"):
            os.environ.pop(k, None)
        os.environ.update(env)
        return Settings(load_env=False)

    def test_operator_y_defaults(self):
        s = self._settings({"FINNEGANS_OPERATOR": "Juan <j@x.com>"})
        self.assertEqual(s.operator, "Juan <j@x.com>")
        self.assertFalse(s.allow_delete)
        self.assertEqual(s.high_risk_patterns, [])
        self.assertTrue(s.audit_log_path)  # tiene default

    def test_allow_delete_truthy(self):
        s = self._settings({"FINNEGANS_ALLOW_DELETE": "true"})
        self.assertTrue(s.allow_delete)

    def test_high_risk_patterns_split(self):
        s = self._settings({"FINNEGANS_HIGH_RISK_PATTERNS": "asiento, factura ,cierre"})
        self.assertEqual(s.high_risk_patterns, ["asiento", "factura", "cierre"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_config -v`
Expected: FAIL con `AttributeError: 'Settings' object has no attribute 'operator'`.

- [ ] **Step 3: Write minimal implementation**

En `finnegans/config.py`, dentro de `Settings.__init__`, después de la línea `self.workspace = ...`, agregar:

```python
        from pathlib import Path as _Path

        self.operator = os.environ.get("FINNEGANS_OPERATOR", "")
        default_audit = _Path(__file__).resolve().parent.parent / "audit" / "finnegans-audit.jsonl"
        self.audit_log_path = os.environ.get("FINNEGANS_AUDIT_LOG", str(default_audit))
        self.allow_delete = os.environ.get("FINNEGANS_ALLOW_DELETE", "").strip().lower() in (
            "1", "true", "si", "sí", "yes",
        )
        raw_patterns = os.environ.get("FINNEGANS_HIGH_RISK_PATTERNS", "")
        self.high_risk_patterns = [p.strip() for p in raw_patterns.split(",") if p.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_config -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Actualizar `.env.example`**

Agregar al final de `.env.example`:

```bash

# --- Identidad y auditoria (opcion B: credencial compartida) ---
# Nombre/email del usuario de ESTA instalacion. Es lo unico distinto entre las 20 PCs.
FINNEGANS_OPERATOR=Nombre Apellido <email@empresa.com>
# Ruta del log de auditoria (por defecto: ./audit/finnegans-audit.jsonl)
FINNEGANS_AUDIT_LOG=
# Permitir DELETE (por defecto NO). Poner "true" solo si un area lo necesita.
FINNEGANS_ALLOW_DELETE=false
# Patrones de endpoint de alto riesgo (coma-separados), ej: asiento,factura,cierre
FINNEGANS_HIGH_RISK_PATTERNS=
```

- [ ] **Step 6: Commit**

```bash
git add finnegans/config.py .env.example tests/test_config.py
git commit -m "feat(config): operador, auditoria y politica de riesgo de escritura"
```

---

### Task 3: Log de auditoría append-only (`audit.py`)

**Files:**
- Create: `finnegans/audit.py`
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: nada de otras tareas.
- Produces:
  - `class AuditLog` con `__init__(self, path: str, operator: str)` y
    `record(self, evento: str, *, metodo: str = "", api_id: str = "", resource_id: str | None = None, parametros: dict | None = None, body: object = None, confirmacion_id: str = "", codigo_ok: bool | None = None, resultado: str = "", detalle: object = None) -> None`
  - Escribe una línea JSON por evento; nunca guarda `ACCESS_TOKEN`/secretos.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audit.py
import json
import tempfile
import unittest
from pathlib import Path
from finnegans.audit import AuditLog


class TestAuditLog(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = str(Path(self.dir.name) / "sub" / "audit.jsonl")

    def tearDown(self):
        self.dir.cleanup()

    def test_crea_directorio_y_escribe_linea(self):
        log = AuditLog(self.path, "Juan <j@x.com>")
        log.record("preparado", metodo="POST", api_id="cliente")
        lines = Path(self.path).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["evento"], "preparado")
        self.assertEqual(rec["operador"], "Juan <j@x.com>")
        self.assertEqual(rec["metodo"], "POST")
        self.assertIn("timestamp", rec)

    def test_append_no_sobreescribe(self):
        log = AuditLog(self.path, "op")
        log.record("preparado", api_id="a")
        log.record("ejecutado", api_id="a", resultado="OK")
        lines = Path(self.path).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)

    def test_nunca_loguea_access_token(self):
        log = AuditLog(self.path, "op")
        log.record("preparado", api_id="cliente",
                   parametros={"ACCESS_TOKEN": "SECRETO123", "Estado": "activo"})
        content = Path(self.path).read_text(encoding="utf-8")
        self.assertNotIn("SECRETO123", content)
        self.assertIn("Estado", content)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_audit -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'finnegans.audit'`.

- [ ] **Step 3: Write minimal implementation**

```python
# finnegans/audit.py
"""Log de auditoria append-only (JSONL) para el conector Finnegans.

Registra cada preparacion/ejecucion/rechazo con identidad de operador.
Nunca escribe tokens ni secretos.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

_SENSIBLE = ("access_token", "token", "secret", "password", "client_secret")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if any(s in str(k).lower() for s in _SENSIBLE):
                out[k] = "***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class AuditLog:
    """Escribe eventos de auditoria, uno por linea (JSONL)."""

    def __init__(self, path: str, operator: str) -> None:
        self.path = Path(path)
        self.operator = operator or "(sin operador)"

    def record(
        self,
        evento: str,
        *,
        metodo: str = "",
        api_id: str = "",
        resource_id: str | None = None,
        parametros: dict | None = None,
        body: Any = None,
        confirmacion_id: str = "",
        codigo_ok: bool | None = None,
        resultado: str = "",
        detalle: Any = None,
    ) -> None:
        rec = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "operador": self.operator,
            "evento": evento,
            "metodo": metodo,
            "api_id": api_id,
            "resource_id": resource_id,
            "parametros": _redact(parametros or {}),
            "body": _redact(body),
            "confirmacion_id": confirmacion_id,
            "codigo_ok": codigo_ok,
            "resultado": resultado,
            "detalle": _redact(detalle),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_audit -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add finnegans/audit.py tests/test_audit.py
git commit -m "feat(audit): log append-only JSONL con redaccion de secretos"
```

---

### Task 4: Extraer el schema de escritura desde discovery

`preparar_cambio` necesita los parámetros y el `requestBodySchema` del endpoint para construir la vista previa verificada. Se agrega una función y un caché.

**Files:**
- Modify: `finnegans/discovery.py`
- Test: `tests/test_discovery_schema.py`

**Interfaces:**
- Consumes: `get_api(api_id)` (async), `list_methods(spec)`.
- Produces:
  - `extraer_schema_escritura(spec: dict, metodo: str) -> dict` (pura, sin red) que devuelve
    `{"parametros": list[dict], "body_schema": dict | None, "campos_body": list[str], "requeridos": list[str]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_schema.py
import unittest
from finnegans.discovery import extraer_schema_escritura

SPEC = {
    "request_structure": {
        "paths": {
            "/api/cliente": {
                "post": {
                    "summary": "Crear cliente",
                    "parameters": [{"name": "ACCESS_TOKEN"}, {"name": "sucursal", "required": True}],
                    "requestBodySchema": {
                        "required": ["Codigo", "Nombre"],
                        "properties": {
                            "Codigo": {"type": "string"},
                            "Nombre": {"type": "string"},
                            "Limite": {"type": "number"},
                        },
                    },
                }
            }
        }
    }
}


class TestExtraerSchema(unittest.TestCase):
    def test_post_devuelve_campos_y_requeridos(self):
        r = extraer_schema_escritura(SPEC, "POST")
        self.assertEqual(sorted(r["campos_body"]), ["Codigo", "Limite", "Nombre"])
        self.assertEqual(sorted(r["requeridos"]), ["Codigo", "Nombre"])
        nombres_param = [p["nombre"] for p in r["parametros"]]
        self.assertIn("sucursal", nombres_param)
        self.assertNotIn("ACCESS_TOKEN", nombres_param)

    def test_metodo_inexistente_devuelve_vacio(self):
        r = extraer_schema_escritura(SPEC, "DELETE")
        self.assertIsNone(r["body_schema"])
        self.assertEqual(r["campos_body"], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_discovery_schema -v`
Expected: FAIL con `ImportError: cannot import name 'extraer_schema_escritura'`.

- [ ] **Step 3: Write minimal implementation**

En `finnegans/discovery.py`, agregar al final:

```python
def extraer_schema_escritura(api_spec: dict[str, Any], metodo: str) -> dict[str, Any]:
    """Devuelve parametros, body_schema y campos del body para un metodo dado.

    Funcion pura (no consulta la red): opera sobre un spec ya obtenido.
    """
    metodo = metodo.upper()
    vacio = {"parametros": [], "body_schema": None, "campos_body": [], "requeridos": []}
    structure = api_spec.get("request_structure") or api_spec.get("api") or {}
    paths = structure.get("paths") or {}

    for _path, ops in paths.items():
        if not isinstance(ops, dict):
            continue
        for http_method, detail in ops.items():
            if http_method.upper() != metodo or not isinstance(detail, dict):
                continue
            params = [
                {
                    "nombre": p.get("name"),
                    "requerido": p.get("required", False),
                    "ubicacion": p.get("in"),
                    "descripcion": p.get("description", ""),
                }
                for p in (detail.get("parameters") or [])
                if isinstance(p, dict) and p.get("name") != "ACCESS_TOKEN"
            ]
            body_schema = detail.get("requestBodySchema")
            campos = list((body_schema or {}).get("properties", {}).keys())
            requeridos = list((body_schema or {}).get("required", []))
            return {
                "parametros": params,
                "body_schema": body_schema,
                "campos_body": campos,
                "requeridos": requeridos,
            }
    return vacio
```

Y agregar caché a `get_api` (envolver la llamada). Reemplazar la función `get_api` por:

```python
_api_cache: dict[str, Any] = {}


async def get_api(api_id: str) -> dict[str, Any]:
    """Obtiene la especificacion OpenAPI de una API (con cache en memoria)."""
    if api_id in _api_cache:
        return _api_cache[api_id]
    result = await _call_docs_tool("get_api", {"api": api_id})
    if isinstance(result, dict) and result.get("status") not in ("not_found", "ambiguous"):
        _api_cache[api_id] = result
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_discovery_schema -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add finnegans/discovery.py tests/test_discovery_schema.py
git commit -m "feat(discovery): extraer schema de escritura + cache de get_api"
```

---

### Task 5: Validación de body contra schema

**Files:**
- Modify: `finnegans/validator.py`
- Test: `tests/test_validator_body.py`

**Interfaces:**
- Produces: `validar_body(body: dict | None, body_schema: dict | None) -> list[str]`
  - Devuelve lista de problemas en castellano. Lista vacía = sin objeciones.
  - Si `body_schema` es None → devuelve `["(sin schema: no se pudo verificar contra la documentacion)"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validator_body.py
import unittest
from finnegans.validator import validar_body

SCHEMA = {
    "required": ["Codigo", "Nombre"],
    "properties": {
        "Codigo": {"type": "string"},
        "Nombre": {"type": "string"},
        "Limite": {"type": "number"},
    },
}


class TestValidarBody(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(validar_body({"Codigo": "A", "Nombre": "X"}, SCHEMA), [])

    def test_falta_requerido(self):
        problemas = validar_body({"Codigo": "A"}, SCHEMA)
        self.assertTrue(any("Nombre" in p and "falta" in p.lower() for p in problemas))

    def test_campo_desconocido(self):
        problemas = validar_body({"Codigo": "A", "Nombre": "X", "Inventado": 1}, SCHEMA)
        self.assertTrue(any("Inventado" in p for p in problemas))

    def test_tipo_incorrecto(self):
        problemas = validar_body({"Codigo": "A", "Nombre": "X", "Limite": "cero"}, SCHEMA)
        self.assertTrue(any("Limite" in p for p in problemas))

    def test_sin_schema(self):
        problemas = validar_body({"x": 1}, None)
        self.assertEqual(len(problemas), 1)
        self.assertIn("sin schema", problemas[0].lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_validator_body -v`
Expected: FAIL con `ImportError: cannot import name 'validar_body'`.

- [ ] **Step 3: Write minimal implementation**

En `finnegans/validator.py`, agregar:

```python
_TIPOS_PY = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validar_body(body: dict | None, body_schema: dict | None) -> list[str]:
    """Valida el body propuesto contra el requestBodySchema del endpoint."""
    if body_schema is None:
        return ["(sin schema: no se pudo verificar contra la documentacion)"]
    body = body or {}
    props = body_schema.get("properties", {}) or {}
    requeridos = body_schema.get("required", []) or []
    problemas: list[str] = []

    for req in requeridos:
        if req not in body:
            problemas.append(f"Falta el campo requerido '{req}'.")

    for campo, valor in body.items():
        if campo not in props:
            problemas.append(f"Campo desconocido '{campo}' (no existe en la documentacion).")
            continue
        tipo = props[campo].get("type")
        py = _TIPOS_PY.get(tipo)
        if py and valor is not None and not isinstance(valor, py):
            # bool es subclase de int; evitar falso positivo con number/integer
            if not (tipo in ("integer", "number") and isinstance(valor, bool) is False and isinstance(valor, (int, float))):
                problemas.append(
                    f"Campo '{campo}': se esperaba {tipo}, se recibio {type(valor).__name__}."
                )
    return problemas
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_validator_body -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add finnegans/validator.py tests/test_validator_body.py
git commit -m "feat(validator): validacion de body contra requestBodySchema"
```

---

### Task 6: Evaluación de riesgo (lista negra / operaciones masivas)

**Files:**
- Modify: `finnegans/validator.py`
- Test: `tests/test_validator_riesgo.py`

**Interfaces:**
- Produces: `evaluar_riesgo(metodo: str, resource_id: str | None, api_id: str, allow_delete: bool, high_risk_patterns: list[str]) -> tuple[bool, bool, str]`
  - Retorna `(bloqueado, alto_riesgo, motivo)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validator_riesgo.py
import unittest
from finnegans.validator import evaluar_riesgo


class TestEvaluarRiesgo(unittest.TestCase):
    def test_delete_bloqueado_por_defecto(self):
        bloq, alto, motivo = evaluar_riesgo("DELETE", "123", "cliente", False, [])
        self.assertTrue(bloq)
        self.assertIn("DELETE", motivo)

    def test_delete_permitido_si_allow(self):
        bloq, alto, _ = evaluar_riesgo("DELETE", "123", "cliente", True, [])
        self.assertFalse(bloq)
        self.assertTrue(alto)  # borrar sigue siendo alto riesgo

    def test_put_sin_id_es_alto_riesgo(self):
        bloq, alto, motivo = evaluar_riesgo("PUT", None, "cliente", False, [])
        self.assertFalse(bloq)
        self.assertTrue(alto)
        self.assertIn("sin id", motivo.lower())

    def test_patron_alto_riesgo(self):
        bloq, alto, motivo = evaluar_riesgo("POST", None, "asientoContable", False, ["asiento"])
        self.assertTrue(alto)
        self.assertIn("asiento", motivo.lower())

    def test_post_normal_bajo_riesgo(self):
        bloq, alto, _ = evaluar_riesgo("POST", None, "cliente", False, [])
        self.assertFalse(bloq)
        self.assertFalse(alto)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_validator_riesgo -v`
Expected: FAIL con `ImportError: cannot import name 'evaluar_riesgo'`.

- [ ] **Step 3: Write minimal implementation**

En `finnegans/validator.py`, agregar:

```python
def evaluar_riesgo(
    metodo: str,
    resource_id: str | None,
    api_id: str,
    allow_delete: bool,
    high_risk_patterns: list[str],
) -> tuple[bool, bool, str]:
    """Determina si una escritura esta bloqueada o es de alto riesgo.

    Retorna (bloqueado, alto_riesgo, motivo).
    """
    metodo = metodo.upper()
    motivos: list[str] = []
    alto = False

    if metodo == "DELETE":
        if not allow_delete:
            return (True, True, "Operacion DELETE bloqueada por politica (FINNEGANS_ALLOW_DELETE=false).")
        alto = True
        motivos.append("es un DELETE (borrado)")

    if metodo in ("PUT", "DELETE") and not resource_id:
        alto = True
        motivos.append("sin id: puede afectar multiples registros")

    api_lower = (api_id or "").lower()
    for pat in high_risk_patterns:
        if pat.lower() in api_lower:
            alto = True
            motivos.append(f"endpoint sensible (coincide con '{pat}')")
            break

    motivo = "; ".join(motivos) if motivos else "operacion estandar"
    return (False, alto, motivo)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_validator_riesgo -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add finnegans/validator.py tests/test_validator_riesgo.py
git commit -m "feat(validator): evaluacion de riesgo (DELETE bloqueado, masivos, patrones)"
```

---

### Task 7: Vista previa estructurada + código de confirmación en `ChangeStore`

**Files:**
- Modify: `finnegans/validator.py`
- Test: `tests/test_validator_store.py`

**Interfaces:**
- Consumes: `validar_body`, `evaluar_riesgo`.
- Produces:
  - `construir_preview(api_id, metodo, resource_id, parametros, body, campos_body, problemas, alto_riesgo, motivo, codigo) -> str`
  - `generar_codigo() -> str` (4 dígitos, string).
  - `PendingChange` con campos extra: `codigo: str`, `preview: str`, `alto_riesgo: bool`.
  - `ChangeStore.prepare(..., codigo: str, preview: str, alto_riesgo: bool) -> PendingChange`
  - `ChangeStore.consume(confirmacion_id: str, codigo_tipeado: str) -> PendingChange` (valida código en vez de booleano).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validator_store.py
import unittest
from finnegans.validator import (
    ChangeStore, ValidationError, construir_preview, generar_codigo,
)


class TestPreviewYStore(unittest.TestCase):
    def test_generar_codigo_4_digitos(self):
        c = generar_codigo()
        self.assertTrue(c.isdigit())
        self.assertEqual(len(c), 4)

    def test_preview_marca_problemas_y_codigo(self):
        txt = construir_preview(
            "cliente", "POST", None, {}, {"Nombre": "X"},
            campos_body=["Codigo", "Nombre"],
            problemas=["Falta el campo requerido 'Codigo'."],
            alto_riesgo=False, motivo="operacion estandar", codigo="4271",
        )
        self.assertIn("cliente", txt)
        self.assertIn("POST", txt)
        self.assertIn("Codigo", txt)
        self.assertIn("4271", txt)
        self.assertIn("Falta el campo requerido", txt)

    def test_consume_requiere_codigo_correcto(self):
        store = ChangeStore()
        p = store.prepare(
            api_id="cliente", metodo="POST", resource_id=None, parametros={},
            body={"Codigo": "A"}, resumen="crear", codigo="1234",
            preview="...", alto_riesgo=False,
        )
        with self.assertRaises(ValidationError):
            store.consume(p.confirmacion_id, "0000")  # codigo incorrecto
        # el correcto consume una sola vez
        again = store.consume(p.confirmacion_id, "1234")
        self.assertEqual(again.api_id, "cliente")
        with self.assertRaises(ValidationError):
            store.consume(p.confirmacion_id, "1234")  # ya consumido


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_validator_store -v`
Expected: FAIL con `ImportError: cannot import name 'construir_preview'`.

- [ ] **Step 3: Write minimal implementation**

En `finnegans/validator.py`:

1. Agregar imports arriba: `import secrets`.
2. Extender `PendingChange` con tres campos (después de `resumen`):

```python
    codigo: str = ""
    preview: str = ""
    alto_riesgo: bool = False
```

3. Agregar funciones:

```python
def generar_codigo() -> str:
    """Codigo corto de confirmacion (4 digitos) que el humano debe tipear."""
    return f"{secrets.randbelow(10000):04d}"


def construir_preview(
    api_id: str,
    metodo: str,
    resource_id: str | None,
    parametros: dict | None,
    body: dict | None,
    campos_body: list[str],
    problemas: list[str],
    alto_riesgo: bool,
    motivo: str,
    codigo: str,
) -> str:
    """Arma la vista previa estructurada, campo por campo, para el usuario."""
    lineas = ["=== CONFIRMACION DE CAMBIO ==="]
    if alto_riesgo:
        lineas.append(f"⚠️  ALTO RIESGO: {motivo}")
    lineas.append(f"Operacion: {metodo}  |  Endpoint: {api_id}")
    if resource_id:
        lineas.append(f"Registro afectado (id): {resource_id}")

    if parametros:
        lineas.append("Parametros:")
        for k, v in parametros.items():
            if k == "ACCESS_TOKEN":
                continue
            lineas.append(f"  - {k}: {v}")

    if body:
        lineas.append("Datos a enviar:")
        for k, v in body.items():
            marca = "" if (not campos_body or k in campos_body) else "  ⚠️ (campo no documentado)"
            lineas.append(f"  - {k}: {v}{marca}")

    if problemas:
        lineas.append("Advertencias de validacion:")
        for p in problemas:
            lineas.append(f"  ⚠️ {p}")

    lineas.append("")
    lineas.append(f"Para EJECUTAR, el usuario debe tipear este codigo: {codigo}")
    return "\n".join(lineas)
```

4. Cambiar la firma de `ChangeStore.prepare` para aceptar y guardar `codigo`, `preview`, `alto_riesgo`:

```python
    def prepare(
        self,
        api_id: str,
        metodo: str,
        resource_id: str | None,
        parametros: dict[str, Any] | None,
        body: Any,
        resumen: str,
        codigo: str = "",
        preview: str = "",
        alto_riesgo: bool = False,
    ) -> PendingChange:
        self._cleanup()
        metodo = metodo.upper()
        if metodo not in WRITE_METHODS:
            raise ValidationError(
                f"Metodo '{metodo}' no es de escritura. "
                f"Usa consultar_finnegans para lecturas (GET)."
            )
        confirmacion_id = str(uuid.uuid4())[:8]
        pending = PendingChange(
            confirmacion_id=confirmacion_id,
            api_id=api_id,
            metodo=metodo,
            resource_id=resource_id,
            parametros=parametros or {},
            body=body,
            resumen=resumen,
            codigo=codigo,
            preview=preview,
            alto_riesgo=alto_riesgo,
            expira_en=time.time() + self.TTL_SECONDS,
        )
        self._pending[confirmacion_id] = pending
        return pending
```

5. Reemplazar `ChangeStore.consume` para validar el código:

```python
    def consume(self, confirmacion_id: str, codigo_tipeado: str) -> PendingChange:
        self._cleanup()
        pending = self._pending.get(confirmacion_id)
        if not pending:
            raise ValidationError(
                f"Confirmacion '{confirmacion_id}' no encontrada o expirada. "
                "Volve a preparar el cambio con preparar_cambio."
            )
        if str(codigo_tipeado).strip() != pending.codigo:
            raise ValidationError(
                "Codigo de confirmacion incorrecto. La operacion NO se ejecuto. "
                "Pedile al usuario que tipee exactamente el codigo mostrado en el resumen."
            )
        del self._pending[confirmacion_id]
        return pending
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_validator_store -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run all validator/config/audit tests (regresión)**

Run: `python -m unittest discover -s tests -v`
Expected: todos PASS. (Confirma que el cambio de firma de `consume` no rompió nada aún; `server.py` se ajusta en la Task 8.)

- [ ] **Step 6: Commit**

```bash
git add finnegans/validator.py tests/test_validator_store.py
git commit -m "feat(validator): preview estructurado + codigo de confirmacion en ChangeStore"
```

---

### Task 8: Rewire `preparar_cambio` (async, verificado, con auditoría)

**Files:**
- Modify: `server.py`
- Test: `tests/test_server_preparar.py`

**Interfaces:**
- Consumes: `finnegans.discovery.get_api` + `extraer_schema_escritura`, `finnegans.validator.{evaluar_riesgo, validar_body, construir_preview, generar_codigo}`, `finnegans.audit.AuditLog`, `finnegans.config.Settings`.
- Produces: `async def preparar_cambio(api_id, metodo, id=None, parametros=None, datos=None, descripcion="") -> str` que devuelve el preview + `confirmacion_id`; y helpers `get_audit()`, `get_settings()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_preparar.py
import asyncio
import tempfile
import unittest
from pathlib import Path
import server
from finnegans.audit import AuditLog


class TestPrepararCambio(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        # Redirigir auditoria a temp y forzar settings de prueba
        server._audit = AuditLog(str(Path(self.dir.name) / "a.jsonl"), "TEST")
        server._changes.__init__()  # limpiar pendientes

        async def fake_get_api(api_id):
            return {"request_structure": {"paths": {"/api/cliente": {"post": {
                "requestBodySchema": {"required": ["Codigo"],
                                       "properties": {"Codigo": {"type": "string"}}}}}}}}
        self._orig = server.get_api
        server.get_api = fake_get_api

        class _S:
            allow_delete = False
            high_risk_patterns = []
        server.get_settings = lambda: _S()

    def tearDown(self):
        server.get_api = self._orig
        self.dir.cleanup()

    def test_delete_bloqueado_no_crea_pendiente(self):
        out = asyncio.run(server.preparar_cambio("cliente", "DELETE", id="9"))
        self.assertIn("bloquead", out.lower())
        self.assertEqual(len(server._changes._pending), 0)

    def test_post_crea_pendiente_con_codigo_y_advertencia(self):
        out = asyncio.run(server.preparar_cambio("cliente", "POST", datos={"Nombre": "X"}))
        self.assertIn("CONFIRMACION", out)
        self.assertIn("codigo", out.lower())
        # 'Nombre' no esta en schema, 'Codigo' falta -> advertencias
        self.assertIn("⚠️", out)
        self.assertEqual(len(server._changes._pending), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_server_preparar -v`
Expected: FAIL (`preparar_cambio` no es async / no existe `get_settings` / `_audit`).

- [ ] **Step 3: Write minimal implementation**

En `server.py`:

1. Ampliar imports:

```python
from finnegans import FinnegansClient, FinnegansError
from finnegans.config import Settings
from finnegans.audit import AuditLog
from finnegans.discovery import (
    DiscoveryError, get_api, list_methods, search_apis, extraer_schema_escritura,
)
from finnegans.validator import (
    READ_METHODS, ChangeStore, ValidationError, WRITE_METHODS,
    evaluar_riesgo, validar_body, construir_preview, generar_codigo,
)
```

2. Agregar singletons junto a `_client`/`_changes`:

```python
_settings: Settings | None = None
_audit: AuditLog | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_audit() -> AuditLog:
    global _audit
    if _audit is None:
        s = get_settings()
        _audit = AuditLog(s.audit_log_path, s.operator)
    return _audit
```

3. Reemplazar la tool `preparar_cambio` completa por:

```python
@mcp.tool()
async def preparar_cambio(
    api_id: str,
    metodo: str,
    id: str | None = None,
    parametros: dict | None = None,
    datos: dict | None = None,
    descripcion: str = "",
) -> str:
    """Prepara una ESCRITURA en Finnegans sin ejecutarla (POST/PUT/DELETE).

    Devuelve una vista previa VERIFICADA y un codigo de confirmacion.
    MOSTRAR el preview al usuario y pedirle que tipee el codigo. Luego llamar
    ejecutar_cambio con ese codigo.
    """
    metodo = metodo.upper()
    settings = get_settings()
    audit = get_audit()

    if metodo not in WRITE_METHODS:
        return "Metodo no es de escritura. Usa consultar_finnegans para lecturas."

    bloqueado, alto_riesgo, motivo = evaluar_riesgo(
        metodo, id, api_id, settings.allow_delete, settings.high_risk_patterns
    )
    if bloqueado:
        audit.record("rechazado", metodo=metodo, api_id=api_id, resource_id=id,
                     parametros=parametros, body=datos, resultado="bloqueado", detalle=motivo)
        return f"OPERACION BLOQUEADA: {motivo}"

    # Traer schema del endpoint (degradar con aviso si falla)
    campos_body: list[str] = []
    body_schema = None
    try:
        spec = await get_api(api_id)
        if isinstance(spec, dict):
            info = extraer_schema_escritura(spec, metodo)
            campos_body = info["campos_body"]
            body_schema = info["body_schema"]
    except (DiscoveryError, RuntimeError):
        body_schema = None  # validar_body avisara "sin schema"

    problemas = validar_body(datos, body_schema) if metodo in ("POST", "PUT") else []
    codigo = generar_codigo()
    preview = construir_preview(
        api_id, metodo, id, parametros, datos, campos_body, problemas,
        alto_riesgo, motivo, codigo,
    )

    pending = _changes.prepare(
        api_id=api_id, metodo=metodo, resource_id=id, parametros=parametros,
        body=datos, resumen=descripcion or f"{metodo} en {api_id}",
        codigo=codigo, preview=preview, alto_riesgo=alto_riesgo,
    )
    audit.record("preparado", metodo=metodo, api_id=api_id, resource_id=id,
                 parametros=parametros, body=datos,
                 confirmacion_id=pending.confirmacion_id, detalle=motivo)

    return (
        f"{preview}\n\n"
        f"confirmacion_id: {pending.confirmacion_id}\n"
        f"Cuando el usuario tipee el codigo, llama ejecutar_cambio con "
        f"confirmacion_id='{pending.confirmacion_id}' y codigo_confirmacion=<lo que tipeo>."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_server_preparar -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server_preparar.py
git commit -m "feat(server): preparar_cambio async con preview verificado y auditoria"
```

---

### Task 9: Rewire `ejecutar_cambio` (código, read-back, auditoría)

**Files:**
- Modify: `server.py`
- Test: `tests/test_server_ejecutar.py`

**Interfaces:**
- Consumes: `_changes.consume(confirmacion_id, codigo)`, `FinnegansClient.request`, `get_audit()`.
- Produces: `def ejecutar_cambio(confirmacion_id: str, codigo_confirmacion: str) -> str` (firma nueva; reemplaza `usuario_confirmo: bool`). Incluye read-back tras POST/PUT/DELETE.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_ejecutar.py
import tempfile
import unittest
from pathlib import Path
import server
from finnegans.audit import AuditLog


class _FakeClient:
    def __init__(self):
        self.calls = []
        self.store = {}

    def request(self, method, endpoint, id=None, params=None, body=None):
        self.calls.append((method, endpoint, id))
        if method == "POST":
            self.store["10"] = body
            return {"Codigo": "10", **(body or {})}
        if method == "GET":
            return self.store.get(id, {"_leido": True, "id": id})
        return {"ok": True}


class TestEjecutarCambio(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        server._audit = AuditLog(str(Path(self.dir.name) / "a.jsonl"), "TEST")
        server._changes.__init__()
        self.fake = _FakeClient()
        server._client = self.fake  # inyectar cliente falso

    def tearDown(self):
        server._client = None
        self.dir.cleanup()

    def _preparar(self):
        p = server._changes.prepare(
            api_id="cliente", metodo="POST", resource_id=None, parametros=None,
            body={"Nombre": "X"}, resumen="crear", codigo="4321",
            preview="...", alto_riesgo=False,
        )
        return p.confirmacion_id

    def test_codigo_incorrecto_no_ejecuta(self):
        cid = self._preparar()
        out = server.ejecutar_cambio(cid, "0000")
        self.assertIn("incorrecto", out.lower())
        self.assertEqual(self.fake.calls, [])

    def test_codigo_correcto_ejecuta_y_relee(self):
        cid = self._preparar()
        out = server.ejecutar_cambio(cid, "4321")
        self.assertIn("EJECUTADO", out)
        metodos = [c[0] for c in self.fake.calls]
        self.assertIn("POST", metodos)
        self.assertIn("GET", metodos)  # read-back
        self.assertIn("Verificacion", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_server_ejecutar -v`
Expected: FAIL (firma vieja `usuario_confirmo`, sin read-back).

- [ ] **Step 3: Write minimal implementation**

En `server.py`, reemplazar la tool `ejecutar_cambio` completa por:

```python
@mcp.tool()
def ejecutar_cambio(confirmacion_id: str, codigo_confirmacion: str) -> str:
    """Ejecuta un cambio SOLO si el usuario tipeo el codigo de confirmacion correcto.

    Args:
        confirmacion_id: ID devuelto por preparar_cambio.
        codigo_confirmacion: el codigo que el USUARIO tipeo (no lo inventes).
    """
    audit = get_audit()
    try:
        pending = _changes.consume(confirmacion_id, codigo_confirmacion)
    except ValidationError as e:
        audit.record("rechazado", confirmacion_id=confirmacion_id,
                     codigo_ok=False, resultado="codigo/expiracion", detalle=str(e))
        return f"No ejecutado: {e}"

    try:
        data = get_client().request(
            pending.metodo, pending.api_id, id=pending.resource_id,
            params=pending.parametros, body=pending.body,
        )
    except FinnegansError as e:
        audit.record("error", metodo=pending.metodo, api_id=pending.api_id,
                     resource_id=pending.resource_id, confirmacion_id=confirmacion_id,
                     codigo_ok=True, resultado="error_api", detalle=str(e))
        return f"Error al ejecutar: {e}"

    # Read-back (verificacion posterior)
    verificacion = _read_back(pending, data)

    audit.record("ejecutado", metodo=pending.metodo, api_id=pending.api_id,
                 resource_id=pending.resource_id, confirmacion_id=confirmacion_id,
                 codigo_ok=True, resultado="OK", detalle=verificacion)

    return (
        f"CAMBIO EJECUTADO OK\n{_truncate(data)}\n\n"
        f"Verificacion posterior:\n{verificacion}"
    )


def _read_back(pending, data) -> str:
    """Relee el registro afectado para confirmar el estado resultante."""
    try:
        rid = pending.resource_id
        if pending.metodo == "POST" and isinstance(data, dict):
            rid = data.get("Codigo") or data.get("Id") or data.get("id") or rid
        if not rid:
            return "(no se pudo identificar el registro para releer)"
        if pending.metodo == "DELETE":
            try:
                get_client().request("GET", pending.api_id, id=rid)
                return f"AVISO: el registro {rid} todavia responde a GET tras el DELETE."
            except FinnegansError:
                return f"Confirmado: el registro {rid} ya no existe (DELETE OK)."
        leido = get_client().request("GET", pending.api_id, id=rid)
        return _truncate(leido, 800)
    except FinnegansError as e:
        return f"(no se pudo releer: {e})"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_server_ejecutar -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Actualizar instrucciones del MCP**

En `server.py`, en el texto `instructions=` de `FastMCP`, reemplazar los puntos 3 y 4 por:

```
"3. Para ESCRITURAS usa preparar_cambio, mostra el PREVIEW completo al "
"usuario (incluye un codigo de confirmacion) y pedile que tipee ese codigo.\n"
"4. Solo cuando el usuario tipee el codigo, llama ejecutar_cambio con "
"ese codigo_confirmacion. NUNCA inventes ni adivines el codigo.\n"
```

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server_ejecutar.py
git commit -m "feat(server): ejecutar_cambio con codigo, read-back y auditoria"
```

---

### Task 10: Test de integración end-to-end con stub HTTP

Valida el ciclo completo `preparar → consume → ejecutar → read-back` usando `FinnegansClient` real contra un servidor HTTP falso (sin tocar el ERP ni el MCP de docs).

**Files:**
- Test: `tests/test_integration_stub.py`

**Interfaces:**
- Consumes: `FinnegansClient`, `server.preparar_cambio` (con `get_api` mockeado), `server.ejecutar_cambio`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_integration_stub.py
import asyncio
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import server
from finnegans.audit import AuditLog
from finnegans.client import FinnegansClient
from finnegans.config import Settings


class _Handler(BaseHTTPRequestHandler):
    creado = {}

    def _send(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode("utf-8"))

    def log_message(self, *a):  # silenciar
        pass

    def do_GET(self):
        if self.path.startswith("/api/oauth/token"):
            self._send(200, {"access_token": "x" * 36})
        elif "/api/cliente/" in self.path:
            self._send(200, self.creado or {"_leido": True})
        else:
            self._send(404, {"error": "no encontrado"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        _Handler.creado = {"Codigo": "77", **body}
        self._send(200, _Handler.creado)


class TestIntegracionStub(unittest.TestCase):
    def setUp(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.port}"

        s = Settings(load_env=False)
        s.base_url = base
        s.client_id = "id"
        s.client_secret = "sec"
        self.dir = tempfile.TemporaryDirectory()

        server._client = FinnegansClient(settings=s)
        server._audit = AuditLog(str(Path(self.dir.name) / "a.jsonl"), "TEST")
        server._changes.__init__()

        class _S:
            allow_delete = False
            high_risk_patterns = []
        server.get_settings = lambda: _S()

        async def fake_get_api(api_id):
            return {"request_structure": {"paths": {"/api/cliente": {"post": {
                "requestBodySchema": {"required": ["Nombre"],
                                       "properties": {"Nombre": {"type": "string"}}}}}}}}
        self._orig = server.get_api
        server.get_api = fake_get_api

    def tearDown(self):
        server.get_api = self._orig
        server._client = None
        self.httpd.shutdown()
        self.dir.cleanup()

    def test_ciclo_completo_crear_cliente(self):
        out = asyncio.run(server.preparar_cambio("cliente", "POST", datos={"Nombre": "ACME"}))
        cid = [l for l in out.splitlines() if l.startswith("confirmacion_id:")][0].split(":")[1].strip()
        codigo = list(server._changes._pending.values())[0].codigo

        res = server.ejecutar_cambio(cid, codigo)
        self.assertIn("EJECUTADO", res)
        self.assertIn("77", res)  # el read-back leyo el registro creado


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `python -m unittest tests.test_integration_stub -v`
Expected: si las Tasks 8-9 están completas, PASS. Si algo falla, corregir en el módulo señalado (no en el test).

- [ ] **Step 3: Run full suite (regresión total)**

Run: `python -m unittest discover -s tests -v`
Expected: TODOS los tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_stub.py
git commit -m "test: integracion end-to-end del ciclo de escritura con stub HTTP"
```

---

### Task 11: Instalador para las 20 PCs (`install.py`)

Automatiza: pedir el operador, escribir `.env` (credenciales de servicio embebidas por IT una sola vez), registrar el server en `claude_desktop_config.json`, y correr `verify_setup`.

**Files:**
- Create: `install.py`
- Create: `service-credentials.env.example`
- Test: `tests/test_install.py`

**Interfaces:**
- Consumes: `verify_setup._primary_claude_desktop_config`.
- Produces:
  - `render_env(template: str, operator: str) -> str` (pura)
  - `upsert_mcp_entry(config: dict, python_exe: str, script: str, cwd: str) -> dict` (pura)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_install.py
import unittest
from install import render_env, upsert_mcp_entry


class TestInstall(unittest.TestCase):
    def test_render_env_inserta_operador(self):
        tpl = "FINNEGANS_CLIENT_ID=abc\nFINNEGANS_OPERATOR=\n"
        out = render_env(tpl, "Juan <j@x.com>")
        self.assertIn("FINNEGANS_OPERATOR=Juan <j@x.com>", out)
        self.assertIn("FINNEGANS_CLIENT_ID=abc", out)

    def test_upsert_crea_y_actualiza(self):
        cfg = {}
        cfg = upsert_mcp_entry(cfg, "python.exe", "C:\\x\\server.py", "C:\\x")
        self.assertIn("finnegans-agent", cfg["mcpServers"])
        # idempotente: no duplica
        cfg2 = upsert_mcp_entry(cfg, "python.exe", "C:\\x\\server.py", "C:\\x")
        self.assertEqual(len(cfg2["mcpServers"]), 1)
        self.assertEqual(cfg2["mcpServers"]["finnegans-agent"]["command"], "python.exe")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_install -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'install'`.

- [ ] **Step 3: Write minimal implementation**

Crear `service-credentials.env.example` (IT completa una vez y renombra a `service-credentials.env`, en `.gitignore`):

```bash
# Credenciales de SERVICIO compartidas (opcion B). IT completa esto UNA vez.
# NO commitear el archivo completado.
FINNEGANS_BASE_URL=https://api.finneg.com
FINNEGANS_CLIENT_ID=
FINNEGANS_CLIENT_SECRET=
FINNEGANS_WORKSPACE=SOUTEX
FINNEGANS_DOCS_MCP_URL=https://services.finneg.com/api/1/finnegans-developer-mcp/finnegans-api-docs/mcp
FINNEGANS_DOCS_CLIENT_ID=
FINNEGANS_DOCS_SECRET_KEY=
FINNEGANS_ALLOW_DELETE=false
FINNEGANS_HIGH_RISK_PATTERNS=
FINNEGANS_OPERATOR=
```

Crear `install.py`:

```python
"""Instalador del conector Finnegans para una PC (opcion B).

Uso (IT, en la PC del usuario):
    python install.py

Pide el nombre del operador, escribe .env a partir de service-credentials.env,
registra el server en claude_desktop_config.json y corre verify_setup.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def render_env(template: str, operator: str) -> str:
    """Devuelve el contenido de .env con el operador insertado."""
    lineas = []
    visto = False
    for line in template.splitlines():
        if line.startswith("FINNEGANS_OPERATOR="):
            lineas.append(f"FINNEGANS_OPERATOR={operator}")
            visto = True
        else:
            lineas.append(line)
    if not visto:
        lineas.append(f"FINNEGANS_OPERATOR={operator}")
    return "\n".join(lineas) + "\n"


def upsert_mcp_entry(config: dict, python_exe: str, script: str, cwd: str) -> dict:
    """Inserta/actualiza la entrada 'finnegans-agent' en el config de Claude."""
    config = dict(config)
    servers = dict(config.get("mcpServers", {}))
    servers["finnegans-agent"] = {"command": python_exe, "args": [script], "cwd": cwd}
    config["mcpServers"] = servers
    return config


def main() -> int:
    cred = ROOT / "service-credentials.env"
    if not cred.exists():
        print("[ERROR] Falta service-credentials.env (copiar de .example y completar).")
        return 1

    operator = input("Nombre y email del operador (ej. Juan <j@x.com>): ").strip()
    if not operator:
        print("[ERROR] El operador es obligatorio para la auditoria.")
        return 1

    (ROOT / ".env").write_text(
        render_env(cred.read_text(encoding="utf-8"), operator), encoding="utf-8"
    )
    print("[OK] .env escrito.")

    from verify_setup import _primary_claude_desktop_config

    cfg_path = _primary_claude_desktop_config()
    cfg = {}
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8") or "{}")
    cfg = upsert_mcp_entry(cfg, sys.executable, str(ROOT / "server.py"), str(ROOT))
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Registrado en {cfg_path}")

    print("\nVerificando instalacion...")
    import verify_setup
    return verify_setup.main()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_install -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Añadir a `.gitignore`**

Verificar que `.gitignore` incluya `service-credentials.env` y `audit/`. Si no, agregarlos.

- [ ] **Step 6: Commit**

```bash
git add install.py service-credentials.env.example tests/test_install.py .gitignore
git commit -m "feat(install): instalador por PC (env + registro MCP + verify)"
```

---

### Task 12: Actualizar instrucciones del asistente al flujo Nivel 3

**Files:**
- Modify: `ASSISTANT_INSTRUCTIONS.md`

**Interfaces:** ninguna (documento para pegar en Claude Desktop).

- [ ] **Step 1: Reemplazar la sección "Para CREAR, MODIFICAR o ELIMINAR datos"**

En `ASSISTANT_INSTRUCTIONS.md`, reemplazar el punto 3 por:

```markdown
3. Para CREAR, MODIFICAR o ELIMINAR datos:
   a. Usa `preparar_cambio` (no ejecuta nada todavia).
   b. Mostra al usuario el PREVIEW COMPLETO tal cual lo devuelve la tool
      (incluye la operacion, los datos campo por campo, advertencias ⚠️ y un
      codigo de confirmacion de 4 digitos).
   c. Pedile al usuario que tipee ese codigo si esta de acuerdo.
   d. SOLO cuando el usuario tipee el codigo, llama `ejecutar_cambio` con
      `codigo_confirmacion` igual a lo que tipeo. NUNCA inventes el codigo.
   e. Mostra la "Verificacion posterior" para confirmar como quedo el registro.
4. Si el usuario no tipea el codigo o dice que no, no ejecutes nada.
```

Y en "Reglas de seguridad" agregar:

```markdown
- Si el preview muestra advertencias ⚠️ (campos no documentados o faltantes),
  avisale al usuario ANTES de que confirme; puede ser un error.
- Las operaciones marcadas ALTO RIESGO requieren atencion extra: leele el motivo.
- Los DELETE pueden estar bloqueados por politica; si es asi, explicalo.
```

- [ ] **Step 2: Commit**

```bash
git add ASSISTANT_INSTRUCTIONS.md
git commit -m "docs: instrucciones del asistente al flujo de confirmacion Nivel 3"
```

---

### Task 13: Smoke test real y checklist de entrega

Verificación final contra el ERP real antes de repartir. No es código; es el gate de "listo".

**Files:**
- Modify: `README.md` (agregar checklist de entrega)

- [ ] **Step 1: Configurar `.env` real** con las credenciales de servicio (rol acotado, NO admin) y un `FINNEGANS_OPERATOR` de prueba.

- [ ] **Step 2: Correr verificación**

Run: `python verify_setup.py`
Expected: checks 4, 5 y 6 en `[OK]`.

- [ ] **Step 3: Lectura real** — en Claude Desktop (tras reiniciar), pedir una consulta de solo lectura (ej. "datos del cliente <código real>") y confirmar respuesta correcta.

- [ ] **Step 4: Escritura de prueba controlada** — sobre un registro descartable: pedir una modificación, verificar que el PREVIEW muestre los campos correctos y el código, tipear el código, y confirmar que la "Verificacion posterior" refleje el cambio. Revisar que `audit/finnegans-audit.jsonl` tenga las líneas `preparado` y `ejecutado` con el operador correcto y SIN token.

- [ ] **Step 5: Documentar el checklist en `README.md`** (sección "Entrega a usuarios") con los pasos 1-4 anteriores como criterio de aceptación por PC.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: checklist de entrega y smoke test real por PC"
```

---

## Self-Review (cobertura del spec)

- Fix descubrimiento (asyncio/proceso viejo) → **Task 1**.
- Config: operador, audit path, allow_delete, patrones → **Task 2**.
- Auditoría append-only con redacción de secretos → **Task 3**.
- Schema de escritura desde discovery + caché → **Task 4**.
- Vista previa verificada campo-por-campo + validación de body → **Tasks 5, 7**.
- Lista negra / DELETE bloqueado / masivos / patrones → **Task 6**.
- Código de confirmación (freno anti-atajo) → **Tasks 7, 8, 9**.
- Read-back (verificación posterior) → **Task 9**.
- Identidad de operador en cada evento → **Tasks 3, 8, 9**.
- Distribución a 20 PCs (instalador + verify) → **Task 11**.
- Instrucciones del asistente Nivel 3 → **Task 12**.
- Testing (unit + stub + smoke real) → **Tasks 2-11 (unit/stub), 13 (real)**.
- Fuera de alcance (Enfoque 2, gate externo, auditoría central, creds por usuario) → no se implementa, documentado en el spec.

Consistencia de tipos verificada: `evaluar_riesgo` retorna `(bloqueado, alto_riesgo, motivo)` y se consume igual en Task 8; `ChangeStore.consume(confirmacion_id, codigo)` (Task 7) coincide con la llamada en `ejecutar_cambio` (Task 9); `extraer_schema_escritura` retorna `campos_body`/`body_schema` consumidos en Task 8.
