# Finnegans MCP Desktop Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild this repo as a Claude Desktop extension (`.mcpb`, Python + uv). It gets one settings form for keys, merged endpoint search across every source of truth, and an in-server DuckDB workspace so large Finnegans data never fills the chat.

**Architecture:** `src/finnegans_core` holds everything that isn't MCP: config, HTTP client, redaction, error translation, swagger + docs-MCP catalog, merged search, DuckDB workspace, response budget, export, and the business guide. `src/finnegans_mcp` is a thin MCP server (8 tools + short instructions) on top of it. `manifest.json` maps the settings form to environment variables. Legacy code is deleted. Knowledge-bearing modules and their tests are ported.

**Tech Stack:**
- Python ≥3.12, uv
- `mcp` 2.x (`from mcp.server import MCPServer`), which brings `httpx2`, `pydantic` and `anyio`
- `duckdb` 2.x, `openpyxl`, pytest
- `@anthropic-ai/mcpb` CLI via `npx`

**Spec:** `docs/superpowers/specs/2026-11-02-finnegans-mcp-extension-design.md`

## Global Constraints

- Branch: `feat/extension-desktop` (no upstream; never push to `master`).
- Dependencies (pyproject): `mcp>=2.3,<3`, `duckdb>=2.0,<3`, `openpyxl>=3.1`. Dev: `pytest`. HTTP uses `httpx2` (already a dependency of `mcp`); add no other HTTP library.
- MCPB manifest `manifest_version: "0.4"`, `server.type: "uv"`, platforms `["win32"]`, runtime `python >=3.12`.
- Env vars (the only config source, no `.env` support): `FINNEGANS_CLIENT_ID`, `FINNEGANS_CLIENT_SECRET`, `FINNEGANS_SWAGGER_KEY`, `FINNEGANS_DOCS_CLIENT_ID`, `FINNEGANS_DOCS_SECRET_KEY`, `FINNEGANS_EXPORT_DIR`, `FINNEGANS_BASE_URL` (default `https://api.finneg.com`), `FINNEGANS_SWAGGER_URL` (default `https://oneteam.finneg.com/BSA/api/swaggerGlobal`), `FINNEGANS_DOCS_MCP_URL` (default `https://services.finneg.com/api/1/finnegans-developer-mcp/finnegans-api-docs/mcp`).
- `RESPUESTA_MAX_CHARS = 8000`: no tool returns more than this. Larger output is paged, summarized or exported, and the response says which. Never cut silently.
- Secrets (client_id, client_secret, token, swagger key, docs keys) never appear in any tool output, error, or exported file.
- All user-facing text is in clear Spanish for non-technical leaders. Code identifiers follow the repo's Spanish naming (`buscar_endpoint`, `traducir_error`).
- Endpoint type comes from the swagger tag description `Tipo: Viewer` / `Tipo: EntidadVO`, never from the path.
- Viewer/EntidadVO query params are passed exactly as the spec spells them (case included).
- No confirmation codes, risk patterns, DELETE flag, audit log, or truncation anywhere.
- Tests: `uv run pytest -q`. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **SQL that escapes the workspace** (`COPY`, `ATTACH`, `INSTALL`, `read_csv('C:/…')`, `SELECT 1; DROP TABLE t`) must be refused with a plain message, never executed → tests in Task 5.
2. **Odd response bodies in `leer`**: an empty list, a list of scalars, plain text, or `null` must give a clear summary, not a crash → tests in Task 5 and Task 7.
3. **A Finnegans error body echoing the token or secret** must come out redacted in every tool, `escribir` included → tests in Task 2 and Task 7.
4. **Table names from awkward paths** (`reports/ACOrdenesCompraPendientes`, ids with `-`, accents, `ñ`) must become valid identifiers that `consultar` can use as returned → test in Task 5.
5. **A stale `desde` offset** after the table was reloaded, or beyond the last row, must say "no hay más filas" rather than error → test in Task 5.

---

### Task 0: Spike: prove a `uv` extension works in Claude Desktop (throwaway, gate)

Nothing from this task is committed to the repo. Work in the session scratchpad.

- [ ] **Step 1:** Copy `examples/hello-world-uv` from `github.com/modelcontextprotocol/mcpb` into a scratch folder.
  - Add `duckdb>=2.0,<3` and `mcp>=2.3,<3` to its `pyproject.toml`.
  - Add a `user_config` field `secreto` (`type: string`, `sensitive: true`), passed as env `SPIKE_SECRETO`.
  - Write one tool `probar()` that returns `duckdb.__version__` and `len(os.environ["SPIKE_SECRETO"])`.
- [ ] **Step 2:** Run `npx -y @anthropic-ai/mcpb pack` in the folder. Expected: a `.mcpb` file is produced.
- [ ] **Step 3 (Juan):** Double-click the `.mcpb` on a Windows PC with no Python on PATH, fill in `secreto`, and ask Claude to call `probar`. Expected: the duckdb version and the correct length.
- [ ] **Step 4 (Juan, as Owner):** Upload the same `.mcpb` under Organization settings → Connectors → Desktop. Install it as a team extension on a PC, and repeat Step 3.
- [ ] **Step 5: Gate.** If Step 3 or Step 4 fails, stop and report to Juan, because the packaging decision has to be revisited. Record the Claude Desktop version used in the PR description.

### Task 1: Scaffold the new package and remove legacy code

**Files:**
- Create: `pyproject.toml`, `.mcpbignore`, `src/finnegans_core/__init__.py`, `src/finnegans_mcp/__init__.py`, `tests/conftest.py`
- Move (git mv): `finnegans/vocabulario.py` → `src/finnegans_core/vocabulario.py`; `finnegans/errores.py` → `src/finnegans_core/errores.py`; `tests/test_vocabulario.py` → `tests/core/test_vocabulario.py`; `tests/test_errores.py` → `tests/core/test_errores.py`
- Delete: `cli.py`, `install.py`, `verify_setup.py`, `server.py`, `requirements.txt`, `scripts/actualizar.bat`, `scripts/instalar.bat`, `service-credentials.env.example`, `.env.example`, `examples/`, `finnegans/validator.py`, `finnegans/audit.py`, `finnegans/config.py`, `finnegans/__init__.py`, and every test under `tests/` not moved here or in Tasks 2–3
- Modify: `.github/workflows/tests.yml`, `.gitignore`

Keep `finnegans/client.py`, `finnegans/redaction.py`, `finnegans/discovery.py`, `finnegans/swagger_catalog.py` and their tests until Tasks 2–4 port them. Keep `ASSISTANT_INSTRUCTIONS.md` until Task 6.

**Interfaces:**
- Produces: importable `finnegans_core.vocabulario` (`sin_acentos`, `normalizar`, `variantes`, `sinonimos_de`, `SINONIMOS`) and `finnegans_core.errores.traducir_error(api_id: str, mensaje: str, id: str | None = None) -> str`, both unchanged in behavior.

- [ ] **Step 1:** Install uv if missing (`python -m pip install --user uv`) and check it with `uv --version`.
- [ ] **Step 2:** Write `pyproject.toml`.
  - `name = "finnegans-mcp"`, `requires-python = ">=3.12"`, the dependencies from Global Constraints.
  - Build backend `hatchling` with `packages = ["src/finnegans_core", "src/finnegans_mcp"]`.
  - `[dependency-groups] dev = ["pytest"]`, `[tool.pytest.ini_options] testpaths = ["tests"]`.
  - Write `.mcpbignore` with the same entries as the hello-world-uv example, plus `tests/`, `docs/`, `.github/`, `scripts/`.
- [ ] **Step 3:** Do the moves. Rewrite the imports in the moved tests to `from finnegans_core import vocabulario as v` and `from finnegans_core.errores import traducir_error`. Convert them to pytest only where unittest gets in the way; they can stay `unittest.TestCase`, since pytest collects those.
- [ ] **Step 4:** Do the deletions.
  - Add `exports/`, `.venv/` and `*.mcpb` to `.gitignore`.
  - Remove the `.env`-specific lines, but keep `*.env` and `.env*` ignored so old local files never get committed.
- [ ] **Step 5:** Update CI to use `astral-sh/setup-uv` and run `uv sync` then `uv run pytest -q`.
- [ ] **Step 6:** Run `uv sync && uv run pytest -q tests/core`. Expected: all vocabulario and errores tests PASS.
- [ ] **Step 7:** Commit with `refactor: nuevo paquete finnegans_core y borrar el conector legacy`.

### Task 2: Config, redaction and HTTP client

**Files:**
- Create: `src/finnegans_core/config.py`, `src/finnegans_core/secretos.py`, `src/finnegans_core/client.py`
- Delete: `finnegans/client.py`, `finnegans/redaction.py`, `tests/test_client_auth.py` (its cases are ported to the new test)
- Test: `tests/core/test_config.py`, `tests/core/test_client.py`

**Interfaces:**
- Produces:
  - `Settings` is a frozen dataclass with fields `client_id, client_secret, swagger_key, docs_client_id, docs_secret_key, export_dir, base_url, swagger_url, docs_mcp_url` (all `str`, empty when unset).
    - `Settings.from_env(env: Mapping[str, str] = os.environ) -> Settings`. It never raises. `export_dir` defaults to `~/Documents/Finnegans`.
    - `Settings.faltantes() -> list[str]` returns the human labels of the missing required keys, in form order: `"Client ID de Finnegans"`, `"Client secret de Finnegans"`, `"Clave del swagger"`, `"Client ID de la documentación"`, `"Secret key de la documentación"`.
    - `Settings.secretos() -> list[str]` returns the non-empty secret values.
  - `Redactor(valores: Iterable[str])`, with `.agregar(valor: str) -> None` and `.limpiar(texto: object) -> str`. `.limpiar` replaces each value with `***`, longest first.
  - `FinnegansError(Exception)`, `FinnegansAuthError(FinnegansError)`.
  - `FinnegansClient(settings: Settings, http: httpx2.Client | None = None)`:
    - `.token(forzar: bool = False) -> str`
    - `.request(metodo: str, path: str, id: str | None = None, params: dict | None = None, body: Any = None) -> Any`, which returns parsed JSON, or text when the body isn't JSON
    - `.redactor: Redactor`

- [ ] **Step 1: Write the failing tests.** Fake HTTP with `httpx2.MockTransport`.
  - `test_from_env_usa_defaults_y_no_explota_sin_claves`: `Settings.from_env({})` → `base_url == "https://api.finneg.com"`, and `faltantes()` lists the 5 labels in order.
  - `test_token_texto_plano_y_json`: the token endpoint returns `abc` → `token() == "abc"`. With `{"access_token":"xyz"}` → `"xyz"`.
  - `test_access_token_va_en_cada_request`: the request URL query contains `ACCESS_TOKEN=abc`, and the path is `/api/cliente/P01093` for `request("GET","cliente",id="P01093")`.
  - `test_reintenta_una_vez_ante_401`: first 401 then 200 → the result is returned and 2 tokens were fetched. Two 401s → `FinnegansError`.
  - `test_body_json_en_put`: `request("PUT","cliente",id="X",body={"Codigo":"X"})` sends `Content-Type: application/json` and that JSON.
  - `test_errores_no_filtran_secretos`: the token endpoint returns 401 with a body containing the client_secret, and a data call returns 500 with a body containing the token. The `str()` of both raised errors contains neither value, but does contain `***`.
  - `test_base_url_invalida_da_error_claro`: `base_url="api.finneg.com"` → a `FinnegansAuthError` whose message contains `https://` and no secret.
- [ ] **Step 2:** Run `uv run pytest -q tests/core/test_config.py tests/core/test_client.py`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement the three modules.**
  - The token request is `GET {base_url}/api/oauth/token?grant_type=client_credentials&client_id=…&client_secret=…`.
  - Cache the token for 3600 s.
  - Every `FinnegansError` message goes through `self.redactor.limpiar`.
  - The redactor starts from `settings.secretos()`, and each fetched token is added with `.agregar`.
- [ ] **Step 4:** Run the same command. Expected: PASS.
- [ ] **Step 5:** Commit with `feat(core): config desde env, redactor y cliente httpx2`.

### Task 3: Swagger catalog with endpoint types

**Files:**
- Create: `src/finnegans_core/catalogo/__init__.py`, `src/finnegans_core/catalogo/swagger.py`
- Delete: `finnegans/swagger_catalog.py`, `tests/test_swagger_catalog.py` (ported), `tests/test_server_discovery_swagger.py`
- Test: `tests/core/test_swagger.py`

**Interfaces:**
- Consumes: `Settings`, `Redactor`, and `vocabulario` from Tasks 1–2.
- Produces:
  - `TipoEndpoint = Literal["viewer", "entidad", "otro"]`
  - `Coincidencia` is a dataclass: `path: str, metodos: list[str], tipo: TipoEndpoint, resumen: str, puntaje: float, cobertura: float`. `cobertura` is the fraction of query concepts matched, from 0 to 1.
  - `Operacion` is a dataclass: `metodo, path, resumen, tipo, parametros: list[dict]` (`nombre, requerido, ubicacion, descripcion`), `tiene_body: bool`, `body_campos: list[str]`, `body_requeridos: list[str]`, `body_schema_ok: bool`.
  - `SwaggerCatalog(settings: Settings, http: httpx2.Client | None = None)`:
    - `.spec() -> dict`, cached per process, raises `SwaggerError`
    - `.tipo(path: str) -> TipoEndpoint`
    - `.buscar(consulta: str, limite: int = 8) -> list[Coincidencia]`
    - `.ver(recurso_o_path: str) -> list[Operacion]`
    - `.campo(recurso_o_path: str, metodo: str, campo: str) -> dict`, which returns one nested body field's sub-properties, one level deep
  - `SwaggerError(Exception)`

- [ ] **Step 1: Port the tests from `tests/test_swagger_catalog.py`** to the new class: tokens, camelCase, precision ranking, external `$ref` resolution and its cache, degradation when the download fails, and ACCESS_TOKEN excluded from params. Extend the `SPEC` fixture with a `tags` list carrying `"description": "… Tipo: Viewer"` and `"… Tipo: EntidadVO"`. Then add:
  - `test_tipo_sale_del_tag_y_no_del_path`: `/reports/ACOrdenesCompraPendientes` → `"viewer"`, `/cliente/{codigo}` → `"entidad"`, `/oauth/token` → `"otro"`. Also a fixture path `/reports/raro` tagged `Tipo: EntidadVO` → `"entidad"`.
  - `test_buscar_expone_tipo_y_cobertura`: `buscar("ordenes compra pendientes")[0]` has `tipo == "viewer"` and `cobertura == 1.0`. `buscar("cliente marciano")[0].cobertura == 0.5`.
  - `test_ver_no_vuelca_objetos_anidados`: for a VO with `ProvinciaItems` (an array of objects), `body_campos` contains `"ProvinciaItems"` and none of its sub-fields.
  - `test_campo_expande_un_nivel`: `campo("cliente","PUT","ProvinciaItems")` contains the key `"ControlImpositivo1"`.
  - `test_errores_de_carga_no_filtran_la_key`: the spec download fails with the key in the URL → the `SwaggerError` text has no key.
- [ ] **Step 2:** Run `uv run pytest -q tests/core/test_swagger.py`. Expected: FAIL.
- [ ] **Step 3: Implement `catalogo/swagger.py`.**
  - Move the tokenizer, `_conceptos`, scoring and `$ref` resolution logic from `finnegans/swagger_catalog.py`. Replace urllib with `httpx2`.
  - `tipo` builds a `{tag name: tipo}` map once from `spec["tags"]` (regex `Tipo:\s*(\w+)`: `Viewer` → viewer, `EntidadVO` → entidad), then uses the path's first operation tag.
  - `cobertura` = concepts matched / concepts in the query.
- [ ] **Step 4:** Run the same command. Expected: PASS.
- [ ] **Step 5:** Commit with `feat(core): catalogo swagger con tipo de endpoint`.

### Task 4: Docs MCP client and merged search

**Files:**
- Create: `src/finnegans_core/catalogo/docs_mcp.py`, `src/finnegans_core/catalogo/busqueda.py`, `tests/fixtures/docs_search_apis.json`
- Delete: `finnegans/discovery.py`, `tests/test_discovery_schema.py`, and the now-empty `finnegans/` package
- Test: `tests/core/test_busqueda.py`

**Interfaces:**
- Consumes: `SwaggerCatalog.buscar`, `Coincidencia`, `Settings`, `Redactor`.
- Produces:
  - `DocsMcp(settings: Settings)` with `async .buscar(consulta: str) -> list[dict]` (`{"path": str, "resumen": str}`), raising `DocsMcpError`.
  - `ResultadoBusqueda` is a dataclass: `filas: list[FilaBusqueda]`, `notas: list[str]`.
  - `FilaBusqueda`: `path, metodos, tipo, resumen, fuentes: list[str]` (`"swagger"`/`"docs"`).
  - `async buscar_endpoint(consulta: str, swagger: SwaggerCatalog, docs: DocsMcp | None, limite: int = 8) -> ResultadoBusqueda`
  - `formatear_busqueda(r: ResultadoBusqueda) -> str`, one line per row: `- GET /reports/X [viewer] resumen (swagger+docs)`, then `Notas:` lines.

- [ ] **Step 1: Capture the real docs MCP response shape.**
  - Write a throwaway script in the scratchpad. It reads the `FINNEGANS_DOCS_*` keys from Juan's old local `.env` (still on disk, ignored) and calls `search_apis` with `{"query": "ordenes de compra"}` through `mcp.client.streamable_http.streamable_http_client`. Pass an `httpx2.AsyncClient` that carries the `x-client-id` / `x-secret-key` headers.
  - Save the JSON to `tests/fixtures/docs_search_apis.json`, after checking it contains no keys.
- [ ] **Step 2: Write the failing tests**, with `DocsMcp` faked.
  - `test_une_por_path_y_marca_fuentes`: a path returned by both sources → one row with `fuentes == ["swagger","docs"]`.
  - `test_nota_si_las_fuentes_no_coinciden`: the docs top result isn't in the swagger results → one note containing `"las fuentes no coinciden"`.
  - `test_nota_si_hay_empate`: the top two swagger scores are equal → a note containing `"empate"`.
  - `test_nota_si_coincidencia_parcial`: the best `cobertura < 1` → a note containing `"coincidencia parcial"`.
  - Every note ends with `"preguntale al usuario"`.
  - `test_sigue_solo_con_swagger_si_docs_falla`: `DocsMcpError`, or `docs=None` → rows still returned, plus a note containing `"solo con el swagger"`.
  - `test_parsea_respuesta_real_de_docs`: `DocsMcp` parsing of the fixture gives a non-empty list of paths.
- [ ] **Step 3:** Run `uv run pytest -q tests/core/test_busqueda.py`. Expected: FAIL.
- [ ] **Step 4: Implement.**
  - Run the two searches concurrently with `anyio`.
  - Rows from swagger keep its order. Docs-only rows are appended after them, with `tipo` from `swagger.tipo(path)`.
- [ ] **Step 5:** Run it. Expected: PASS. Then run `uv run pytest -q`: everything passes.
- [ ] **Step 6:** Commit with `feat(core): busqueda unificada swagger + docs MCP`.

### Task 5: DuckDB workspace, response budget, export

**Files:**
- Create: `src/finnegans_core/workspace.py`, `src/finnegans_core/presupuesto.py`, `src/finnegans_core/exportar.py`
- Test: `tests/core/test_workspace.py`, `tests/core/test_exportar.py`

**Interfaces:**
- Produces:
  - `RESPUESTA_MAX_CHARS = 8000` (in `presupuesto.py`)
  - `formatear_tabla(columnas: list[str], filas: list[tuple], max_chars: int) -> tuple[str, int]` returns a markdown table and how many rows fit. At least one row is always included. Cells are never cut.
  - `resumir_valor(v: Any, max_len: int = 120) -> str`, for sample rows only. It appends `…`.
  - `nombre_tabla(path: str, id: str | None = None) -> str` gives lowercase `[a-z0-9_]`, accents stripped, `ñ` → `n`, last path segment (`reports/ACOrdenesCompraPendientes` → `acordenescomprapendientes`), `_` + sanitized id when given, and a `t_` prefix if it starts with a digit.
  - `Resumen` is a dataclass: `tabla: str | None, filas: int, columnas: list[tuple[str, str]], muestra: str, nota: str | None`.
  - `Workspace(memoria: str = "1GB")`:
    - `.cargar(tabla: str, datos: Any) -> Resumen`
    - `.crudo(tabla: str) -> Any`, the original JSON as loaded, raising `KeyError`
    - `.consultar(sql: str, desde: int = 0) -> str`
    - `.ejecutar(sql: str) -> tuple[list[str], list[tuple]]`, which is read-only, used by export, and raises `ConsultaInvalida`
  - `ConsultaInvalida(Exception)`
  - `exportar(columnas: list[str], filas: list[tuple], carpeta: Path, nombre: str, formato: Literal["xlsx","csv"]) -> Path` creates the folder if it's missing, never overwrites (adds ` (2)`, ` (3)`, …), and writes csv as UTF-8 with BOM.

- [ ] **Step 1: Write the failing tests.**
  - `test_cargar_lista_de_objetos`: 4,150 synthetic clientes → `Resumen.filas == 4150`, 4 columns, and a `muestra` of 3 rows under 1,500 chars.
  - `test_cargar_objeto_unico_es_tabla_de_una_fila`: a single dict → `filas == 1`, and `crudo(tabla)` equals the input dict exactly.
  - `test_cargar_anidados_permite_unnest`: a record with `ProvinciaItems: [{...},{...}]` → `consultar("SELECT unnest(ProvinciaItems) FROM t")` returns 2 rows.
  - `test_cargar_casos_raros`: `[]` → `tabla is None`, `filas == 0`, and the `nota` says it came back empty. `[1,2]` → one column `valor`. `"texto"` or `None` → `tabla is None`, and the `nota` contains the text, cut at 500 chars.
  - `test_consultar_pagina_y_dice_como_seguir`: 4,150 rows → the output is ≤ 8000 chars and contains `"de 4150"` and `"desde="`. Calling with that `desde` returns the next rows. A `desde` ≥ the total → `"no hay más filas"`.
  - `test_consultar_rechaza_lo_que_no_es_lectura`: each of `COPY t TO 'x.csv'`, `ATTACH 'x.db'`, `INSTALL httpfs`, `CREATE TABLE z AS SELECT 1`, `SELECT 1; DROP TABLE t` raises `ConsultaInvalida`, and the table still exists afterwards.
  - `test_consultar_no_lee_archivos_de_la_pc`: `SELECT * FROM read_csv('C:/Windows/win.ini')` raises `ConsultaInvalida`, with DuckDB's own error wrapped.
  - `test_show_y_describe_funcionan`: `SHOW TABLES` lists the loaded tables.
  - `test_nombre_tabla`: `nombre_tabla("reports/ACOrdenesCompraPendientes") == "acordenescomprapendientes"`, `nombre_tabla("cliente","P-01093") == "cliente_p_01093"`, `nombre_tabla("compañía/list") == "list"`, and `nombre_tabla("dirección") == "direccion"`.
  - `test_exportar_xlsx_y_csv`: accents and `ñ` survive a round-trip read with openpyxl and csv, and the second export with the same name gets ` (2)`.
- [ ] **Step 2:** Run `uv run pytest -q tests/core/test_workspace.py tests/core/test_exportar.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **Connection setup:**
    - Open `duckdb.connect(":memory:")` with a private temp dir.
    - Set `allowed_directories=[that temp dir]`, then `enable_external_access=false`, `autoinstall_known_extensions=false`, `autoload_known_extensions=false`, `memory_limit`, and finally `lock_configuration=true`.
  - **Loading:** write the data as NDJSON into the temp dir, then run `CREATE OR REPLACE TABLE "{tabla}" AS SELECT * FROM read_json_auto(path)`. Keep `datos` in a dict for `.crudo`.
    - **If DuckDB 2.x rejects `allowed_directories` together with disabled external access, stop and report.** The fallback is loading from Python without file access. Don't silently re-enable external access.
  - **Read-only check:** use `duckdb.extract_statements(sql)`. Exactly one statement is allowed, and its `.type` must be `SELECT`, or the statement must start with `SHOW`/`DESCRIBE`/`SUMMARIZE` (check the type enum first). Any `duckdb.Error` during execution is wrapped in `ConsultaInvalida` with a Spanish message.
  - **Paging:** `consultar` fetches all rows and pages them in Python.
- [ ] **Step 4:** Run the same command. Expected: PASS.
- [ ] **Step 5:** Commit with `feat(core): workspace DuckDB, presupuesto de respuesta y exportacion`.

### Task 6: Business guide and server instructions

**Files:**
- Create: `src/finnegans_core/guia/{sucursales,iibb,rutas,tipos,escrituras,clientes,parametros}.md`, `src/finnegans_core/guia/__init__.py`, `src/finnegans_mcp/instrucciones.py`
- Delete: `ASSISTANT_INSTRUCTIONS.md`
- Test: `tests/core/test_guia.py`

**Interfaces:**
- Produces:
  - `TEMAS: tuple[str, ...]`
  - `guia(tema: str | None = None) -> str` reads the files with `importlib.resources`. No argument gives the topic list with one line each. An unknown topic gives the list plus `"No existe el tema"`.
  - `INSTRUCCIONES: str`

- [ ] **Step 1: Write the topic files** from spec §7 and the content of `ASSISTANT_INSTRUCTIONS.md`. Keep every fact, and drop every mention of `preparar_cambio`, confirmation codes or truncation.
  - `parametros.md` covers viewer params:
    - prefixes and case are copied exactly
    - the relative date constants, listed in full: `getCurrentDate, getFirstDayOfWeek, getFirstDayOfMonth, getLastDayOfMonth, getFirstDayOfYear, getLastDayOfYear, getFirstDayOfLastMonth, getLastDayOfLastMonth, getFirstDayOfLastWeek, getLastDayOfLastWeek, getFirstDayOfLastYear, getLastDayOfLastYear`
    - `arbol(nombre)` smart selection
    - `updatedSince` on `/list`
    - `createIfNotExists=1` on PUT
    - the `…DEALS` twins
- [ ] **Step 2: Write `INSTRUCCIONES`** with exactly this text:

```text
Sos el asistente de Finnegans (ERP) para líderes no técnicos de SOUTEX / Formas. Respondé en castellano claro, sin tecnicismos.
1. Antes de leer o escribir, usá buscar_endpoint y después ver_endpoint. Si la búsqueda trae una nota que dice "preguntale al usuario", preguntale antes de seguir.
2. Si el pedido necesita sucursal, unidad de negocio o rango de fechas y el usuario no lo dijo, preguntá. Nunca asumas una sucursal.
3. Para leer usá leer. Si devuelve una tabla, trabajá con consultar (SQL) o exportar; nunca pidas ni muestres todas las filas.
4. Para modificar un registro, cargalo con leer y usá escribir con base + cambios. Mostrá al usuario el diff que devuelve escribir.
5. Para reglas del negocio (sucursales, IIBB, rutas, tipos de endpoint, parámetros de reportes) usá guia.
```

- [ ] **Step 3: Write the tests.**
  - `test_cada_tema_existe_y_no_esta_vacio`.
  - `test_instrucciones_cortas`: `len(INSTRUCCIONES) < 1200`.
  - `test_no_quedan_rastros_de_limites_viejos`: no topic or instruction contains `preparar_cambio`, `ejecutar_cambio`, `codigo de confirmacion`, or `truncado`.
  - `test_guia_conserva_hechos_clave`: `sucursales` contains `EMPRE01`. `iibb` contains `ControlImpositivo1` and `Convenio Multilateral`. `escrituras` contains `406` and `objeto completo`.
- [ ] **Step 4:** Run `uv run pytest -q tests/core/test_guia.py`. Expected: PASS.
- [ ] **Step 5:** Commit with `feat: guia de negocio e instrucciones del servidor`.

### Task 7: MCP server and tools

**Files:**
- Create: `src/finnegans_mcp/server.py`, `src/finnegans_mcp/escritura.py`, `src/finnegans_mcp/__main__.py`
- Test: `tests/mcp/test_tools.py`, `tests/mcp/test_escritura.py`

**Interfaces:**
- Consumes: everything produced in Tasks 2–6.
- Produces:
  - `crear_servidor(settings: Settings, client: FinnegansClient | None = None, swagger: SwaggerCatalog | None = None, docs: DocsMcp | None = None, workspace: Workspace | None = None) -> MCPServer`. Every dependency can be injected for tests and is built from `settings` when omitted.
  - `main() -> None` runs `crear_servidor(Settings.from_env()).run()` over stdio, and is called from `server.py`'s `if __name__ == "__main__"` and from `__main__.py`.
  - Tools, with the exact names and parameters:
    - `buscar_endpoint(consulta: str)`
    - `ver_endpoint(path: str, campo: str | None = None)`
    - `leer(path: str, id: str | None = None, params: dict | None = None, tabla: str | None = None)`
    - `consultar(sql: str, desde: int = 0)`
    - `exportar(sql: str, formato: str = "xlsx", nombre: str | None = None)`
    - `escribir(metodo: str, path: str, id: str | None = None, body: dict | None = None, base: str | None = None, cambios: dict | None = None, params: dict | None = None)`
    - `guia(tema: str | None = None)`
    - `verificar_conexion()`
  - In `escritura.py`:
    - `armar_body(body: dict | None, base_crudo: dict | None, cambios: dict | None) -> dict` does a shallow merge: `cambios` keys replace the base's whole values. It raises `ValueError` on `body` + `base` together, or on `base` without `cambios`.
    - `diff(antes: dict | None, enviado: dict, despues: dict) -> str` gives `"Campos cambiados"` (before → after) and `"Campos que la API cambió por su cuenta"` (sent ≠ after), with values cut at 80 chars.

- [ ] **Step 1: Write the failing tests.** Use a fake `FinnegansClient`, a fake `DocsMcp`, and the `SPEC` fixture. Call the tool functions through the server's tool registry.
  - `test_ninguna_respuesta_supera_el_presupuesto`: for each tool with a large fake response (4,150 clientes, a 600-path spec), `len(out) <= RESPUESTA_MAX_CHARS`.
  - `test_leer_chico_devuelve_json_y_carga_tabla`: a single cliente → the output contains its `Codigo`, and `workspace.crudo("cliente_p01093")` exists.
  - `test_leer_grande_devuelve_resumen`: 4,150 rows → the output contains `4150` and the table name, and doesn't contain the 100th row's code.
  - `test_leer_pasa_params_tal_cual`: `params={"PARAMWEBREPORT_Moneda":"PES"}` reaches the client unchanged.
  - `test_leer_siempre_usa_get`: `leer` has no `metodo` param, so the fake client must have been called with `"GET"`.
  - `test_escribir_put_con_base_y_cambios`:
    - The client receives the base raw JSON with only `Nombre` replaced.
    - A GET re-reads the record.
    - The output lists `Nombre` under "Campos cambiados", and `NroInscripcionIIBB` under "por su cuenta" when the fake read-back adds it.
  - `test_escribir_delete_devuelve_estado`: DELETE → the output says it was deleted, with no diff.
  - `test_escribir_error_no_filtra_secretos`: the fake client raises an error whose text contains the secret → the output has `***` and not the secret, and is translated by `traducir_error`.
  - `test_escribir_base_inexistente`: `base="nope"` → a message telling Claude to load the record with `leer` first.
  - `test_verificar_conexion_nombra_la_clave_mala`: missing settings → the output lists the `faltantes()` labels. A token 401 → `"Client ID / secret de Finnegans"`. A docs failure → `"documentación"`, with swagger still OK.
  - `test_buscar_endpoint_sin_claves_de_docs_sigue`: empty docs keys → rows plus the `"solo con el swagger"` note.
  - `test_reads_y_writes_son_tools_distintas`: the registry has both `leer` and `escribir`. `leer`'s annotations have `readOnlyHint=True`, and `escribir`'s have `destructiveHint=True`.
- [ ] **Step 2:** Run `uv run pytest -q tests/mcp`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `MCPServer("finnegans", instructions=INSTRUCCIONES)`, with `ToolAnnotations` on every tool.
  - Every tool catches `FinnegansError` / `SwaggerError` / `ConsultaInvalida` / `ValueError` and returns a Spanish message, already redacted. None of these errors reaches the client.
  - `escribir` re-reads the record only for `PUT`/`POST` on `entidad` types. The code comes from `id`, or failing that from `body["Codigo"]`.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: everything passes.
- [ ] **Step 5:** Commit with `feat(mcp): servidor con buscar/ver/leer/consultar/exportar/escribir/guia`.

### Task 8: Manifest, packaging, README

**Files:**
- Create: `manifest.json`, `icon.png` (256×256, simple and generic; if no image tool is available, omit `icon` from the manifest and say so in the PR)
- Modify: `README.md` (full rewrite)
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: the env var names (Global Constraints) and `main` (Task 7).

- [ ] **Step 1: Write `manifest.json`.**
  - `name: "finnegans"`, `display_name: "Finnegans"`, `version: "1.0.0"`.
  - `server`: `type: "uv"`, `entry_point: "src/finnegans_mcp/server.py"`, and `mcp_config.command: "uv"` with `args: ["run","--directory","${__dirname}","src/finnegans_mcp/server.py"]`.
  - `env` maps each variable to `${user_config.<key>}`.
  - `user_config` uses exactly the spec §8.1 keys, types, `sensitive` flags and defaults. `carpeta_exportacion` is a `directory` with default `${DOCUMENTS}/Finnegans`.
  - Spanish titles and descriptions say where to get each key: "te la pasa Juan Sbatella".
  - `tools` lists the 8 tools with one-line Spanish descriptions.
- [ ] **Step 2: Write the test.**
  - `test_manifest_y_settings_coinciden`: every `env` value refers to an existing `user_config` key. Every `Settings.from_env` variable is present in `env`. Exactly `client_secret`, `swagger_key` and `docs_secret_key` are `sensitive`. The `tools` names equal the server's registered tool names.
- [ ] **Step 3:** Run `uv run pytest -q tests/test_manifest.py`, then `npx -y @anthropic-ai/mcpb validate manifest.json`, then `npx -y @anthropic-ai/mcpb pack`. Expected: PASS, valid, and `finnegans.mcpb` produced (gitignored).
- [ ] **Step 4: Rewrite `README.md`.**
  - What it is.
  - Install: Owner upload, or double-click the `.mcpb`, then fill in the form. Per field, what it is and that Juan provides it.
  - The 8 tools in one line each.
  - Recommended Claude Desktop permissions: always allow reads, ask on `escribir`.
  - Update: upload the new `.mcpb`.
  - Development: `uv sync`, `uv run pytest`, `npx @anthropic-ai/mcpb pack`.
  - No mention of `.env`, `.bat` files or `cli.py`.
- [ ] **Step 5:** Commit with `feat: manifest MCPB, empaquetado y README nuevo`.

### Task 9: Live write test with throwaway records (needs Juan's approval to run)

**Files:**
- Create: `scripts/prueba_escritura_en_vivo.py`

**Interfaces:**
- Consumes: `crear_servidor` tools via the registry (the same path Claude uses), and `Settings.from_env`.

- [ ] **Step 1: Write the script.**
  - It refuses to run without `--si-escribir-en-produccion` and `--plantilla CODIGO`. The template is an existing cliente Juan picks, read only, used for the required fields.
  - It then runs these steps, printing each tool's output:
    1. `leer("cliente/list")` + `consultar` for codes `LIKE 'ZZ-PRUEBA-MCP%'` → `escribir DELETE` each leftover.
    2. `leer("cliente", id=plantilla)` → build a body from the template's raw JSON with `Codigo="ZZ-PRUEBA-MCP"` and a name of `"ZZ PRUEBA MCP - borrar"`, inactive (the field name comes from `ver_endpoint("cliente")`) → `escribir POST`.
    3. `leer` the new record → `escribir PUT` with `base` + `cambios={"Nombre": "ZZ PRUEBA MCP - editado"}` → check that the diff shows `Nombre`.
    4. `escribir PUT` with the full `body`.
    5. `escribir DELETE` → a final `leer` gives the not-found message.
  - It exits non-zero on any step that doesn't match its expectation, and never touches any other code.
- [ ] **Step 2 (Juan approves the run):** Juan sets the env vars in a terminal and runs `uv run python scripts/prueba_escritura_en_vivo.py --si-escribir-en-produccion --plantilla <codigo>`. Expected: every step OK, and no `ZZ-PRUEBA-MCP` left in `cliente/list`.
- [ ] **Step 3:** Commit with `test: prueba de escritura en vivo con registros descartables`.

### Task 10: Second-PC acceptance (manual)

- [ ] **Step 1 (Juan):** Upload `finnegans.mcpb` as a team extension. Install it on another person's PC, and enter that person's keys in the form.
- [ ] **Step 2 (that person, in Claude Desktop chat):**
  - "¿Qué órdenes de compra pendientes tiene el proveedor X?" → Claude searches, may ask for the supplier code, and answers with a short summary.
  - "Exportame todos los clientes activos a Excel" → a file appears in Documents\Finnegans, and the chat shows only the path and the count.
- [ ] **Step 3:** Delete the memory note `pendiente-pasar-a-tester.md` once this passes.
