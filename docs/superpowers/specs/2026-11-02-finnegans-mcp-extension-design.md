# Finnegans MCP — Desktop extension rebuild (design)

Date: 2026-11-02 · Author: Juan Sbatella (with Claude)

## 1. Intent

Replace the current `finnegans-connector` with **one complete Finnegans MCP** that
any leader can install in **Claude Desktop chat** like a normal extension, fill in
their keys in **one settings form**, and use to read and write anything in the
Finnegans API.

Why: the current connector works, but installing it means Python, a `.env`
file, `instalar.bat`/`actualizar.bat`, and copy-pasting `ASSISTANT_INSTRUCTIONS.md`
into Claude. It also carries guardrails (`preparar_cambio`/`ejecutar_cambio`,
confirmation codes, risk patterns, 3,000-char truncation) that the user now wants
gone. Big results (e.g. `cliente/list`, ~4,150 rows / ~469k chars) can't be used
at all today because they're truncated.

This is the **foundation**: later, narrow use-case extensions (Facturar, Órdenes
de compra) will be built on top of the same core.

## 2. Goals

1. **Install via Claude Desktop extension** (`.mcpb`). Installable by double-click,
   and distributable company-wide by a Team/Enterprise Owner as a custom team
   extension (Organization settings → Connectors → Desktop).
2. **One place for every key**: the extension's settings form (`user_config` in
   the manifest). Secrets marked `sensitive`. No `.env`, no installer script,
   no Python on the user's PC.
3. **No artificial limits**: no confirmation-code flow, no risk patterns, no
   DELETE policy flag, no character truncation, no local audit log.
4. **Find the right endpoint reliably**: always consult **every** source of
   truth (swaggerGlobal OpenAPI spec + Finnegans docs MCP), tell Claude when they
   disagree or the match is weak, and **ask the user when not sure**.
5. **Protect the conversation context**: large data never flows into the chat.
   It is loaded into an in-server DuckDB workspace, filtered/aggregated there
   with SQL, and only small pages, summaries, or a file path come back.
6. **Preserve the hard-won knowledge** (§7) as part of the product, not as a
   doc people paste by hand.
7. **Reusable core** so the future Facturar / Órdenes de compra extensions can
   import it instead of copying it.

## 3. Non-goals

- Hosted/remote connector. Each person runs it locally with their own keys.
- Claude Code / Cowork plugins. Target is Claude Desktop chat only.
- Backwards compatibility with the current repo: no `.env` support, no
  `cli.py`, no `install.py`/`verify_setup.py`, no `.bat` scripts, no migration
  path for existing installs. The repo is refactored in place (see §9).
- Executing arbitrary Python from Claude inside the server.
- Building the Facturar / Órdenes de compra extensions now.

## 4. Anti-goals (failure even if it technically works)

- A tool response that dumps hundreds of rows or a whole schema into the chat.
- Claude guessing an endpoint when sources disagree or nothing matches well,
  instead of asking.
- Credentials (client secret, token, swagger key) appearing in any tool output,
  error message, or exported file.
- A leader needing a terminal, Python, or a text editor to install or update.

## 5. Constraints

- **Claude Desktop on Windows**, current version, Team/Enterprise plan for the
  org-wide allowlist (Owner uploads the `.mcpb`).
- **MCPB `uv` server type** (manifest spec v0.4+): the host installs Python deps
  from `pyproject.toml` with uv; no user Python needed. This is newer than the
  `node` type and must be proven first (§10, step 0).
- Finnegans auth: `client_credentials` → plain-text or JSON token from
  `GET {base}/api/oauth/token?grant_type=...&client_id=...&client_secret=...`;
  token goes as `ACCESS_TOKEN` query param on every call; refresh once on 401/403.
- swaggerGlobal: `GET {swagger_url}?key={key}` returns Swagger 2.0. Body schemas
  are **not** in `#/definitions`; each is an external `$ref` to another URL on
  the same host that must be fetched and cached.
- Finnegans docs MCP (streamable HTTP, headers `x-client-id`, `x-secret-key`)
  exposes `search_apis(query)` and `get_api(api)`.

## 6. Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| Packaging | **MCPB `uv` (Python)** | Keeps proven search/vocabulary logic; DuckDB is a normal wheel; newer server type, needs a spike | **Chosen** |
| | MCPB `node` (TypeScript rewrite) | Most proven runtime in Desktop; rewrite everything, no capability gain | Rejected |
| | MCPB `python` with bundled deps | Requires Python installed on each PC (today's pain) | Rejected |
| | MCPB `binary` (PyInstaller) | Large, antivirus false positives | Rejected |
| Context control | **DuckDB SQL workspace in-server** | Claude writes SQL well; handles joins/aggregations; can be locked down (`enable_external_access=false`) | **Chosen** |
| | Fixed filter params (`campos`, `filtro`, `orden`, `pagina`) | Simplest/safest; every new question shape needs new params; weak at totals/joins | Rejected |
| | Claude-written Python executed in server | Most flexible; arbitrary code on user PCs with credentials loaded; Python can't be sandboxed reliably | Rejected |
| | Claude Desktop's own code sandbox | Runs in the cloud; data must pass through the chat to reach it | Not viable |

The user picked: Desktop extension, keys per person, Python + uv + DuckDB.

## 7. Knowledge to preserve (ship inside the product)

From the current code and `ASSISTANT_INSTRUCTIONS.md`. All of it moves into the
new core; nothing is lost because a module is deleted.

**Search** (`swagger_catalog.py`, `vocabulario.py`)
- Tokenizer: strip accents *before* splitting (keep ñ), split camelCase
  (`ordenPago` → `orden|pago`, acronyms not split letter by letter), keep the
  whole identifier too.
- Singular/plural variants (min length 4); business synonyms map
  (`tesoreria`/`caja` → `fondos`, `cobrar` → `cobranza|cobro`, `remito` →
  `despacho|recepcion` because `/remito` returns 501, `inventario` → `stock`,
  `contabilidad` → `asiento|cuenta`, …). Synonym targets must exist in the real
  spec (keep the test that enforces this).
- Scoring: concepts matched + precision (matched / words in endpoint), so the
  exact resource beats reports that merely mention it.
- External body-schema `$ref` resolution with a separate cache.

**Routes and endpoint types** (verified against swaggerGlobal, 2026-11-02:
579 paths; the spec served by `j11.teamplace.finneg.com` and
`oneteam.finneg.com` is byte-identical)
- The type comes from the tag description, `Tipo: <X>`. Read it from there,
  don't guess from the path.
- **Viewer** (234 tags): read-only reports, always `GET /api/reports/{Nombre}`,
  query params only.
  - Names are inconsistent: mostly `PARAMWEBREPORT_*`, but also `PARAM*`,
    unprefixed, and case variants (`Moneda`/`moneda`). Pass them exactly as
    the spec spells them.
  - Dates take `yyyy-MM-dd` or relative constants (`getCurrentDate`,
    `getFirstDayOfMonth`, `getLastDayOfLastMonth`, `getFirstDayOfYear`, …).
  - Code params take a code or `arbol(nombre)` "smart selection" (searches as a
    tree first, then as a node).
  - Output schema (`swaggerApiViewer?api=…`) is often unusable ("No fue posible
    generar un ejemplo"), so the columns are only known after calling. This is
    why `leer` loads viewers into the workspace and reports the columns.
  - 11 have a `…DEALS` twin, a variant for the Deals app.
- **EntidadVO** (127 tags): CRUD entities.
  - Record: `GET|PUT|DELETE /api/{entidad}/{codigo}`. Create:
    `POST /api/{entidad}`. List: `GET /api/{entidad}/list`, which only 97 of
    them have.
  - `/list` accepts `updatedSince=yyyy-mm-dd` for incremental reads.
  - `PUT` accepts `createIfNotExists=1`, which inserts if the record is missing
    (an upsert).
  - The body schema is an external ref:
    `swaggerApi?api={entidad}&nombreVO={Entidad}VO`.
- **Untagged**: `GET /oauth/token` and `custom/BProc` (the only one with PATCH).
- `id missing` = missing path segment.
- The swagger key is embedded in every `$ref` of the spec itself. It is a
  workspace-level read-only docs key, not a personal secret.
- Live production already holds test artifacts (`AjusteDeStockPruebaServidorSQL`,
  `reports/PruebaIsmaStock`). There is no sandbox host in the spec.

**Writes**
- `PUT /api/{entidad}/{codigo}` replaces the **whole** record; no partial
  update. The id is read from the body's `Codigo` field (missing →
  `HTTP 406 "Not Acceptable: empty id"`).
- The API writes fields you didn't send (e.g. `NroInscripcionIIBB` filled from
  the CUIT when switching to Convenio Multilateral). Always diff after writing.
- Some existing records are in states the API itself rejects (mixed IIBB);
  those can't be restored by API.

**Business dictionary (SOUTEX / Formas)**
- Sucursales: `EMPRE01` Formas Publicitarias SA, `4` Soutex SA (productive);
  `7` FP DEMO, `6` ST Demo, `5` Prueba (internal).
- Business units of Formas: Formas Shop, Corporate, No Estrés.
- IIBB `ProvinciaItems[].ControlImpositivo1`: `0` Contribuyente Local (one
  province only), `1` Convenio Multilateral (many), `3` unknown; mixing → 500.
  Normalizing IIBB is a fiscal decision: ask, never choose.
- `cliente/list`: ~4,150 rows; only `codigo`, `nombre`, `descripcion`, `activo`;
  three code formats (`301`, `C02155`, `P00016`); junk names (`--`, `.`, leading
  spaces). The ERP can't search by name: load the list and filter.
- Ask for sucursal / business unit / date range when the request needs them and
  the user didn't say; never assume a default sucursal.

**Errors and secrets** (`errores.py`, `redaction.py`, `client.py`)
- Plain-Spanish translation of API errors (404 → record not found, etc.).
- Redact client_id, client_secret, token, and swagger key from every message
  (the token URL carries credentials in the query string).

## 8. Design

### 8.1 Settings form (`manifest.json` → `user_config`)

| Key | Type | Sensitive | Default |
|---|---|---|---|
| `client_id` | string | no | — (required) |
| `client_secret` | string | yes | — (required) |
| `swagger_key` | string | yes | — (required) |
| `docs_client_id` | string | no | — (required) |
| `docs_secret_key` | string | yes | — (required) |
| `carpeta_exportacion` | directory | no | user's Documents\Finnegans |
| `base_url` | string | no | `https://api.finneg.com` |
| `swagger_url` | string | no | `https://oneteam.finneg.com/BSA/api/swaggerGlobal` |
| `docs_mcp_url` | string | no | current docs MCP URL |

Passed to the server as environment variables via `${user_config.KEY}`.
`FINNEGANS_WORKSPACE` is dropped unless the builder finds code that uses it
(the current client doesn't).

### 8.2 Tools

Reads and writes are separate tools so Claude Desktop's own per-tool permission
can be "always allow" for reads and "ask" for writes. That is the client's
setting, not a limit we build.

1. **`buscar_endpoint(consulta)`**: queries swaggerGlobal (local scoring) **and**
   the docs MCP in parallel, merges by path, returns ≤ 8 one-line results:
   path, methods, type, short summary, which source(s) found it. Adds an explicit
   note when sources disagree, when the top results tie, or when the best score
   is weak, so Claude knows to ask the user. If the docs MCP is unreachable or
   its keys are missing, search still runs on swaggerGlobal alone and the
   response says so (*Claude's call*: a docs outage shouldn't stop all work).
2. **`ver_endpoint(path, campo=None)`**: operations for a resource or exact
   path: method, params (required marked), body top-level fields + required.
   Nested objects/arrays are shown as names only; `campo="ProvinciaItems"`
   expands one level. Never dumps the full schema.
3. **`leer(path, id=None, params=None, tabla=None)`**: GET. If the response is
   small (under the response budget), returns it directly. Otherwise loads it
   into the workspace as table `tabla` (auto-named if omitted) and returns only:
   table name, row count, columns with types, 3 sample rows (long cells cut).
   Single records loaded this way can be the base for a write (see 6).
4. **`consultar(sql, cursor=None)`**: read-only SQL over workspace tables.
   Returns one page under the response budget, total row count, and a cursor if
   more remain. `SHOW TABLES` / `DESCRIBE t` work for orientation.
5. **`exportar(sql, formato="xlsx"|"csv", nombre=None)`**: runs the query and
   writes the full result to `carpeta_exportacion`. Returns path + row count only.
6. **`escribir(metodo, path, id=None, body=None, base=None, cambios=None)`**:
   POST/PUT/PATCH/DELETE, executed immediately. For PUT, either send the full
   `body`, or pass `base` (a table holding the record loaded with `leer`) plus
   `cambios` (the fields to change): the server merges them, so the full object
   never has to travel through the chat. Returns status + a compact diff
   (fields sent vs. record re-read after write, including fields the API changed
   on its own).
7. **`guia(tema=None)`**: returns a section of the business knowledge (§7):
   `sucursales`, `iibb`, `rutas`, `tipos`, `escrituras`, `clientes`. No arg →
   list of topics.
8. **`verificar_conexion()`**: checks token, swaggerGlobal, docs MCP; says
   which key is wrong in plain Spanish.

### 8.3 Server instructions (always in context, keep short)

A few lines only: answer in clear Spanish for non-technical leaders; always
`buscar_endpoint` → `ver_endpoint` before reading or writing; ask when the
search says sources disagree/weak match, or when sucursal/date range is
missing; never dump rows, use `leer` → `consultar`/`exportar`; for PUT use
`base` + `cambios`; call `guia` for business rules. Everything else lives in
`guia`, so it costs context only when needed.

### 8.4 DuckDB workspace

- One in-memory DuckDB database per server process, opened with
  `enable_external_access=false`, then `lock_configuration=true`, and a
  `memory_limit`.
- `consultar` accepts only read statements (SELECT/WITH/SHOW/DESCRIBE/
  SUMMARIZE); check the parsed statement type, don't regex the text.
- Loading: JSON list → table; nested objects become STRUCT/LIST columns that
  Claude can `UNNEST`. A single object → one-row table.
- `exportar` writes files from Python code, not via SQL `COPY` (external access
  stays off).
- Tables live until Claude Desktop restarts the extension; reloading the same
  `tabla` name replaces it.

### 8.5 Response budget

One constant (builder's call on the exact number, around 8k chars) applies to
every tool. Anything larger is paged (`consultar`), summarized (`leer`), or sent
to a file (`exportar`). Never silently truncated: when something is cut, the
response says so and says how to get the rest.

### 8.6 Code layout (reusable core)

- **`finnegans_core`**: auth/client, swaggerGlobal + docs MCP catalog, search +
  vocabulary, error translation, redaction, workspace, knowledge content.
  No MCP imports; importable by future extensions.
- **`finnegans_mcp`**: the MCP server (tools, instructions) on top of the core.
- **`manifest.json`**, `pyproject.toml`, `.mcpbignore`, icon.

How these map onto a uv workspace or a single package is the builder's call, as
long as `finnegans_core` can be depended on by another extension.

*Claude's call:* future extensions get the core by **vendoring it into each
`.mcpb` at pack time** (a build step copies `finnegans_core` into the bundle),
not via PyPI (would publish the business dictionary), a private index (someone
has to host it), or a git dependency (leaders don't have git). Known trade-off:
each future extension has its own settings form, so keys get typed once per
extension. To be revisited when Facturar is designed.

## 9. Repo refactor (no legacy kept)

Refactor this repo in place on a new branch off `master`. Delete what the new
design replaces: `cli.py`, `install.py`, `verify_setup.py`, `scripts/*.bat`,
`service-credentials.env.example`, `ASSISTANT_INSTRUCTIONS.md` (content moves
into `guia`), `finnegans/validator.py`, `finnegans/audit.py`, the `audit/`
folder, and tests for removed behavior. Rewrite `README.md` for the new install
(download `.mcpb` / admin allowlist, fill in the form). Keep `docs/` history.

Tests are rewritten for the new tools, but the existing tests that encode
knowledge (tokenizer, synonyms against the real spec, scoring, external `$ref`
resolution, error translation, redaction) are ported, not dropped.

The open branch `fix/fuga-credenciales` becomes moot: its redaction rule is
carried into the core (§7).

## 10. Order of work

0. **Spike (throwaway)**: a minimal `uv` `.mcpb` with one tool that imports
   `duckdb` and reads a `sensitive` `user_config` value from env. Install it in
   Claude Desktop on Windows, confirm deps install with no Python on the PC and
   the secret reaches the server. Test both paths: double-click install, and an
   Owner uploading it as a custom team extension (*Claude's call*: the real
   delivery path must be proven, not just the local one). If `uv` fails, stop
   and re-decide packaging.
1. Core: client + redaction + error translation.
2. Core: catalog (swaggerGlobal + docs MCP), merged search, endpoint types.
3. Core: DuckDB workspace + response budget + export.
4. MCP server tools + instructions + `guia`.
5. Manifest, packaging (`mcpb pack`), README.
6. Repo cleanup (§9).
7. Live write test with throwaway records (§11.1), approved by Juan.
8. Install on a second PC with the keys Juan enters for that person.

## 11. Open questions

1. ~~Where to test `escribir`~~ **Answered: throwaway records.** There is no
   sandbox (§7), and master data isn't split by sucursal, so demo sucursales
   don't isolate anything.
   - Live write tests touch **only records the test itself creates**: POST an
     inactive `cliente` with code `ZZ-PRUEBA-MCP` (plus a run suffix if needed),
     PUT it (full body and `base` + `cambios`), check the after-write diff,
     then DELETE it.
   - Existing records are never written to.
   - Unit tests stub HTTP. The live test is a separate opt-in script that
     refuses to run without an explicit flag, and Juan approves each run.
   - If a run dies halfway, the script's first step on the next run deletes any
     leftover `ZZ-PRUEBA-MCP*` record.
2. ~~Which keys can each leader get~~ **Answered:** Juan enters the keys for
   each person. The API client ID/secret and the docs MCP credentials are
   different credentials for different services (checked against Juan's
   `.env`: different values and lengths). All five fields stay.
3. ~~"viewer" endpoint type~~ **Answered** from the spec (§7): a plain GET on
   `/reports/{Nombre}`, so `leer` needs no separate code path.

## 12. Left to the builder

- Exact MCP Python SDK version (current repo pins `<2` because FastMCP was
  renamed in 2.x; the rebuild should target the current stable API).
- HTTP library (`httpx` suggested), response budget number, DuckDB memory
  limit, Excel library.
- Table auto-naming, cursor format, how merged search ranks results that only
  one source returns.
- Docs MCP and swaggerGlobal caching (in-memory per process is fine).
