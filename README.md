# Agente Finnegans

Asistente unificado para que líderes consulten y modifiquen datos en
Finnegans desde una IA (Claude Desktop), en lenguaje natural, con
validación obligatoria antes de cualquier escritura.

Combina en **un solo MCP**:

- **Descubrimiento** de APIs (catálogo oficial Finnegans)
- **Lectura** (GET a cualquier endpoint)
- **Escritura con validación** (POST/PUT/DELETE solo tras confirmación del usuario)

---

## Flujo para el líder

```
Líder: "¿Qué órdenes de compra pendientes tiene el proveedor Acme?"

IA:    [buscar_api → ver_api → consultar_finnegans]
       "El proveedor Acme tiene 3 órdenes pendientes: ..."

Líder: "Creá una OC al proveedor Beta por 50 unidades del producto X"

IA:    [buscar_api → ver_api → preparar_cambio]
       "Voy a crear esta OC: ... ¿Confirmás? (sí / no)"

Líder: "Sí, confirmá"

IA:    [ejecutar_cambio]
       "Listo. OC creada."
```

---



## Guía de instalación IT (paso a paso)

Esta sección está pensada para que alguien de IT configure **una PC de líder**
sin conocimientos de programación avanzados. Seguí los pasos en orden.
No saltees verificaciones: cada paso tiene un comando para confirmar que quedó bien.

### Resumen de qué se instala


| Componente                      | Dónde vive                            | Quién lo ve          |
| ------------------------------- | ------------------------------------- | -------------------- |
| Carpeta `finnegans-connector`   | Disco local (ej. `C:\FinnegansAgent`) | Solo IT              |
| Archivo `.env` con credenciales | Dentro de esa carpeta                 | Solo IT              |
| Python + dependencias           | Sistema                               | Solo IT              |
| Claude Desktop + config MCP     | App del líder                         | El líder abre Claude |


El líder **no** instala Python, **no** edita `.env`, **no** toca el MCP de docs de Cursor.

---



### Paso 0 — Checklist previo

Antes de empezar, confirmá que tenés:

- [ ] Acceso administrativo a la PC del líder (Windows 10/11)
- [ ] **Credenciales API de ejecución** (`client_id` + `client_secret`)  
  ```
  Finnegans → Configuración → General → Seguridad → Usuarios → [usuario API] → **Keys API**
  ```
- [ ] **Credenciales del catálogo de APIs** (`x-client-id` + `x-secret-key`)  
  ```
  Las mismas que usa el MCP `finnegans-api-docs` en Cursor (archivo `mcp.json`)
  ```
- [ ] Instalador de [Python 3.10+](https://www.python.org/downloads/) (marcar **"Add python.exe to PATH"**)
- [ ] Instalador de [Claude Desktop](https://claude.ai/download)
- [ ] Carpeta del proyecto (zip o copia de red)

---



### Paso 1 — Verificar Python

Abrí **PowerShell** (no hace falta admin) y ejecutá:

```powershell
python --version
```

**Resultado esperado:** `Python 3.10.x` o superior (3.11, 3.12, 3.14, etc.).

Si dice *"python no se reconoce"*:

1. Reinstalá Python marcando **"Add python.exe to PATH"**.
2. Cerrá y volvé a abrir PowerShell.
3. Si sigue fallando, probá:

```powershell
py --version
```

Anotá la ruta exacta del ejecutable (la vas a necesitar en el Paso 6):

```powershell
(Get-Command python).Source
```

Ejemplo de salida: `C:\Users\Juan\AppData\Local\Python\pythoncore-3.14-64\python.exe`

---



### Paso 2 — Copiar el proyecto a la PC

Creá una carpeta fija. **Recomendado:** `C:\FinnegansAgent` (sin espacios en la ruta).

```powershell
# Si tenés el proyecto en otra ubicación, ajustá ORIGEN
$Origen  = "C:\finnegans-connector-master\finnegans-connector-master"   # o la ruta del zip descomprimido
$Destino = "C:\FinnegansAgent"

New-Item -ItemType Directory -Force -Path $Destino | Out-Null
Copy-Item -Path "$Origen\*" -Destination $Destino -Recurse -Force
Set-Location $Destino
Get-ChildItem
```

**Resultado esperado:** debés ver `server.py`, `finnegans\`, `requirements.txt`, `.env.example`, `verify_setup.py`, etc.

```powershell
Test-Path "C:\FinnegansAgent\server.py"
```

Debe devolver `True`.

---



### Paso 3 — Crear y completar el archivo `.env`

El `.env` guarda las credenciales. **Nunca** lo compartas por mail, chat ni git.

```powershell
Set-Location C:\FinnegansAgent
Copy-Item .env.example .env
notepad .env
```

Completá **las 6 variables** (sin comillas, sin espacios alrededor del `=`):

```env
FINNEGANS_BASE_URL=https://api.finneg.com
FINNEGANS_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FINNEGANS_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FINNEGANS_WORKSPACE=SOUTEX

FINNEGANS_DOCS_MCP_URL=https://services.finneg.com/api/1/finnegans-developer-mcp/finnegans-api-docs/mcp
FINNEGANS_DOCS_CLIENT_ID=xxxxxxxx...
FINNEGANS_DOCS_SECRET_KEY=xxxxxxxx...
```


| Variable                                                 | Qué es                                                          | Dónde conseguirla                                         |
| -------------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------------- |
| `FINNEGANS_CLIENT_ID` / `FINNEGANS_CLIENT_SECRET`        | Credenciales para **ejecutar** consultas y cambios en Finnegans | Finnegans → Usuarios → Keys API                           |
| `FINNEGANS_DOCS_CLIENT_ID` / `FINNEGANS_DOCS_SECRET_KEY` | Credenciales para **buscar** APIs en el catálogo                | MCP `finnegans-api-docs` en Cursor → `mcp.json` → headers |
| `FINNEGANS_WORKSPACE`                                    | Nombre del espacio de trabajo                                   | Ej. `SOUTEX`                                              |


**Errores comunes:**

- Dejar valores `tu_client_id` / `tu_docs_client_id` → el script de verificación falla a propósito.
- Mezclar credenciales: las de ejecución y las de docs **son distintas**.
- Agregar comillas: `FINNEGANS_CLIENT_ID="abc"` → incorrecto. Debe ser `FINNEGANS_CLIENT_ID=abc`.

Verificá que `.env` no se suba a git (ya está en `.gitignore`):

```powershell
git check-ignore .env
```

Debe imprimir `.env`.

---



### Paso 4 — Instalar dependencias Python

```powershell
Set-Location C:\FinnegansAgent
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**Resultado esperado:** instalación de `mcp` sin errores.

Verificá:

```powershell
python -c "import mcp; print('mcp OK')"
```

Debe imprimir `mcp OK`.

---



### Paso 5 — Verificación automática (obligatorio)

Este script prueba **todo** antes de configurar Claude:

```powershell
Set-Location C:\FinnegansAgent
python verify_setup.py
```

**Resultado esperado:**

```
[OK] Python 3.x.x
[OK] FINNEGANS_CLIENT_ID configurado
[OK] Token obtenido
[OK] Búsqueda de prueba OK
[OK] Tools registradas: verificar_conexion, buscar_api, ...
RESULTADO: TODO OK (6/6 checks automáticos)
```

Si hay `[ERROR]`, **no continúes**. Corregí el punto indicado y volvé a ejecutar:

```powershell
python verify_setup.py
```

Al final del script verás el bloque JSON exacto para Claude Desktop con las rutas de **esta PC**.

---



### Paso 6 — Configurar Claude Desktop

> **Nota sobre la ruta del config en Windows:** Claude Desktop instalado desde
> Microsoft Store, WinGet o el instalador actual de claude.ai usa el formato
> **MSIX**. En ese caso el archivo real **no** está en `%APPDATA%\Claude\`, sino
> en una carpeta virtualizada bajo `Packages\Claude_...\LocalCache\Roaming\Claude\`.
> El botón *Edit Config* de Claude a veces abre el archivo equivocado; usá el
> script de abajo para abrir el que la app realmente lee.



#### 6.1 Cerrar Claude Desktop por completo

Cerrá la app (incluido el ícono en la bandeja del sistema). La config solo se lee al iniciar.

#### 6.2 Encontrar y editar el archivo de configuración MCP

Ejecutá este bloque en PowerShell. Detecta automáticamente si tenés instalación
MSIX o clásica y abre el archivo correcto:

```powershell
# Detectar la ruta real del config (MSIX o clasico)
$configFile = $null
$pkg = (Get-AppxPackage -Name "*Claude*" -ErrorAction SilentlyContinue).PackageFamilyName
if ($pkg) {
    $msixConfig = Join-Path $env:LOCALAPPDATA "Packages\$pkg\LocalCache\Roaming\Claude\claude_desktop_config.json"
    if (Test-Path (Split-Path $msixConfig -Parent)) {
        $configFile = $msixConfig
        Write-Host "Instalacion MSIX detectada."
        Write-Host "Config que lee Claude: $configFile"
    }
}
if (-not $configFile) {
    $configFile = "$env:APPDATA\Claude\claude_desktop_config.json"
    Write-Host "Instalacion clasica (no MSIX)."
    Write-Host "Config: $configFile"
}

# Crear el archivo si no existe
New-Item -ItemType Directory -Force -Path (Split-Path $configFile -Parent) | Out-Null
if (-not (Test-Path $configFile)) {
    '{}' | Set-Content -Path $configFile -Encoding UTF8
}

# Aviso si existen dos copias (bug conocido de MSIX)
$legacyConfig = "$env:APPDATA\Claude\claude_desktop_config.json"
if ($configFile -ne $legacyConfig -and (Test-Path $legacyConfig)) {
    Write-Host ""
    Write-Host "AVISO: Tambien existe $legacyConfig"
    Write-Host "       Edita SOLO el archivo MSIX de arriba. El otro lo ignora Claude."
}

notepad $configFile
```


| Tipo de instalación                           | Ruta del config que lee Claude                                                                      |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **MSIX** (Store / WinGet / instalador actual) | `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json` |
| **Clásica** (instalador antiguo)              | `%APPDATA%\Claude\claude_desktop_config.json`                                                       |


El sufijo `pzs8sxrjxfjjc` suele ser fijo; si difiere en tu PC, el script de
arriba lo resuelve solo con `Get-AppxPackage`.

#### 6.3 Agregar el servidor MCP

**Importante:** usá la ruta de `python` que obtuviste en el Paso 1, y rutas absolutas a `server.py`.

Ejemplo (ajustá `command` si tu Python está en otro path):

```json
{
  "mcpServers": {
    "finnegans-agent": {
      "command": "C:\\Users\\user\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe",
      "args": ["C:\\FinnegansAgent\\server.py"],
      "cwd": "C:\\FinnegansAgent"
    }
  }
}
```

**Reglas para no fallar:**


| Regla               | Correcto                        | Incorrecto                                         |
| ------------------- | ------------------------------- | -------------------------------------------------- |
| Barras en JSON      | `C:\\FinnegansAgent\\server.py` | `C:\FinnegansAgent\server.py`                      |
| `command`           | Ruta completa a `python.exe`    | Solo `python` (puede no resolverse en Claude)      |
| `cwd`               | Carpeta donde está `.env`       | Otra carpeta o vacío                               |
| Nombre del servidor | `finnegans-agent`               | Cualquier otro (debe coincidir con lo documentado) |


Si ya tenés otros MCPs en el JSON, **agregá** `finnegans-agent` dentro de `mcpServers` sin borrar los demás.

Validá que el JSON sea válido (reutilizá la misma detección de ruta):

```powershell
$pkg = (Get-AppxPackage -Name "*Claude*" -ErrorAction SilentlyContinue).PackageFamilyName
$configFile = if ($pkg -and (Test-Path (Join-Path $env:LOCALAPPDATA "Packages\$pkg\LocalCache\Roaming\Claude"))) {
    Join-Path $env:LOCALAPPDATA "Packages\$pkg\LocalCache\Roaming\Claude\claude_desktop_config.json"
} else {
    "$env:APPDATA\Claude\claude_desktop_config.json"
}
Get-Content $configFile | ConvertFrom-Json | Out-Null
if ($?) { Write-Host "JSON valido en $configFile" } else { Write-Host "JSON INVALIDO - corregir antes de abrir Claude" }
```



#### 6.4 Reiniciar Claude Desktop

Abrí Claude Desktop. En la conversación, el ícono de herramientas (🔨) debería mostrar tools de `finnegans-agent`.

---



### Paso 7 — Instrucciones del asistente para el líder

Para que el agente pida confirmación antes de escribir y hable en castellano claro:

1. En Claude Desktop, creá un **Proyecto** (ej. "Finnegans SOUTEX").
2. En **Instrucciones del proyecto**, pegá el contenido completo de `ASSISTANT_INSTRUCTIONS.md`.
3. El líder siempre usa ese proyecto para consultas de Finnegans.

```powershell
notepad C:\FinnegansAgent\ASSISTANT_INSTRUCTIONS.md
```

---



### Paso 8 — Prueba funcional en Claude (smoke test)

Con Claude Desktop abierto y el proyecto configurado, probá **en este orden**:

**8.1 Conexión**

> Verificá la conexión con Finnegans.

Esperado: mensaje de API OK y catálogo OK.

**8.2 Lectura (necesitás un código real de tu maestro)**

> Buscá la API de productos, mostrá cómo se consulta, y traeme el producto con código `CODIGO_REAL`.

Reemplazá `CODIGO_REAL` por un código existente en Finnegans.  
Esperado: datos del producto o un 404 claro si el código no existe.

**8.3 Escritura con validación (solo en ambiente de prueba)**

> Prepará la creación de [algo de bajo riesgo] y mostrámelo para confirmar. No ejecutes sin mi OK.

Esperado: resumen + pregunta de confirmación. **No** debe ejecutar solo.

> Sí, confirmá.

Esperado: recién ahí ejecuta `ejecutar_cambio`.

---



### Paso 9 — Pruebas manuales desde PowerShell (si Claude falla)

Si Claude no conecta el MCP pero `verify_setup.py` pasó, probá la API directo:

```powershell
Set-Location C:\FinnegansAgent

# Token de autenticacion
python cli.py token

# Lectura de un producto (reemplazar CODIGO_REAL)
python cli.py get producto --id CODIGO_REAL
```

Si la CLI funciona pero Claude no, el problema está en `claude_desktop_config.json` (Paso 6).

---



### Paso 10 — Entrega al líder

Entregá la PC con:

- [ ] Claude Desktop instalado y con sesión iniciada
- [ ] Proyecto "Finnegans" creado con instrucciones cargadas
- [ ] `verify_setup.py` ejecutado con TODO OK
- [ ] Smoke test de lectura probado con un código real
- [ ] `.env` **no** compartido ni documentado para el líder
- [ ] Acceso directo o pin a Claude Desktop (opcional)

**Lo que el líder necesita saber (una frase):**  
*"Abrí Claude, entrá al proyecto Finnegans, y preguntá en castellano. Si te pide confirmar un cambio, leé el resumen y decí sí o no."*

---



## Solución de problemas



### `python no se reconoce`

- Reinstalá Python con **Add to PATH**.
- Usá la ruta completa en `claude_desktop_config.json` → `command`.



### `verify_setup.py` — error en credenciales API

```
[ERROR] No se pudo autenticar: ...
```

- Verificá `FINNEGANS_CLIENT_ID` y `FINNEGANS_CLIENT_SECRET` en `.env`.
- Regenerá las keys en Finnegans si fueron rotadas.
- Comprobá que la PC tenga internet y acceso a `https://api.finneg.com`.



### `verify_setup.py` — error en catálogo de APIs

```
[ERROR] No se pudo consultar el catalogo: ...
```

- Verificá `FINNEGANS_DOCS_CLIENT_ID` y `FINNEGANS_DOCS_SECRET_KEY`.
- Copiá los valores desde el `mcp.json` de Cursor (sección `finnegans-api-docs` → `headers`).
- Comprobá acceso a `https://services.finneg.com`.



### Claude Desktop no muestra herramientas MCP

1. Cerrá Claude por completo (bandeja incluida).
2. Confirmá que editaste el config **MSIX** (si aplica), no solo el de `%APPDATA%\Claude\` (Paso 6.2).
3. Validá JSON: `ConvertFrom-Json` en PowerShell (Paso 6.3).
4. Confirmá que `command` apunta al mismo `python` donde instalaste `mcp`.
5. Revisá logs de Claude (ruta según tipo de instalación):
  ```powershell
   $pkg = (Get-AppxPackage -Name "*Claude*" -ErrorAction SilentlyContinue).PackageFamilyName
   $logDir = if ($pkg -and (Test-Path (Join-Path $env:LOCALAPPDATA "Packages\$pkg\LocalCache\Roaming\Claude\logs"))) {
       Join-Path $env:LOCALAPPDATA "Packages\$pkg\LocalCache\Roaming\Claude\logs"
   } else {
       "$env:APPDATA\Claude\logs"
   }
   Get-ChildItem $logDir -Recurse -Filter "*mcp*" | Sort-Object LastWriteTime -Descending | Select-Object -First 5
  ```
6. Ejecutá manualmente el servidor (debe quedar esperando, sin error):
  ```powershell
   Set-Location C:\FinnegansAgent
   python server.py
  ```
   Ctrl+C para salir. Si imprime error acá, corregilo antes de abrir Claude.



### `Bad Request: id missing` al consultar

- Esa API requiere un **código** en el path. Primero `buscar_api` + `ver_api` para ver parámetros.
- En `consultar_finnegans`, pasá el parámetro `id` con el código del maestro.



### `404 Not Found` al consultar

- La petición está bien formada; el **código no existe** en Finnegans.
- Probá con otro código que sepas que existe.



### El agente escribe sin pedir confirmación

- Revisá que las **instrucciones del proyecto** incluyan `ASSISTANT_INSTRUCTIONS.md`.
- El flujo correcto es: `preparar_cambio` → usuario confirma → `ejecutar_cambio`.
- `ejecutar_cambio` con `usuario_confirmo=false` **nunca** ejecuta (está bloqueado en código).



### Actualizar el agente en una PC ya configurada

```powershell
# Detener Claude Desktop primero
$Destino = "C:\FinnegansAgent"
Copy-Item -Path "\\servidor\compartido\finnegans-connector\*" -Destination $Destino -Recurse -Force
# NO sobrescribir .env si ya tiene credenciales
Set-Location $Destino
python -m pip install -r requirements.txt
python verify_setup.py
# Reiniciar Claude Desktop
```

---



## Herramientas MCP expuestas


| Tool                  | Propósito                                | Cuándo usarla                  |
| --------------------- | ---------------------------------------- | ------------------------------ |
| `verificar_conexion`  | Prueba credenciales y catálogo           | Diagnóstico / setup            |
| `buscar_api`          | Busca endpoints por nombre o descripción | Siempre primero                |
| `ver_api`             | Muestra métodos y parámetros de una API  | Antes de consultar o escribir  |
| `consultar_finnegans` | Lectura (GET)                            | Consultas de datos             |
| `preparar_cambio`     | Arma escritura sin ejecutar              | Crear/modificar/eliminar       |
| `ejecutar_cambio`     | Ejecuta tras confirmación del usuario    | Solo después de "sí, confirmo" |


---



## Seguridad

- Credenciales en `.env` (nunca en git, nunca en el chat).
- Escrituras **siempre** en dos pasos: preparar → confirmar → ejecutar.
- `ejecutar_cambio` rechaza si `usuario_confirmo` no es `true`.
- Confirmaciones expiran a los 10 minutos.
- No se usan contraseñas personales; solo credenciales de aplicación.
- Rotar `client_secret` y keys de docs si se expusieron en un chat o mail.

---



## Estructura del proyecto

```
finnegans-connector/
├── server.py                  # Agente MCP unificado (punto de entrada)
├── verify_setup.py            # Script de verificación para IT
├── finnegans/
│   ├── client.py              # HTTP client (auth + GET/POST/PUT/DELETE)
│   ├── discovery.py           # Catálogo de APIs (MCP remoto Finnegans)
│   ├── validator.py           # Cola de cambios con confirmación
│   └── config.py              # Carga de .env
├── cli.py                     # CLI para pruebas manuales
├── ASSISTANT_INSTRUCTIONS.md  # Prompt para Claude Desktop
├── .env.example
└── requirements.txt
```

---



## Diferencia con el MCP de docs de Cursor


|                          | MCP docs (Cursor)                | Este agente            |
| ------------------------ | -------------------------------- | ---------------------- |
| Propósito                | Documentación para programadores | Operación para líderes |
| Ejecuta en Finnegans     | No                               | Sí                     |
| Descubre APIs            | Sí                               | Sí (integrado)         |
| Validación de escrituras | No aplica                        | Sí, obligatoria        |


Los líderes solo necesitan **este agente** + Claude Desktop.
El MCP de docs en Cursor queda para desarrollo.

---



## Referencia rápida de comandos IT

```powershell
# Ir al proyecto
Set-Location C:\FinnegansAgent

# Verificación completa
python verify_setup.py

# Probar token API
python cli.py token

# Probar lectura
python cli.py get producto --id CODIGO_REAL

# Abrir config MCP de Claude (detecta MSIX o clasico)
$pkg = (Get-AppxPackage -Name "*Claude*" -ErrorAction SilentlyContinue).PackageFamilyName
$configFile = if ($pkg -and (Test-Path (Join-Path $env:LOCALAPPDATA "Packages\$pkg\LocalCache\Roaming\Claude"))) {
    Join-Path $env:LOCALAPPDATA "Packages\$pkg\LocalCache\Roaming\Claude\claude_desktop_config.json"
} else { "$env:APPDATA\Claude\claude_desktop_config.json" }
notepad $configFile

# Validar JSON de Claude
Get-Content $configFile | ConvertFrom-Json

# Ver ruta de Python para la config
(Get-Command python).Source
```

