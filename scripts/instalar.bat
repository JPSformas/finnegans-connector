@echo off
title Instalar asistente Finnegans

rem ===================================================================
rem  INSTALADOR para una PC que nunca tuvo el conector.
rem  Para una PC ya instalada usar scripts\actualizar.bat.
rem
rem  Se corre DOS veces:
rem    1a vez: instala el codigo y crea la carpeta. Se detiene pidiendo
rem            el archivo .env, que IT manda por separado (tiene las
rem            credenciales de la API y no puede viajar en este archivo).
rem    2a vez: detecta el .env, configura Claude, verifica y reinicia.
rem ===================================================================

rem Clave de lectura de la documentacion de APIs. La misma que usa el
rem actualizador: es de solo lectura y ya esta en el repo publico. Si el
rem .env que manda IT ya la trae, esta no se usa.
set "CLAVE_DOC=435f45445548"

rem Donde se instala. En LOCALAPPDATA no hace falta ser administrador.
set "DESTINO=%LOCALAPPDATA%\FinnegansAgent"

rem  OJO AL EDITAR: ninguna linea debe pasar de ~95 caracteres, y el
rem  script se relanza desde %TEMP% antes de tocar nada. Las dos cosas
rem  son por lo mismo: cmd lee los .bat por offset de bytes mientras los
rem  ejecuta, asi que una linea cortada o un archivo reemplazado en pleno
rem  vuelo lo hacen ejecutar fragmentos sin detenerse.
set "COPIA=%TEMP%\fnx-instalador"
if /i "%~dp0"=="%COPIA%\" goto :arranque
if not exist "%COPIA%" mkdir "%COPIA%" >nul 2>&1
copy /y "%~f0" "%COPIA%\instalar.bat" >nul 2>&1
if errorlevel 1 goto :arranque
call "%COPIA%\instalar.bat"
exit /b

:arranque
setlocal
rem Directorios del sistema al frente del PATH: sin esto "tar" puede
rem resolver al GNU tar que trae Git para Windows, que no lee ZIP.
set "SYS=%SystemRoot%\System32"
set "PATH=%SYS%;%SYS%\WindowsPowerShell\v1.0;%PATH%"
set "URL_GIT=https://github.com/JPSformas/finnegans-connector.git"
set "URL_ZIP=https://github.com/JPSformas/finnegans-connector/archive/refs/heads/master.zip"

echo.
echo   ===============================================
echo    INSTALAR EL ASISTENTE FINNEGANS
echo   ===============================================
echo.
echo    Tarda unos minutos.
echo    No cierres esta ventana hasta que te lo indique.
echo.
pause
echo.

rem --- 1. Python ------------------------------------------------------
echo   [1/7] Buscando Python...
set "PY="
set "SNIP=import sys;print(sys.executable)"
for /f "usebackq delims=" %%i in (`py -3 -c "%SNIP%" 2^>nul`) do set "PY=%%i"
if not defined PY (
  for /f "usebackq delims=" %%i in (`python -c "%SNIP%" 2^>nul`) do set "PY=%%i"
)
if defined PY if not exist "%PY%" set "PY="
if not defined PY goto :err_sin_python
echo         Python: %PY%
echo.

rem --- 2. Claude Desktop ----------------------------------------------
echo   [2/7] Buscando Claude Desktop...
call :ubicar_config
if not defined CFG goto :err_sin_claude
echo         Config: %CFG%
echo.

rem --- 3. Traer el codigo ---------------------------------------------
echo   [3/7] Descargando el asistente...
if not exist "%DESTINO%" mkdir "%DESTINO%" >nul 2>&1
if not exist "%DESTINO%" goto :err_carpeta
call :traer_codigo
if errorlevel 1 goto :err_descarga
if not exist "%DESTINO%\server.py" goto :err_descarga
echo         Instalado en: %DESTINO%
echo.

set "LOG=%DESTINO%\instalacion-error.txt"
if exist "%LOG%" del "%LOG%" >nul 2>&1

rem --- 4. Dependencias ------------------------------------------------
echo   [4/7] Instalando componentes...
pushd "%DESTINO%"
set "PIP=-m pip install -r requirements.txt --quiet --disable-pip-version-check"
"%PY%" %PIP% 2>>"%LOG%"
if errorlevel 1 (
  popd
  goto :err_pip
)
popd
echo         Componentes listos.
echo.

rem --- 5. El archivo .env ---------------------------------------------
echo   [5/7] Revisando las credenciales...
call :rescatar_env
if not exist "%DESTINO%\.env" goto :falta_env
call :revisar_env
if errorlevel 1 goto :fin
call :completar_env
if errorlevel 1 goto :err_env
echo.

rem --- 6. Configurar Claude -------------------------------------------
echo   [6/7] Configurando Claude...
call :configurar_claude
if errorlevel 1 goto :err_config
echo         Asistente registrado en Claude.
echo.

rem --- 7. Verificar ----------------------------------------------------
echo   [7/7] Probando la conexion con Finnegans...
pushd "%DESTINO%"
set "V1=from finnegans.client import FinnegansClient as F;"
set "V2=from finnegans.swagger_catalog import cargar_spec as C, buscar_endpoints as B;"
set "V3=c=F(); t=c.get_token(); s=c.settings; s.require_swagger_config();"
set "V4=r=B(C(s.swagger_url,s.swagger_key),'movimiento de fondos',limite=3);"
set "V5=print('        Conexion OK, encontro',len(r),'APIs de prueba');"
set "V6=raise SystemExit(0 if (t and r) else 1)"
"%PY%" -c "%V1%%V2%%V3%%V4%%V5%%V6%" 2>>"%LOG%"
if errorlevel 1 (
  popd
  goto :err_prueba
)
popd
echo.

rem --- Reiniciar Claude ------------------------------------------------
echo   Falta un paso: cerrar y abrir Claude.
echo.
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
echo    LISTO. El asistente Finnegans ya funciona.
echo   ===============================================
echo.
echo    Probalo preguntandole en Claude:
echo      "buscame la api de movimiento de fondos"
echo.
echo    Para actualizarlo mas adelante, usa actualizar.bat
echo    (esta en %DESTINO%\scripts).
echo.
goto :fin

rem ================== Pausa esperando el .env ========================

:falta_env
echo.
echo   ===============================================
echo    FALTA UN PASO: EL ARCHIVO DE CREDENCIALES
echo   ===============================================
echo.
echo   El codigo ya quedo instalado, pero falta el archivo con las
echo   credenciales de Finnegans. IT te lo manda por separado: no puede
echo   venir dentro de este instalador.
echo.
echo   1. Guarda el archivo .env que te mando IT en esta carpeta:
echo.
echo         %DESTINO%
echo.
echo      Tiene que quedar con el nombre exacto  .env  (con el punto
echo      adelante y sin ninguna extension como .txt).
echo.
echo   2. Volve a hacer doble clic en este mismo instalador.
echo.
echo   Te abro la carpeta para que lo pegues ahi.
echo.
start "" "%DESTINO%"
goto :fin

rem ================== Mensajes de error ==============================

:err_sin_python
echo.
echo   NO PUDE SEGUIR
echo   Falta Python en esta PC.
echo   Avisale a IT: hay que instalar Python 3.10 o mayor desde
echo   python.org, marcando "Add python.exe to PATH".
goto :fin

:err_sin_claude
echo.
echo   NO PUDE SEGUIR
echo   No encontre Claude Desktop en esta PC.
echo   Instalalo desde claude.ai/download, abrilo una vez, cerralo, y
echo   volve a ejecutar este instalador.
goto :fin

:err_carpeta
echo.
echo   NO PUDE SEGUIR
echo   No pude crear la carpeta de instalacion:
echo      %DESTINO%
echo   Avisale a IT.
goto :fin

:err_descarga
echo.
echo   NO PUDE SEGUIR
echo   No pude descargar el asistente. Puede ser tu conexion a internet,
echo   o el antivirus bloqueando la descarga. Volve a intentar; si sigue
echo   fallando, avisale a IT.
goto :fin

:err_pip
echo.
echo   NO PUDE SEGUIR
echo   Fallo la instalacion de componentes de Python.
echo   Mandale a IT este archivo:
echo      %LOG%
goto :fin

:err_env
echo.
echo   NO PUDE SEGUIR
echo   El archivo .env existe pero no pude leerlo o completarlo.
echo   Mandale a IT este archivo:
echo      %LOG%
goto :fin

:err_config
echo.
echo   NO PUDE SEGUIR
echo   No pude registrar el asistente en la configuracion de Claude.
echo   Mandale a IT este archivo:
echo      %LOG%
goto :fin

:err_prueba
echo.
echo   NO PUDE SEGUIR
echo   Instale todo, pero Finnegans rechazo la conexion. Casi siempre
echo   es que el archivo .env tiene credenciales de otra cuenta o
echo   incompletas. Mandale a IT este archivo:
echo      %LOG%
goto :fin

:fin
echo.
pause
endlocal
exit /b

rem ================== Subrutinas =====================================

rem Ubica claude_desktop_config.json. Claude puede estar instalado desde
rem la Store (MSIX) y ahi el config vive dentro del paquete; esa ruta va
rem primero, igual que en verify_setup.py.

:ubicar_config
set "Q1=$c=@(); $r='LocalCache\Roaming\Claude\claude_desktop_config.json';"
set "Q2=try{ $pk=Join-Path $env:LOCALAPPDATA 'Packages';"
set "Q3= foreach($d in [IO.Directory]::GetDirectories($pk,'Claude_*')){"
set "Q4=  $c+=(Join-Path $d $r) } }catch{};"
set "Q5=$c+=(Join-Path $env:APPDATA 'Claude\claude_desktop_config.json');"
set "Q6=foreach($p in $c){ if(Test-Path $p){ $p; break } }"
set "QALL=%Q1%%Q2%%Q3%%Q4%%Q5%%Q6%"
set "CFG="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "%QALL%"`) do set "CFG=%%i"
if defined CFG exit /b 0
rem Claude instalado pero nunca abierto: el config todavia no existe.
rem Se crea en la ruta clasica, que Claude lee igual.
set "Q7=$d=Join-Path $env:APPDATA 'Claude';"
set "Q8=if(Test-Path $d){ Join-Path $d 'claude_desktop_config.json' }"
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "%Q7%%Q8%"`) do set "CFG=%%i"
exit /b 0

rem Trae el codigo: git clone si hay git, si no curl + tar (los dos
rem nativos de Windows). No se usa PowerShell para bajar el ZIP porque
rem Windows Defender marca ese patron como Trojan:Win32/Commando.A!ml.

:traer_codigo
where git >nul 2>&1
if errorlevel 1 goto :traer_por_zip
if exist "%DESTINO%\.git" goto :traer_pull
git clone --quiet "%URL_GIT%" "%DESTINO%" 2>nul
if errorlevel 1 goto :traer_init
exit /b 0

:traer_init
rem La carpeta ya existia y no estaba vacia: se convierte en clon.
git -C "%DESTINO%" init --quiet 2>nul
git -C "%DESTINO%" remote add origin "%URL_GIT%" 2>nul
:traer_pull
git -C "%DESTINO%" fetch origin master --quiet 2>nul
if errorlevel 1 goto :traer_por_zip
git -C "%DESTINO%" checkout --quiet -f -B master origin/master 2>nul
if errorlevel 1 goto :traer_por_zip
exit /b 0

:traer_por_zip
set "TMPZ=%TEMP%\fnx-zip-inst"
if exist "%TMPZ%" rd /s /q "%TMPZ%" >nul 2>&1
mkdir "%TMPZ%" >nul 2>&1
set "CURL=%SYS%\curl.exe"
set "TAR=%SYS%\tar.exe"
if not exist "%CURL%" exit /b 1
if not exist "%TAR%" exit /b 1
"%CURL%" -sSL --fail -o "%TMPZ%\m.zip" "%URL_ZIP%" 2>nul
if errorlevel 1 exit /b 1
"%TAR%" -xf "%TMPZ%\m.zip" -C "%TMPZ%" 2>nul
if errorlevel 1 exit /b 1
set "RAIZ="
for /d %%d in ("%TMPZ%\finnegans-connector-*") do set "RAIZ=%%d"
if not defined RAIZ exit /b 1
xcopy "%RAIZ%\*" "%DESTINO%\" /e /y /q >nul 2>nul
if errorlevel 1 exit /b 1
rd /s /q "%TMPZ%" >nul 2>&1
exit /b 0

rem Windows esconde las extensiones, asi que un archivo guardado como
rem ".env.txt" se ve igual que ".env". Es el error mas comun al pegar el
rem archivo, y deja al instalador leyendo el .env viejo (o ninguno). Si el
rem .env no esta, se usa la variante que si este.

:rescatar_env
if exist "%DESTINO%\.env" exit /b 0
for %%f in (".env.txt" "env.txt" "env" ".env.text") do (
  if exist "%DESTINO%\%%~f" (
    copy /y "%DESTINO%\%%~f" "%DESTINO%\.env" >nul 2>&1
    echo         Encontre el archivo como %%~f y lo renombre a .env
    exit /b 0
  )
)
exit /b 0

rem Valida el .env con la misma funcion que usa verify_setup.py, y muestra
rem en pantalla exactamente que esta mal. Antes solo decia "llego dañado"
rem sin mostrar el valor leido, y eso no alcanzaba para darse cuenta de que
rem el archivo revisado no era el que la persona habia editado.

rem Codigos de salida: 0 esta bien, 1 hay problemas, 2 no se pudo revisar
rem (una version instalada vieja puede no tener validar_env). El caso 2 no
rem puede bloquear: seria decirle que el archivo esta mal cuando en realidad
rem no lo revisamos. El paso 7 igual prueba la conexion de verdad.
:revisar_env
set "E1=import sys; sys.path.insert(0,r'%DESTINO%');"
set "E2=try: from verify_setup import validar_env as V"
set "E3=except Exception: raise SystemExit(2)"
set "E4=p=r'%DESTINO%\.env'"
set "E5=try: t=open(p,encoding='utf-8',errors='replace').read()"
set "E6=except Exception: raise SystemExit(2)"
set "E7=e=V(t)"
set "E8=print(chr(10).join('        - '+x for x in e))"
set "E9=raise SystemExit(1 if e else 0)"
set "SC=%TEMP%\fnx-revisar-env.py"
> "%SC%" echo %E1%
>>"%SC%" echo %E2%
>>"%SC%" echo %E3%
>>"%SC%" echo %E4%
>>"%SC%" echo %E5%
>>"%SC%" echo %E6%
>>"%SC%" echo %E7%
>>"%SC%" echo %E8%
>>"%SC%" echo %E9%
"%PY%" "%SC%" 2>>"%LOG%"
if errorlevel 2 goto :revisar_env_nose
if errorlevel 1 goto :revisar_env_mal
echo         Credenciales verificadas.
exit /b 0

:revisar_env_nose
echo         No pude revisar el archivo; sigo y lo pruebo mas adelante.
exit /b 0

:revisar_env_mal
echo.
echo   EL ARCHIVO .env NO ESTA COMPLETO
echo.
echo   Lo lei en esta ruta:
echo      %DESTINO%\.env
echo.
echo   Si el archivo que editaste no es ese, fijate que Windows esconde
echo   las extensiones: puede haber quedado como .env.txt
echo.
echo   Pedile a IT que te lo mande COMO ARCHIVO ADJUNTO (no pegado en el
echo   cuerpo del mail), guardalo en esa carpeta reemplazando el que
echo   esta, y volve a ejecutar este instalador.
exit /b 1

rem Completa lo que el .env que manda IT no puede traer:
rem   - FINNEGANS_OPERATOR: quien opera esta PC. Es lo que la auditoria
rem     graba como responsable de cada cambio, asi que no puede quedar
rem     con el valor de ejemplo ni con el nombre de otra persona.
rem   - FINNEGANS_SWAGGER_KEY: si falta, se agrega la de este archivo.
rem Las dos escrituras son idempotentes.

:completar_env
findstr /b /c:"FINNEGANS_SWAGGER_KEY=" "%DESTINO%\.env" >nul 2>&1
if not errorlevel 1 goto :env_operador
set "S1=$p='%DESTINO%\.env'; $nl=[Environment]::NewLine;"
set "S2=$t=[IO.File]::ReadAllText($p);"
set "S3=if($t -match 'FINNEGANS_SWAGGER_KEY=.'){ exit 0 };"
set "S4=if(-not $t.EndsWith($nl)){ $t+=$nl };"
set "S5=$t+='FINNEGANS_SWAGGER_KEY=%CLAVE_DOC%'+$nl;"
set "S6=[IO.File]::WriteAllText($p,$t)"
powershell -NoProfile -Command "%S1%%S2%%S3%%S4%%S5%%S6%" 2>>"%LOG%"
if errorlevel 1 exit /b 1

:env_operador
rem Si ya hay un operador real (no el de ejemplo) no se pregunta nada.
findstr /b /c:"FINNEGANS_OPERATOR=Nombre Apellido" "%DESTINO%\.env" >nul 2>&1
if errorlevel 1 (
  findstr /b /r /c:"FINNEGANS_OPERATOR=..*" "%DESTINO%\.env" >nul 2>&1
  if not errorlevel 1 (
    echo         Credenciales completas.
    exit /b 0
  )
)
echo.
echo         Para la auditoria hace falta saber quien usa esta PC.
echo         Cada consulta y cada cambio se registra con este dato.
echo.
set "QUIEN="
set /p "QUIEN=        Tu nombre y apellido: "
echo.
if not defined QUIEN set "QUIEN=sin identificar"
set "O1=$p='%DESTINO%\.env'; $nl=[Environment]::NewLine;"
set "O2=$q='FINNEGANS_OPERATOR=%QUIEN%';"
set "O3=$l=[IO.File]::ReadAllLines($p); $hecho=$false; $out=@();"
set "O4=foreach($x in $l){ if($x -like 'FINNEGANS_OPERATOR=*'){"
set "O5=  $out+=$q; $hecho=$true } else { $out+=$x } };"
set "O6=if(-not $hecho){ $out+=$q };"
set "O7=[IO.File]::WriteAllText($p,($out -join $nl)+$nl)"
powershell -NoProfile -Command "%O1%%O2%%O3%%O4%%O5%%O6%%O7%" 2>>"%LOG%"
if errorlevel 1 exit /b 1
echo         Credenciales completas.
exit /b 0

rem Agrega la entrada finnegans-agent al config de Claude SIN pisar lo
rem que ya haya (puede tener otros MCP configurados). Se escribe sin BOM
rem porque Claude no parsea el JSON si lo tiene.

:configurar_claude
set "C1=$p='%CFG%'; $dir='%DESTINO%'; $py='%PY%';"
set "C2=$d=Split-Path -Parent $p;"
set "C3=if(-not (Test-Path $d)){ [void](New-Item -ItemType Directory -Path $d -Force) };"
set "C4=if(Test-Path $p){ $j=ConvertFrom-Json ([IO.File]::ReadAllText($p)) }"
set "C5=else{ $j=New-Object psobject };"
set "C6=if(-not $j.mcpServers){ $j | Add-Member mcpServers (New-Object psobject) -Force };"
set "C7=$e=[ordered]@{ command=$py; args=@((Join-Path $dir 'server.py')); cwd=$dir };"
set "C8=$j.mcpServers | Add-Member 'finnegans-agent' ([psobject]$e) -Force;"
set "C9=$s=ConvertTo-Json -InputObject $j -Depth 10;"
set "CA=[IO.File]::WriteAllText($p,$s)"
set "CALL=%C1%%C2%%C3%%C4%%C5%%C6%%C7%%C8%%C9%%CA%"
powershell -NoProfile -Command "%CALL%" 2>>"%LOG%"
if errorlevel 1 exit /b 1
exit /b 0
