@echo off
title Actualizar asistente Finnegans

rem ===================================================================
rem  Clave de lectura de la documentacion de APIs (swaggerGlobal).
rem  Si el .env del lider no la tiene, el script la agrega con este
rem  valor. Si se deja vacio, el script avisa y no toca nada.
rem
rem  ATENCION IT: este valor esta versionado en un repo publico. Cuando
rem  se rote la clave con Finnegans, hay que actualizarla aca y dejar de
rem  versionarla (moverla a un canal privado hacia el lider).
set "CLAVE_DOC=435f45445548"
rem ===================================================================

rem  ---------------------------------------------------------------
rem  RELANZARSE DESDE %TEMP% -- NO SACAR ESTO
rem  Este script actualiza la carpeta del conector, y el script vive
rem  DENTRO de esa carpeta. cmd lee los .bat por offset de bytes
rem  mientras los ejecuta, asi que si el archivo se reemplaza en pleno
rem  vuelo la siguiente lectura cae en medio de otra linea: cmd ejecuta
rem  fragmentos ("hell" de "powershell", "-Path", "fined"...) y despues
rem  repite pasos ya hechos. Por eso lo primero es correr desde una
rem  copia en %TEMP%, donde nada la va a sobreescribir.
rem  ---------------------------------------------------------------
set "COPIA=%TEMP%\fnx-actualizador"
if /i "%~dp0"=="%COPIA%\" goto :arranque
if not exist "%COPIA%" mkdir "%COPIA%" >nul 2>&1
copy /y "%~f0" "%COPIA%\actualizar.bat" >nul 2>&1
if errorlevel 1 goto :arranque
call "%COPIA%\actualizar.bat"
exit /b

:arranque
setlocal
rem Rutas absolutas a las herramientas del sistema: un PATH raro (o el
rem de Git para Windows, que trae sus propias versiones) no puede
rem hacernos ejecutar otro binario del que creemos.
set "SYS=%SystemRoot%\System32"
set "PATH=%SYS%;%SYS%\WindowsPowerShell\v1.0;%PATH%"
set "URL_GIT=https://github.com/JPSformas/finnegans-connector.git"
set "URL_ZIP=https://github.com/JPSformas/finnegans-connector/archive/refs/heads/master.zip"

echo.
echo   ===============================================
echo    ACTUALIZAR EL ASISTENTE FINNEGANS
echo   ===============================================
echo.
echo    Tarda uno o dos minutos.
echo    No cierres esta ventana hasta que diga LISTO.
echo.
pause
echo.

rem --- 1. Ubicar la instalacion leyendo la config de Claude -----------
echo   [1/6] Buscando la instalacion...

rem Claude Desktop puede estar instalado desde la Store (MSIX), y ahi el
rem config vive dentro del paquete. Se prueba esa ruta primero, igual
rem que hace verify_setup.py, y despues la clasica de %APPDATA%.
set "Q1=$c=@(); $r='LocalCache\Roaming\Claude\claude_desktop_config.json';"
set "Q2=try{ $pk=Join-Path $env:LOCALAPPDATA 'Packages';"
set "Q3= foreach($d in [IO.Directory]::GetDirectories($pk,'Claude_*')){"
set "Q4=  $c+=(Join-Path $d $r) } }catch{};"
set "Q5=$c+=(Join-Path $env:APPDATA 'Claude\claude_desktop_config.json');"
set "Q6=foreach($p in $c){ if(Test-Path $p){ $p; break } }"
set "QALL=%Q1%%Q2%%Q3%%Q4%%Q5%%Q6%"
set "CFG="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "%QALL%"`) do set "CFG=%%i"
if not defined CFG goto :err_sin_config

set "J1=try{ $c=Get-Content '%CFG%' -Raw; $j=ConvertFrom-Json $c;"
set "J2= $s=$j.mcpServers.'finnegans-agent';"
set "JDIR=%J1%%J2% Split-Path -Parent $s.args[0] }catch{}"
set "JPY=%J1%%J2% $s.command }catch{}"
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "%JDIR%"`) do set "DIR=%%i"
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "%JPY%"`) do set "PY=%%i"

if not defined DIR goto :err_sin_entrada
if not exist "%DIR%\server.py" goto :err_sin_entrada
if not defined PY set "PY=python"
echo         Carpeta: %DIR%
echo.

rem Los detalles tecnicos van a un archivo, no a la pantalla del lider.
set "LOG=%DIR%\actualizacion-error.txt"
if exist "%LOG%" del "%LOG%" >nul 2>&1

rem --- 2. Traer la version nueva -------------------------------------
echo   [2/6] Descargando la version nueva...
call :actualizar_codigo
if errorlevel 1 goto :err_descarga
echo         Codigo actualizado.
echo.

rem --- 3. Revisar la clave de documentacion en el .env ---------------
echo   [3/6] Revisando la configuracion...
if not exist "%DIR%\.env" goto :err_sin_env
call :revisar_clave
if errorlevel 1 goto :err_falta_clave
echo.

rem --- 4. Dependencias ------------------------------------------------
echo   [4/6] Revisando componentes...
pushd "%DIR%"
set "PIP=-m pip install -r requirements.txt --upgrade --quiet"
"%PY%" %PIP% --disable-pip-version-check 2>>"%LOG%"
if errorlevel 1 (
  popd
  goto :err_pip
)
echo         Componentes al dia.
echo.

rem --- 5. Verificar que la version nueva funciona ---------------------
echo   [5/6] Probando...
set "V1=from finnegans.config import Settings as S;"
set "V2=from finnegans.swagger_catalog import cargar_spec as C, buscar_endpoints as B;"
set "V3=s=S(); s.require_swagger_config();"
set "V4=r=B(C(s.swagger_url,s.swagger_key),'movimiento de fondos',limite=3);"
set "V5=print('        Encontro',len(r),'resultados de prueba');"
set "V6=raise SystemExit(0 if r else 1)"
"%PY%" -c "%V1%%V2%%V3%%V4%%V5%%V6%" 2>>"%LOG%"
if errorlevel 1 (
  popd
  goto :err_prueba
)
popd
echo.

rem --- 6. Reiniciar Claude -------------------------------------------
echo   [6/6] Reiniciando Claude...
echo.
echo         Se va a cerrar Claude y abrir de nuevo.
echo         Si tenes una conversacion a medio escribir, copiala antes.
echo.
pause
set "R1=Stop-Process -Name Claude -Force -ErrorAction SilentlyContinue;"
set "R2=Start-Sleep -Seconds 3; $id='';"
set "R3=foreach($x in Get-StartApps){"
set "R4= if($x.Name -like '*Claude*'){ $id=$x.AppID; break } };"
set "R5=if($id){ Start-Process explorer.exe -ArgumentList ('shell:AppsFolder\'+$id) }"
set "R6=else { exit 3 }"
powershell -NoProfile -Command "%R1%%R2%%R3%%R4%%R5%%R6%"
if errorlevel 3 (
  echo         No pude abrirlo solo: abri Claude desde el menu Inicio.
) else (
  echo         Claude reiniciado.
)

echo.
echo   ===============================================
echo    LISTO. Ya tenes la version nueva.
echo   ===============================================
echo.
echo    Probalo preguntandole:
echo      "buscame la api de movimiento de fondos"
echo.
goto :fin

rem ================== Mensajes de error ==============================

:err_sin_config
echo.
echo   NO PUDE SEGUIR
echo   No encontre la configuracion de Claude en esta PC.
echo   Avisale a IT: no existe claude_desktop_config.json ni en la ruta
echo   del paquete (LOCALAPPDATA\Packages\Claude_*) ni en %APPDATA%\Claude.
goto :fin

:err_sin_entrada
echo.
echo   NO PUDE SEGUIR
echo   Claude esta instalado, pero no encuentro el asistente Finnegans.
echo   Avisale a IT: falta la entrada "finnegans-agent" en la config,
echo   o la carpeta se movio de lugar.
goto :fin

:err_descarga
echo.
echo   NO PUDE SEGUIR
echo   No pude traer la version nueva. Puede ser tu conexion a internet,
echo   o el antivirus bloqueando la descarga. Volve a intentar; si sigue
echo   fallando, mandale a IT este archivo:
echo      %LOG%
goto :fin

:err_sin_env
echo.
echo   NO PUDE SEGUIR
echo   Falta el archivo de configuracion con las credenciales.
echo   Avisale a IT: no existe %DIR%\.env
goto :fin

:err_falta_clave
echo.
echo   CASI LISTO, FALTA UN DATO
echo   El codigo quedo actualizado, pero falta una clave de configuracion.
echo.
echo   Avisale a IT con este mensaje:
echo      "Falta FINNEGANS_SWAGGER_KEY en el .env"
echo.
echo   Cuando te la pase, volve a ejecutar este archivo.
goto :fin

:err_pip
echo.
echo   NO PUDE SEGUIR
echo   Fallo la instalacion de componentes.
echo   Mandale a IT este archivo:
echo      %LOG%
goto :fin

:err_prueba
echo.
echo   NO PUDE SEGUIR
echo   El codigo se actualizo, pero la prueba final fallo.
echo   El asistente puede no funcionar bien. Mandale a IT este archivo:
echo      %LOG%
goto :fin

:fin
echo.
pause
endlocal
exit /b

rem ================== Subrutinas =====================================

rem Actualiza el codigo dejando la carpeta igual a origin/master.
rem
rem Camino preferido: git. Si la carpeta no es un clon (las instalaciones
rem viejas se hacian copiando un ZIP a mano) se convierte en clon con
rem init + remote + fetch, y de ahi en adelante es un repo normal.
rem "checkout -f -B master origin/master" cubre de una el caso de la rama
rem divergida, que con "pull --ff-only" quedaba sin salida. Pisa los
rem archivos versionados; .env, audit/ y exports/ no lo son, asi que las
rem credenciales y la auditoria quedan intactas.
rem
rem Camino de respaldo: curl + tar, los dos nativos de Windows (system32
rem desde la 1803). Se usa en lugar de bajar el ZIP con PowerShell porque
rem Windows Defender marca ese patron (Invoke-WebRequest + Expand-Archive
rem + Copy-Item en un solo -Command) como Trojan:Win32/Commando.A!ml y
rem mata el proceso.

:actualizar_codigo
where git >nul 2>&1
if errorlevel 1 goto :actualizar_por_zip
if not exist "%DIR%\.git" call :convertir_en_clon
git -C "%DIR%" fetch origin master --quiet 2>>"%LOG%"
if errorlevel 1 goto :actualizar_por_zip
git -C "%DIR%" checkout --quiet -f -B master origin/master 2>>"%LOG%"
if errorlevel 1 goto :actualizar_por_zip
exit /b 0

:convertir_en_clon
git -C "%DIR%" init --quiet 2>>"%LOG%"
git -C "%DIR%" remote add origin "%URL_GIT%" 2>>"%LOG%"
exit /b 0

:actualizar_por_zip
set "TMPZ=%TEMP%\fnx-zip"
if exist "%TMPZ%" rd /s /q "%TMPZ%" >nul 2>&1
mkdir "%TMPZ%" >nul 2>&1
rem Por ruta absoluta a proposito: si el lider tiene Git para Windows, su
rem PATH puede resolver "tar" al GNU tar que trae Git, que no lee ZIP.
rem El de System32 es bsdtar (libarchive) y si lo lee.
set "CURL=%SYS%\curl.exe"
set "TAR=%SYS%\tar.exe"
if not exist "%CURL%" exit /b 1
if not exist "%TAR%" exit /b 1
"%CURL%" -sSL --fail -o "%TMPZ%\m.zip" "%URL_ZIP%" 2>>"%LOG%"
if errorlevel 1 exit /b 1
"%TAR%" -xf "%TMPZ%\m.zip" -C "%TMPZ%" 2>>"%LOG%"
if errorlevel 1 exit /b 1
set "RAIZ="
for /d %%d in ("%TMPZ%\finnegans-connector-*") do set "RAIZ=%%d"
if not defined RAIZ exit /b 1
xcopy "%RAIZ%\*" "%DIR%\" /e /y /q >nul 2>>"%LOG%"
if errorlevel 1 exit /b 1
rd /s /q "%TMPZ%" >nul 2>&1
exit /b 0

rem Agrega FINNEGANS_SWAGGER_KEY al .env solo si falta. Es idempotente a
rem proposito: si el script se corre dos veces, o si la deteccion falla,
rem no puede dejar la variable duplicada.

:revisar_clave
findstr /b /c:"FINNEGANS_SWAGGER_KEY=" "%DIR%\.env" >nul 2>&1
if not errorlevel 1 (
  echo         Configuracion completa.
  exit /b 0
)
if not defined CLAVE_DOC exit /b 1
set "A1=$p='%DIR%\.env'; $nl=[Environment]::NewLine;"
set "A2=$t=[IO.File]::ReadAllText($p);"
set "A3=if($t -match 'FINNEGANS_SWAGGER_KEY=.'){ exit 0 };"
set "A4=if(-not $t.EndsWith($nl)){ $t+=$nl };"
set "A5=$t+='FINNEGANS_SWAGGER_KEY=%CLAVE_DOC%'+$nl;"
set "A6=[IO.File]::WriteAllText($p,$t)"
powershell -NoProfile -Command "%A1%%A2%%A3%%A4%%A5%%A6%" 2>>"%LOG%"
if errorlevel 1 exit /b 1
echo         Configuracion completada.
exit /b 0
