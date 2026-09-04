@echo off
setlocal
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
rem config vive dentro del paquete. Se prueba esa ruta primero, igual que
rem hace verify_setup.py, y despues la clasica de %APPDATA%.
set "CFG="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "$c=@(); try{ foreach($d in [IO.Directory]::GetDirectories((Join-Path $env:LOCALAPPDATA 'Packages'),'Claude_*')){ $c+=(Join-Path $d 'LocalCache\Roaming\Claude\claude_desktop_config.json') } }catch{}; $c+=(Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'); foreach($p in $c){ if(Test-Path $p){ $p; break } }"`) do set "CFG=%%i"
if not defined CFG goto :err_sin_config

for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "try{$c=Get-Content '%CFG%' -Raw; $j=ConvertFrom-Json $c; $s=$j.mcpServers.'finnegans-agent'; Split-Path -Parent $s.args[0]}catch{}"`) do set "DIR=%%i"
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "try{$c=Get-Content '%CFG%' -Raw; $j=ConvertFrom-Json $c; $j.mcpServers.'finnegans-agent'.command}catch{}"`) do set "PY=%%i"

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

set "TIENE_CLAVE="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "try{$m=Select-String -Path '%DIR%\.env' -Pattern '^FINNEGANS_SWAGGER_KEY=..' -Quiet; if($m){'SI'}else{'NO'}}catch{'NO'}"`) do set "TIENE_CLAVE=%%i"

if "%TIENE_CLAVE%"=="SI" (
  echo         Configuracion completa.
) else (
  if not defined CLAVE_DOC goto :err_falta_clave
  powershell -NoProfile -Command "$p='%DIR%\.env'; $t=[System.IO.File]::ReadAllText($p); $nl=[Environment]::NewLine; if(-not $t.EndsWith($nl)){$t+=$nl}; $t+='FINNEGANS_SWAGGER_KEY=%CLAVE_DOC%'+$nl; [System.IO.File]::WriteAllText($p,$t)"
  if errorlevel 1 goto :err_falta_clave
  echo         Configuracion completada.
)
echo.

rem --- 4. Dependencias ------------------------------------------------
echo   [4/6] Revisando componentes...
pushd "%DIR%"
"%PY%" -m pip install -r requirements.txt --upgrade --quiet --disable-pip-version-check 2>>"%LOG%"
if errorlevel 1 (
  popd
  goto :err_pip
)
echo         Componentes al dia.
echo.

rem --- 5. Verificar que la version nueva funciona ---------------------
echo   [5/6] Probando...
"%PY%" -c "from finnegans.config import Settings; from finnegans.swagger_catalog import cargar_spec, buscar_endpoints; s=Settings(); s.require_swagger_config(); spec=cargar_spec(s.swagger_url,s.swagger_key); r=buscar_endpoints(spec,'movimiento de fondos',limite=3); print('        Encontro',len(r),'resultados de prueba'); raise SystemExit(0 if r else 1)" 2>>"%LOG%"
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
powershell -NoProfile -Command "Stop-Process -Name Claude -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 3; $id=''; foreach($x in Get-StartApps){ if($x.Name -like '*Claude*'){ $id=$x.AppID; break } }; if($id){ Start-Process explorer.exe -ArgumentList ('shell:AppsFolder\'+$id) } else { exit 3 }"
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
echo   Avisale a IT: no existe claude_desktop_config.json ni en la ruta del
echo   paquete (LOCALAPPDATA\Packages\Claude_*) ni en %APPDATA%\Claude.
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
echo   No pude descargar la version nueva. Puede ser tu conexion a internet.
echo   Revisala y volve a intentar; si sigue fallando, mandale a IT
echo   este archivo:
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

rem ================== Actualizacion del codigo =======================
rem Dos caminos, segun como se instalo:
rem   - con git (hay carpeta .git): pull de master.
rem   - copiando la carpeta, que es lo que indica el README: se baja el ZIP
rem     del repo publico. El ZIP no incluye .env, audit/ ni exports/ porque
rem     estan en .gitignore, asi que copiar encima no puede tocar las
rem     credenciales ni el historial de auditoria del lider.

:actualizar_codigo
if not exist "%DIR%\.git" goto :actualizar_por_zip
where git >nul 2>&1
if errorlevel 1 goto :actualizar_por_zip
git -C "%DIR%" fetch origin --quiet 2>>"%LOG%"
if errorlevel 1 exit /b 1
git -C "%DIR%" checkout master --quiet 2>>"%LOG%"
if errorlevel 1 exit /b 1
git -C "%DIR%" pull --ff-only origin master --quiet 2>>"%LOG%"
if errorlevel 1 exit /b 1
exit /b 0

:actualizar_por_zip
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try{ $t=Join-Path $env:TEMP ('fnx_'+[guid]::NewGuid().ToString('N')); [void](New-Item -ItemType Directory -Path $t -Force); $z=Join-Path $t 'm.zip'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/JPSformas/finnegans-connector/archive/refs/heads/master.zip' -OutFile $z -UseBasicParsing; Expand-Archive -Path $z -DestinationPath $t -Force; $d=@(Get-ChildItem -Path $t -Directory); if($d.Count -lt 1){ exit 1 }; Copy-Item -Path (Join-Path $d[0].FullName '*') -Destination '%DIR%' -Recurse -Force; [IO.Directory]::Delete($t,$true) }catch{ Write-Error $_; exit 1 }" 2>>"%LOG%"
if errorlevel 1 exit /b 1
exit /b 0
