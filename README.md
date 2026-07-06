# Conector Finnegans

Conector seguro para la API de Finnegans (Teamplace / F3), pensado para que
**agentes de IA** (Claude Desktop, Cursor, etc.) y scripts puedan **leer datos
del sistema de gestión** en lenguaje natural, sin exponer credenciales.

Estado actual: **solo lectura**, autenticación validada contra la API real.

---

## 1. Seguridad (leer primero)

- Las credenciales de **aplicación** (`client_id` / `client_secret`) viven en el
  archivo `.env`, que está en `.gitignore` y **no debe commitearse ni compartirse**.
- El conector **nunca** loguea el `client_secret` ni el token completo.
- **No se usan usuarios/contraseñas personales.** La API se autentica con
  credenciales de aplicación (`grant_type=client_credentials`).
- Recomendado: **rotar** el `client_secret` periódicamente desde Finnegans
  (Configuración → General → Seguridad → Usuarios → *Keys api*).
- Esta versión es de **solo lectura**. Cualquier acción de escritura futura
  (crear/modificar) debe requerir **confirmación explícita** antes de ejecutarse.

## 2. Puesta en marcha

```bash
# 1) Configurar credenciales
copy .env.example .env      # (Windows)  /  cp .env.example .env (Linux/Mac)
# editar .env con el client_id y client_secret reales

# 2) (Opcional) dependencias del servidor MCP
python -m pip install -r requirements.txt
```

Variables de `.env`:

```
FINNEGANS_BASE_URL=https://api.finneg.com
FINNEGANS_CLIENT_ID=...
FINNEGANS_CLIENT_SECRET=...
FINNEGANS_WORKSPACE=SOUTEX
```

## 3. Uso rápido (CLI)

```bash
python cli.py token                              # valida credenciales
python cli.py get producto --id ABC123           # un producto por código
python cli.py get cliente --id 100               # un cliente por código
python cli.py get ACOrdenesCompraPendientes --id 000123
```

## 4. Uso como librería (Python)

```python
from finnegans import FinnegansClient

client = FinnegansClient()
producto = client.producto("ABC123")
oc = client.ordenes_compra_pendientes("000123")
```

## 5. Uso desde un agente (MCP)

Ejecutar el servidor:

```bash
python server.py
```

Configuración en Claude Desktop (`claude_desktop_config.json`) o cualquier
cliente MCP:

```json
{
  "mcpServers": {
    "finnegans": {
      "command": "python",
      "args": ["C:\\Users\\user\\finnegans-connector\\server.py"]
    }
  }
}
```

Herramientas expuestas (solo lectura):

- `verificar_conexion` — comprueba que las credenciales funcionan.
- `obtener_recurso` — lectura genérica de cualquier endpoint.
- `obtener_producto`, `obtener_cliente`, `saldo_de_cliente`,
  `ordenes_compra_pendientes` — atajos por área.

## 6. Convención de la API (verificada contra la API real)

- **Autenticación:** `GET /api/oauth/token?grant_type=client_credentials&client_id=..&client_secret=..`
  → devuelve un token (texto plano, tipo UUID) con vencimiento.
- **Llamadas de negocio:** `GET /api/{recurso}/{id}?ACCESS_TOKEN={token}`
  - El **`id` (código del maestro) va en el PATH**.
  - Un código inexistente devuelve `404`; uno válido devuelve `200` + datos.
  - Sin `id` la API responde `400 "id missing"`.
- Los **reportes/listados** (p. ej. facturas por rango de fechas) requieren
  parámetros específicos (`FechaDesde`, `FechaHasta`, etc.) **definidos en el
  Diccionario de APIs** del espacio de trabajo (App Builder → Diccionario de
  APIs → Documentación). Ahí está el JSON de ejemplo y los parámetros de cada API.

## 7. Cómo agregar más endpoints por área

1. Buscar la API en el Diccionario de APIs de Finnegans y anotar sus parámetros.
2. Agregar un método de conveniencia en `finnegans/client.py` (usar `self.get(...)`).
3. (Opcional) Exponerlo como tool en `server.py` para los agentes.

Endpoints candidatos por área (a confirmar sus parámetros en el diccionario):

- **Compras:** `ACOrdenesCompraPendientes`, `ACOrdenesCompraFinalizadas`,
  `ACOrdenesCompraDetalle`, `cuentaCorrienteProveedor`.
- **Admin/Conta:** `composicionSaldoCliente`, comprobantes, `DETALLETRANSACCIONES`.
- **Ventas:** `cliente`, `oportunidadComercial`, `TrackingVentas`.
- **Producción/Compras:** `producto`, `productoList`, `ACOrdenesCompraProductosPendientes`.

## 8. Pendiente / próximos pasos

- Conseguir **un código real** (de producto o proveedor) para demostrar un `200`
  con datos en vivo.
- Definir qué **acciones de escritura** habilitar por área (con confirmación).
- Mapear los **parámetros exactos** de los reportes desde el Diccionario de APIs.
