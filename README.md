# Agente Finnegans

Asistente unificado para que lideres consulten y modifiquen datos en
Finnegans desde una IA (Claude Desktop), en lenguaje natural, con
validacion obligatoria antes de cualquier escritura.

Combina en **un solo MCP**:
- **Descubrimiento** de APIs (catalogo oficial Finnegans)
- **Lectura** (GET a cualquier endpoint)
- **Escritura con validacion** (POST/PUT/DELETE solo tras confirmacion del usuario)

---

## Flujo para el lider

```
Lider: "¿Qué órdenes de compra pendientes tiene el proveedor Acme?"

IA:    [buscar_api → ver_api → consultar_finnegans]
       "El proveedor Acme tiene 3 órdenes pendientes: ..."

Lider: "Creá una OC al proveedor Beta por 50 unidades del producto X"

IA:    [buscar_api → ver_api → preparar_cambio]
       "Voy a crear esta OC: ... ¿Confirmás? (sí / no)"

Lider: "Sí, confirmá"

IA:    [ejecutar_cambio]
       "Listo. OC creada."
```

---

## Instalacion (IT / una vez por PC)

### 1. Requisitos

- Python 3.10+
- Claude Desktop instalado

### 2. Configurar credenciales

```bash
copy .env.example .env
```

Completar `.env` con **dos juegos de credenciales**:

| Variable | Para que sirve | Donde obtenerla |
|---|---|---|
| `FINNEGANS_CLIENT_ID` / `FINNEGANS_CLIENT_SECRET` | Ejecutar consultas y cambios en Finnegans | Finnegans → Usuarios → Keys API |
| `FINNEGANS_DOCS_CLIENT_ID` / `FINNEGANS_DOCS_SECRET_KEY` | Buscar APIs en el catalogo | Finnegans Developer MCP / config MCP de Cursor |

### 3. Instalar dependencias

```bash
python -m pip install -r requirements.txt
```

### 4. Configurar Claude Desktop

Editar `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "finnegans-agent": {
      "command": "python",
      "args": ["C:\\FinnegansAgent\\server.py"],
      "cwd": "C:\\FinnegansAgent"
    }
  }
}
```

Ajustar la ruta segun donde se copie la carpeta del proyecto.

### 5. Instrucciones del asistente

Copiar el contenido de `ASSISTANT_INSTRUCTIONS.md` en las instrucciones
del proyecto en Claude Desktop.

### 6. Verificar

Reiniciar Claude Desktop. En el chat, el agente puede llamar a
`verificar_conexion` para comprobar API + catalogo.

---

## Herramientas MCP expuestas

| Tool | Proposito | Cuando usarla |
|---|---|---|
| `verificar_conexion` | Prueba credenciales y catalogo | Diagnostico / setup |
| `buscar_api` | Busca endpoints por nombre o descripcion | Siempre primero |
| `ver_api` | Muestra metodos y parametros de una API | Antes de consultar o escribir |
| `consultar_finnegans` | Lectura (GET) | Consultas de datos |
| `preparar_cambio` | Arma escritura sin ejecutar | Crear/modificar/eliminar |
| `ejecutar_cambio` | Ejecuta tras confirmacion del usuario | Solo despues de "si, confirmo" |

---

## Seguridad

- Credenciales en `.env` (nunca en git, nunca en el chat).
- Escrituras **siempre** en dos pasos: preparar → confirmar → ejecutar.
- `ejecutar_cambio` rechaza si `usuario_confirmo` no es `true`.
- Confirmaciones expiran a los 10 minutos.
- No se usan contraseñas personales; solo credenciales de aplicacion.

---

## Estructura del proyecto

```
finnegans-connector/
├── server.py                  # Agente MCP unificado (punto de entrada)
├── finnegans/
│   ├── client.py              # HTTP client (auth + GET/POST/PUT/DELETE)
│   ├── discovery.py           # Catalogo de APIs (MCP remoto Finnegans)
│   ├── validator.py           # Cola de cambios con confirmacion
│   └── config.py              # Carga de .env
├── cli.py                     # CLI para pruebas manuales
├── ASSISTANT_INSTRUCTIONS.md  # Prompt para Claude Desktop
├── .env.example
└── requirements.txt
```

---

## CLI (para pruebas de IT)

```bash
python cli.py token
python cli.py get producto --id CODIGO_REAL
```

---

## Diferencia con el MCP de docs de Cursor

| | MCP docs (Cursor) | Este agente |
|---|---|---|
| Proposito | Documentacion para programadores | Operacion para lideres |
| Ejecuta en Finnegans | No | Si |
| Descubre APIs | Si | Si (integrado) |
| Validacion de escrituras | No aplica | Si, obligatoria |

Los lideres solo necesitan **este agente** + Claude Desktop.
El MCP de docs en Cursor queda para vos, desarrollando.

---

## Proximos pasos

- [ ] Agregar credenciales de docs MCP al `.env` de cada PC
- [ ] Probar con un codigo real (producto/proveedor) → respuesta 200
- [ ] Piloto con 1-2 lideres antes del curso
- [ ] Definir si credenciales son por empresa o por usuario
