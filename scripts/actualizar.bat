@echo off
setlocal
title Actualizar asistente Finnegans

rem ===================================================================
rem  OPCIONAL (lo completa IT antes de enviar el archivo)
rem  Si el .env del lider no tiene la clave de documentacion, el script
rem  la agrega solo usando este valor. Si se deja vacio, el script avisa
rem  y no toca nada.
set "CLAVE_DOC="
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
set "CFG=%APPDATA%\Claude\claude_desktop_config.json"
if not exist "%CFG%" goto :err_sin_config

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
where git >nul 2>&1
if errorlevel 1 goto :err_sin_git
if not exist "%DIR%\.git" goto :err_sin_git_repo

git -C "%DIR%" fetch origin --quiet 2>>"%LOG%"
if errorlevel 1 goto :err_red
git -C "%DIR%" checkout master --quiet 2>>"%LOG%"
if errorlevel 1 goto :err_cambios_locales
git -C "%DIR%" pull --ff-only origin master --quiet 2>>"%LOG%"
if errorlevel 1 goto :err_cambios_locales
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
echo   Avisale a IT: falta %APPDATA%\Claude\claude_desktop_config.json
goto :fin

:err_sin_entrada
echo.
echo   NO PUDE SEGUIR
echo   Claude esta instalado, pero no encuentro el asistente Finnegans.
echo   Avisale a IT: falta la entrada "finnegans-agent" en la config,
echo   o la carpeta se movio de lugar.
goto :fin

:err_sin_git
echo.
echo   NO PUDE SEGUIR
echo   Falta el programa Git en esta PC.
echo   Avisale a IT: hay que instalar Git para poder actualizar.
goto :fin

:err_sin_git_repo
echo.
echo   NO PUDE SEGUIR
echo   La carpeta del asistente se copio a mano, no se puede actualizar sola.
echo   Avisale a IT: la instalacion no tiene repositorio git.
goto :fin

:err_red
echo.
echo   NO PUDE SEGUIR
echo   No pude conectarme a internet para descargar la version nueva.
echo   Revisa tu conexion y volve a intentar.
goto :fin

:err_cambios_locales
echo.
echo   NO PUDE SEGUIR
echo   La carpeta tiene cambios que bloquean la actualizacion.
echo   Mandale a IT este archivo:
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
