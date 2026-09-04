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

rem  OJO AL EDITAR O REENVIAR ESTE ARCHIVO
rem  Ninguna linea debe pasar de ~100 caracteres. Si un cliente de mail,
rem  un editor o un portapapeles corta una linea larga al medio, cmd
rem  ejecuta los pedazos como comandos ("-Path no se reconoce...") y el
rem  script sigue adelante como si todo hubiera salido bien. Por eso los
rem  comandos de PowerShell se arman por pedazos en variables cortas.

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
echo   No pude descargar la version nueva. Puede ser tu conexion a
echo   internet. Revisala y volve a intentar; si sigue fallando,
echo   mandale a IT este archivo:
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

rem Actualiza el codigo. Dos caminos, segun como se instalo:
rem   - con git (hay carpeta .git): pull de master.
rem   - copiando la carpeta: se baja el ZIP del repo publico.
rem El ZIP no incluye .env, audit/ ni exports/ porque estan en
rem .gitignore, asi que copiar encima no puede tocar las credenciales ni
rem el historial de auditoria del lider.
rem Si el pull falla -- por ejemplo, la rama local quedo divergida -- se
rem cae al ZIP en vez de cortar: el resultado es el mismo y no deja al
rem lider sin salida.

:actualizar_codigo
if not exist "%DIR%\.git" goto :actualizar_por_zip
where git >nul 2>&1
if errorlevel 1 goto :actualizar_por_zip
git -C "%DIR%" fetch origin --quiet 2>>"%LOG%"
if errorlevel 1 goto :actualizar_por_zip
git -C "%DIR%" checkout master --quiet 2>>"%LOG%"
if errorlevel 1 goto :actualizar_por_zip
git -C "%DIR%" pull --ff-only origin master --quiet 2>>"%LOG%"
if errorlevel 1 goto :actualizar_por_zip
exit /b 0

:actualizar_por_zip
set "URL=https://github.com/JPSformas/finnegans-connector/archive/refs/heads/master.zip"
set "Z1=$ErrorActionPreference='Stop'; try{"
set "Z2= $t=Join-Path $env:TEMP ('fnx_'+[guid]::NewGuid().ToString('N'));"
set "Z3= [void](New-Item -ItemType Directory -Path $t -Force);"
set "Z4= $z=Join-Path $t 'm.zip'; $tls=[Net.SecurityProtocolType]::Tls12;"
set "Z5= [Net.ServicePointManager]::SecurityProtocol=$tls;"
set "Z6= Invoke-WebRequest -Uri '%URL%' -OutFile $z -UseBasicParsing;"
set "Z7= Expand-Archive -Path $z -DestinationPath $t -Force;"
set "Z8= $d=@(Get-ChildItem -Path $t -Directory); if($d.Count -lt 1){ exit 1 };"
set "Z9= $src=Join-Path $d[0].FullName '*';"
set "ZA= Copy-Item -Path $src -Destination '%DIR%' -Recurse -Force;"
set "ZB= [IO.Directory]::Delete($t,$true)"
set "ZC=}catch{ Write-Error $_; exit 1 }"
powershell -NoProfile -Command "%Z1%%Z2%%Z3%%Z4%%Z5%%Z6%%Z7%%Z8%%Z9%%ZA%%ZB%%ZC%" 2>>"%LOG%"
if errorlevel 1 exit /b 1
exit /b 0

rem Agrega FINNEGANS_SWAGGER_KEY al .env solo si falta. Es idempotente a
rem proposito: si el script se corre dos veces, o si la deteccion falla,
rem no puede dejar la variable duplicada.

:revisar_clave
set "K1=$p='%DIR%\.env'; $pat='^FINNEGANS_SWAGGER_KEY=..';"
set "K2=try{ if(Select-String -Path $p -Pattern $pat -Quiet){'SI'}"
set "K3=else{'NO'} }catch{'ERROR'}"
set "KALL=%K1%%K2%%K3%"
set "TIENE_CLAVE="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "%KALL%"`) do set "TIENE_CLAVE=%%i"
if "%TIENE_CLAVE%"=="SI" (
  echo         Configuracion completa.
  exit /b 0
)
if not "%TIENE_CLAVE%"=="NO" exit /b 1
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
