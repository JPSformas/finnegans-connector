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
- [ ] Instalador de [Git para Windows](https://git-scm.com/download/win) (dejá las opciones por defecto)
- [ ] **Clave de lectura de la documentación** (`FINNEGANS_SWAGGER_KEY`)
  ```
  Sin esta variable, buscar_api / ver_api / preparar_cambio no funcionan.
  ```

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



### Paso 2 — Clonar el proyecto en la PC

Clonalo con Git. **No lo copies a mano ni lo bajes como ZIP:** un clon deja la
carpeta preparada para actualizarse después con un solo paso
(`scripts\actualizar.bat`), sin volver a pasar por la PC del líder.

**Recomendado:** `C:\FinnegansAgent` (sin espacios en la ruta).

```powershell
git clone https://github.com/JPSformas/finnegans-connector.git C:\FinnegansAgent
Set-Location C:\FinnegansAgent
Get-ChildItem
```

**Resultado esperado:** debés ver `server.py`, `finnegans\`, `requirements.txt`, `.env.example`, `verify_setup.py`, `scripts\`, etc.

```powershell
Test-Path "C:\FinnegansAgent\server.py"
Test-Path "C:\FinnegansAgent\.git"
```

Ambos deben devolver `True`. El segundo es el que habilita la actualización
en un paso.

> **Instalaciones viejas.** Las hechas con el instructivo anterior (copiar
> un ZIP descomprimido) no tienen carpeta `.git`. Siguen funcionando, y
> `scripts\actualizar.bat` las actualiza igual bajando el ZIP del repo. No
> hace falta reinstalarlas.

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

## Instalar en una PC nueva sin acceso a ella

Si IT no puede llegar a la máquina, `scripts\instalar.bat` hace la
instalación completa. Requiere que el líder ya tenga **Python 3.10+** y
**Claude Desktop** instalados (el script corta con un mensaje claro si falta
alguno).

Se corre **dos veces**, a propósito:

1. **Primera pasada.** Ubica Python y la config de Claude, descarga el
   código en `%LOCALAPPDATA%\FinnegansAgent`, instala las dependencias, y se
   detiene pidiendo el `.env`. Abre la carpeta donde hay que pegarlo.
2. **Segunda pasada.** Detecta el `.env`, completa lo que falte, registra el
   asistente en Claude, prueba la conexión real contra Finnegans y reinicia
   Claude.

El `.env` va **por separado**: tiene `FINNEGANS_CLIENT_ID` y
`FINNEGANS_CLIENT_SECRET`, que son credenciales de producción y no pueden
viajar dentro de un `.bat`. Se puede reusar el mismo `.env` de otra PC con
una salvedad: **`FINNEGANS_OPERATOR` identifica a quién la auditoría le
atribuye cada cambio**, así que no debe quedar con el nombre de otra persona
ni con el valor de ejemplo. El instalador lo pregunta y lo escribe él mismo
si detecta que falta o sigue en el ejemplo.

La entrada en `claude_desktop_config.json` se **agrega sin pisar** lo que ya
haya: si la PC tiene otros MCP configurados, quedan intactos.

---

## Actualizar una PC ya instalada

Pensado para cuando IT **no tiene acceso** a la máquina del líder.

Mandale `scripts\actualizar.bat` por mail o chat. El líder lo guarda en
cualquier carpeta (Descargas sirve) y hace doble clic. El script:

1. Se ubica solo: lee la carpeta de instalación y el intérprete de Python
   desde `claude_desktop_config.json`, probando primero la ruta MSIX (Claude
   instalado desde la Store) y después la de `%APPDATA%`.
2. Trae la versión nueva: `git pull` si la carpeta es un clon, o bajando el
   ZIP del repo si se instaló copiando la carpeta. El ZIP no incluye `.env`,
   `audit/` ni `exports/` porque están en `.gitignore`, así que copiar encima
   no toca las credenciales ni el historial de auditoría.
3. Completa `FINNEGANS_SWAGGER_KEY` en el `.env` si falta.
4. Reinstala dependencias con el intérprete correcto.
5. Verifica contra `swaggerGlobal` que la versión nueva realmente busca.
6. Reinicia Claude Desktop. **Cerrar la ventana no alcanza:** el server MCP
   es un proceso hijo que sobrevive; hay que salir desde la bandeja del
   sistema, y eso es lo que el script hace por él.

Los detalles técnicos van a `actualizacion-error.txt` en la carpeta de
instalación, no a la pantalla: cada mensaje de error le dice al líder qué
archivo mandarle a IT.

**Antes de enviarlo**, si el `.env` del líder puede no tener la swagger key,
completá la variable `CLAVE_DOC` en las primeras líneas del `.bat`. Si la
dejás vacía y falta la clave, el script corta con un mensaje claro sin dejar
nada a medias.

---



## Entrega a usuarios

**GATE OBLIGATORIO: Los 4 pasos siguientes son el criterio de aceptación por PC.**

Antes de entregar la PC a un usuario (líder), un operador IT debe ejecutar **en orden** los 4 pasos de validación que figuran abajo. Solo cuando los 4 pasos pasen, la PC está lista.

---

### Paso 1: Configurar `.env` con credenciales de servicio acotadas

**Objetivo:** verificar que las credenciales en `.env` son de un **usuario API con rol acotado** (NO administrador).

- [ ] En Finnegans, obtener un usuario de servicio con **rol limitado** (ej. "Solo lectura + escritura de tablas permitidas").
- [ ] Copiar su `client_id` y `client_secret`.
- [ ] Verificar en el archivo `.env` que está completado:
  ```env
  FINNEGANS_CLIENT_ID=<id del usuario acotado>
  FINNEGANS_CLIENT_SECRET=<secret del usuario acotado>
  FINNEGANS_OPERATOR=<nombre de usuario de prueba para auditoría>
  ```
- [ ] **Validar que NO están credenciales de administrador.**
- [ ] Confirmar que `.env` está en `.gitignore` (no subido a git).

**Criterio de aceptación:** `.env` cargado con usuario acotado y `FINNEGANS_OPERATOR` definido.

---

### Paso 2: Correr `python verify_setup.py` y confirmar checks 4, 5 y 6

**Objetivo:** validar que Python, credenciales, catálogo de APIs y servidor MCP funcionan.

- [ ] Abrir PowerShell en la carpeta del proyecto (ej. `C:\FinnegansAgent`).
- [ ] Ejecutar:
  ```powershell
  python verify_setup.py
  ```
- [ ] Esperar a que finalice. **Todos los checks deben estar `[OK]`**, especialmente:
  - **Check 4:** Autenticación y token (credenciales API válidas)
  - **Check 5:** Búsqueda en catálogo de APIs (conectividad a Finnegans)
  - **Check 6:** Servidor MCP registrado y funcionando
- [ ] Si hay un `[ERROR]`, **detente aquí**:
  1. Lee el mensaje de error.
  2. Corrige el punto indicado (ej. actualizar `.env`, reiniciar, verificar conectividad).
  3. Vuelve a ejecutar `python verify_setup.py`.
  4. Repite hasta que todos los checks pasen.

**Criterio de aceptación:** Script finaliza con `RESULTADO: TODO OK (6/6 checks automáticos)`.

---

### Paso 3: Lectura real en Claude Desktop

**Objetivo:** verificar que el agente conecta a Finnegans y trae datos reales en modo lectura.

- [ ] **Cerrar Claude Desktop por completo** (incluido el ícono en la bandeja del sistema).
- [ ] **Volver a abrir Claude Desktop.**
- [ ] Entrar al **Proyecto "Finnegans"** (o el nombre que configuraste en el Paso 7).
- [ ] Escribir en la conversación un mensaje de **lectura de solo lectura**, ejemplo:
  ```
  Buscá la API de productos. Mostrá cómo se consulta. Ahora trae los datos del producto con código "PROD123".
  ```
  (Reemplazar `PROD123` por un código que exista en tu base de datos de Finnegans.)
- [ ] Confirmar que:
  - El agente usa `buscar_api` para encontrar el endpoint.
  - El agente usa `ver_api` para ver los parámetros.
  - El agente usa `consultar_finnegans` para traer los datos.
  - Los datos se devuelven **sin errores** (no 401, 403, 500).
  - La respuesta es en **castellano claro**.

**Criterio de aceptación:** Claude Desktop ejecuta una consulta real contra Finnegans y devuelve datos correctos sin error de autenticación.

---

### Paso 4: Escritura de prueba controlada con auditoría

**Objetivo:** validar que la escritura requiere confirmación, muestra preview, genera auditoría sin exponer tokens.

- [ ] En Claude, escribir un mensaje de **escritura sobre un registro descartable** (algo que no importe borrar después), ejemplo:
  ```
  Prepará la creación de una nota o comentario interno en un cliente de prueba. Mostrámelo para confirmar. No ejecutes sin mi OK.
  ```
- [ ] Confirmar que:
  - [ ] El agente **NO ejecuta inmediatamente**.
  - [ ] Muestra un **PREVIEW** con los campos exactos que va a cambiar.
  - [ ] Muestra el **código** que va a ejecutar.
  - [ ] Pregunta: *"¿Confirmás? (sí / no)"* esperando confirmación explícita.
- [ ] Escribir en la conversación:
  ```
  Sí, confirmá.
  ```
- [ ] Confirmar que:
  - [ ] Ahora SÍ ejecuta `ejecutar_cambio`.
  - [ ] Muestra "Listo" o mensaje de éxito.
  - [ ] **No hay errores** de permisos (401, 403) ni validación (400).
- [ ] **Verificación posterior:** escribir en Claude:
  ```
  Buscá el registro que acabo de crear/modificar. Tráeme sus datos actualizados para confirmar que el cambio está.
  ```
  Confirmar que el agente trae el registro con los cambios reflejados.
- [ ] **Revisar auditoría** — abrir PowerShell y ejecutar:
  ```powershell
  Get-Content C:\FinnegansAgent\audit\finnegans-audit.jsonl | Select-Object -Last 10
  ```
  (O la ruta donde hayas configurado `FINNEGANS_AUDIT_PATH`.)

  Confirmar que aparecen **al menos 2 líneas** para tu cambio:
  1. Línea con `"evento": "preparado"` → debe tener `"operador": "<tu_usuario_de_prueba>"`, **SIN `token`**.
  2. Línea con `"evento": "ejecutado"` → debe tener `"operador": "<tu_usuario_de_prueba>"`, **SIN `token`**.

**Criterio de aceptación:**
- El flujo es: preparación → preview → confirmación explícita → ejecución
- Los datos se actualicen realmente en Finnegans
- Verificación posterior confirma el cambio
- El log de auditoría registre ambos eventos (`preparado` y `ejecutado`) con el operador correcto
- **Ningún token está expuesto en el log**

---

### Resumen: Checklist de aceptación por PC

**Antes de entregar, confirma que:**

- [ ] **Paso 1:** `.env` tiene credenciales acotadas y `FINNEGANS_OPERATOR` definido
- [ ] **Paso 2:** `python verify_setup.py` finaliza con TODO OK (6/6)
- [ ] **Paso 3:** Lectura real en Claude trae datos correctos desde Finnegans
- [ ] **Paso 4:** Escritura con validación, preview, confirmación y auditoría funcionan

**Si algún paso falla:**
1. Lee el error.
2. Investiga la causa (credenciales vencidas, conectividad, permisos).
3. Corrige el punto.
4. Repite el paso que falló.
5. **No avances** hasta que el paso anterior pase completamente.

---

### Entrega al líder (usuario final)

Una vez que los 4 pasos pasen, entregá la PC con:

- [ ] Claude Desktop instalado y con sesión iniciada
- [ ] Proyecto "Finnegans" creado con instrucciones del archivo `ASSISTANT_INSTRUCTIONS.md` cargadas
- [ ] `verify_setup.py` ejecutado exitosamente con TODO OK
- [ ] Lectura real probada con un código real de Finnegans
- [ ] `.env` **no** compartido con el líder (IT lo guarda)
- [ ] Acceso rápido a Claude Desktop (opcional: acceso directo o pin a la barra de tareas)

**Nota simple para el líder:**  
*"Abrí Claude, entrá al proyecto Finnegans, y preguntá en castellano qué necesitás. Si te pide confirmar un cambio, leé el resumen y decí sí o no. ¿Preguntas? Llamá a IT."*

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

- El router de Finnegans exige un segmento tras la entidad. Rutas válidas:
  - `GET /api/{entidad}/{codigo}` → un registro.
  - `GET /api/{entidad}/list` → listado completo.
  - `GET /api/reports/{Nombre}` → reportes.
- Si querés listar, usá `api_id='{entidad}/list'`. Si querés un registro, pasá `id`.



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

> **Fuente de verdad de APIs:** el conector resuelve endpoints contra el spec
> OpenAPI completo de Finnegans (`FINNEGANS_SWAGGER_URL` + `FINNEGANS_SWAGGER_KEY`,
> el Swagger de oneteam). El MCP `finnegans-api-docs` queda como apoyo secundario.

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
- Si el `client_secret` o el `FINNEGANS_SWAGGER_KEY` se exponen (chat, mail),
  rotarlos en Finnegans y actualizar el `.env`.

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

