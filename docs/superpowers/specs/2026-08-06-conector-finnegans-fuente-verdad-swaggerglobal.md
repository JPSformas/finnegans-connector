# Conector Finnegans — Fuente de verdad de APIs + Diccionario de negocio — Diseño

**Fecha:** 2026-08-06
**Estado:** Aprobado, listo para plan de implementación
**Proyecto:** `finnegans-connector` (compañías: Formas Publicitarias SA / Soutex SA)
**Depende de:** diseño Nivel 3 (`2026-08-05-conector-finnegans-nivel3-design.md`)

## Objetivo

Que el conector resuelva **con la mayor certeza posible** qué API de Finnegans
usar ante un pedido en lenguaje natural, apoyándose en la documentación
**completa y correcta** del ERP, y que el asistente de los líderes cuente con
un **diccionario de negocio** (sucursales, unidades de negocio, mapeos y
prácticas) más el hábito de **pedir los detalles** que falten antes de consultar.

## Contexto y hallazgos (smoke test 2026-08-06)

Durante un pedido real ("ventas de julio", "código de cliente de Formas
Publicitarias SA") se descubrió que el conector **no encontraba los endpoints
de listado ni de reportes**. Investigación de causa raíz (GET crudos contra
`https://api.finneg.com`):

- El armado de URL del conector **es correcto**; GET por id funciona
  (`/api/cliente/1` → 404 limpio).
- El router de `api.finneg.com/api/{x}` **exige siempre un segmento** tras la
  entidad. Las rutas reales son:
  - `GET /api/{entidad}/{codigo}` → un registro.
  - `GET /api/{entidad}/list` → **listado** (p.ej. `cliente/list` → 200 con 4118 clientes).
  - `GET /api/reports/{Nombre}` → **reportes** (p.ej. `reports/analisisFacturaVenta`).
- **La fuente que usa hoy el conector (MCP `finnegans-api-docs`) está incompleta
  y en parte equivocada:** no documenta el sufijo `/list`, marca `/api/cliente`
  como "Listar cliente" (ruta que da `id missing`), y devuelve `paths: {}` para
  los reportes.
- **La documentación buena** es el Swagger de `oneteam.finneg.com`, cuyo spec
  OpenAPI crudo es **fetcheable por HTTP** (sin JS) en:
  `https://oneteam.finneg.com/BSA/api/swaggerGlobal?key=<FINNEGANS_SWAGGER_KEY>`
  → JSON de ~1 MB, **538 paths**, con 93 endpoints `/{entidad}/list` y toda la
  familia `/reports/{Nombre}`. El `key` (en `.env`, `FINNEGANS_SWAGGER_KEY`) es
  **estable** (confirmado por el dueño); no se versiona su valor real.

Conclusión: el problema no era de código HTTP sino de **fuente de verdad**. Se
re-apunta el descubrimiento al spec de `swaggerGlobal`.

## Datos de negocio confirmados

**Se opera por SUCURSAL** (no por empresa). Tabla clave = `GET /api/sucursal/list`:

| Código sucursal | Nombre | Uso |
|---|---|---|
| `EMPRE01` | Formas Publicitarias SA | Productiva |
| `4` | Soutex SA | Productiva |
| `7` | FP DEMO | Interna / gestión alternativa |
| `6` | ST Demo | Interna / gestión alternativa |
| `5` | Prueba | Interna |

- Las dos compañías son **Formas Publicitarias SA** y **Soutex SA**; cada una
  tiene una variante **DEMO** para asuntos internos.
- **Unidades de negocio** dentro de Formas Publicitarias SA: "Formas Shop",
  "Corporate", "No Estrés" (y las que se agreguen). Son una **sub-dimensión**;
  el criterio exacto de filtrado para cada una **lo definirá el dueño más
  adelante** (queda como plantilla a completar, no como parte cerrada de este spec).

(Referencia: tabla `empresa/list` = `FP01` Formas, `ST01` Soutex, más DEMO/Prueba;
no es la dimensión operativa principal.)

## Decisiones de diseño (locked)

| Dimensión | Decisión |
|---|---|
| Fuente de verdad | (A) `swaggerGlobal` **autoritativa**; MCP `finnegans-api-docs` como apoyo de búsqueda/validación cruzada, nunca como verdad de paths. |
| Consumo del spec | El conector **baja y cachea** el spec en memoria al iniciar (no se renderiza JS; es un GET). |
| `key` de Swagger | Estable; va en `.env` (`FINNEGANS_SWAGGER_URL` + `FINNEGANS_SWAGGER_KEY`), no hardcodeado. |
| Diccionario de negocio | **Texto** en `ASSISTANT_INSTRUCTIONS.md`, editable por el dueño; consumidor = asistente de los líderes. |
| Detalles faltantes | El asistente **pregunta** (sucursal / unidad de negocio / fechas) antes de consultar; no asume. |

## Arquitectura

### Parte 1 — Descubrimiento sobre `swaggerGlobal` (código)

**Nuevo módulo / fuente en `finnegans/discovery.py`** (o módulo hermano
`swagger_catalog.py` si mantiene `discovery.py` enfocado):

- `cargar_spec()` — GET a `FINNEGANS_SWAGGER_URL?key=…`, parseo JSON, **caché en
  memoria** (el proceso se reinicia al redeployar, igual que el caché actual de
  `get_api`). Ante fallo de red, error claro y, si está disponible, **degradar**
  al MCP de docs con aviso explícito.
- `buscar(consulta)` — búsqueda local sobre el spec: matchea `consulta` contra
  el nombre de path, `tags`, `summary`/`operationId` y devuelve candidatos
  rankeados (endpoint + operaciones disponibles). Reemplaza la verdad que hoy da
  el MCP; el MCP puede seguir consultándose como **segunda opinión** opcional.
- `ver(entidad)` — devuelve, para una entidad/recurso, sus **operaciones reales
  con path exacto y parámetros**: `list`, `get {codigo}`, `post`, `put`,
  `delete`, y reportes `reports/{Nombre}` con sus params.

**Tools MCP (`server.py`)** — se conserva el modelo de 6 tools y el flujo
`buscar_api → ver_api → consultar/preparar`:

- `buscar_api` / `ver_api` → resuelven contra el spec de `swaggerGlobal`.
- `consultar_finnegans` → debe poder pegarle a **cualquier** path real:
  `/{entidad}/{codigo}`, `/{entidad}/list`, `/reports/{Nombre}`. Hoy arma
  `/api/{api_id}[/{id}]`; se formaliza el acceso a sub-rutas (que `api_id` acepte
  `cliente/list` o `reports/analisisFacturaVenta` de forma explícita y
  documentada, en vez del truco `id="list"`).
- `preparar_cambio` / `ejecutar_cambio` → sin cambios de contrato; se benefician
  de los paths/params correctos que ahora expone `ver_api`.

**Flujo de datos:** inicio → `cargar_spec()` (cache) → usuario pregunta →
`buscar_api` (spec local) → `ver_api` (operaciones+params reales) →
`consultar_finnegans` (path real) → respuesta.

**Manejo de errores:**
- Fallo al bajar el spec: mensaje claro ("no pude cargar la documentación de
  APIs"), sin romper el resto de tools; intentar MCP de docs como respaldo.
- `id missing` (400) al consultar: traducir a mensaje accionable ("este endpoint
  requiere un código en el path, o usá la operación `/list`").

### Parte 2 — Diccionario de negocio en `ASSISTANT_INSTRUCTIONS.md` (texto)

Sección nueva, en castellano claro, editable por el dueño:

1. **Sucursales** — la tabla de arriba, marcando productivas vs DEMO/Prueba.
2. **Unidades de negocio** de Formas Publicitarias SA (Formas Shop, Corporate,
   No Estrés) — con un espacio por unidad para "qué buscar / cómo filtrar",
   **a completar por el dueño**.
3. **Mapeos lenguaje natural → API** — ejemplos que crecen con el uso, p.ej.:
   - "buscar cliente por nombre" → `cliente/list` + filtrar localmente por nombre.
   - "ventas del período" → endpoint/reporte de ventas correcto (a fijar al
     enseñar el primer caso real) con sus params.
4. **Prácticas comunes** — convenciones que el dueño vaya dictando.

### Parte 3 — Comportamiento "pedir los detalles"

Regla explícita en las instrucciones: si un pedido necesita **sucursal**,
**unidad de negocio** o **rango de fechas** y el usuario no los especificó, el
asistente **pregunta primero** y ofrece las opciones de la tabla; recién con esos
datos arma la consulta. Nunca asume una sucursal por defecto.

## Seguridad

- **Rotar el `client_secret`** de la credencial de servicio: quedó expuesto en
  texto plano en un chat. Actualizar `.env` tras rotar.
- `FINNEGANS_SWAGGER_KEY` va en `.env` (no en git, no en el chat). Es de solo
  lectura de documentación, pero se trata como credencial.

## Testing

- **Unit (sin red):** `buscar`/`ver` sobre un **spec de muestra** (fixture JSON
  recortado con `cliente/list`, `cliente/{codigo}`, `reports/analisisFacturaVenta`)
  → verifican ranking y extracción de path+params correctos.
- **Resolución de paths:** `consultar_finnegans` arma la URL correcta para
  `/list`, `/{codigo}` y `/reports/{Nombre}` (test con stub HTTP, sin ERP real).
- **Degradación:** si `cargar_spec()` falla, las tools responden con error claro
  y no crashean.
- **Manual (smoke, con credenciales reales):** `cliente/list` trae la lista;
  `sucursal/list` trae la tabla; un reporte de ventas responde 200.

## No-objetivos (YAGNI)

- No se construye un índice de búsqueda sofisticado ni embeddings: matcheo
  simple sobre nombre/tags/summary alcanza para 538 paths.
- No se implementa refresco periódico del spec: se baja al iniciar y se recarga
  al redeployar. (Se puede añadir un `recargar_spec` manual si hace falta.)
- No se cierran los mapeos de unidades de negocio en este spec: son
  conocimiento que el dueño carga como texto después.

## Riesgos y supuestos

- **Supuesto:** el `FINNEGANS_SWAGGER_KEY` (en `.env`, no versionado) es estable
  (confirmado). Si algún día rota, se actualiza `.env`; el conector debe fallar
  con mensaje claro, no en silencio.
- **Supuesto:** el spec de `swaggerGlobal` refleja lo que la cuenta productiva
  expone. Los paths clave (`cliente/list`, `sucursal/list`) ya se verificaron
  200 contra el ERP real.
- **Riesgo:** algunos reportes pueden requerir params obligatorios no obvios; se
  resuelven caso a caso al enseñar cada consulta, leyendo el spec.
