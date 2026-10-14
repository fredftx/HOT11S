@echo off
setlocal
cd /d "%~dp0"
set "PY=%~dp0tools\venv\Scripts\python.exe"
set "MTK=%~dp0tools\mtkclient-main\mtk.py"
rem Usa o driver UsbDk (necessario: o Preloader aparece sem driver no Windows)
set "MTK_USBDK=1"

if not exist "%PY%" (
  echo [ERRO] Ambiente Python nao encontrado em tools\venv.
  pause
  exit /b 1
)

:menu
cls
echo ==============================================================
echo   Ferramenta MTK - Infinix Hot 11S (X6812B)  - via mtkclient
echo ==============================================================
echo.
echo   1. Informacoes do aparelho e tabela de particoes (so leitura)
echo   2. Backup das particoes essenciais (IMEI, calibracao, etc.)
echo   3. Abrir a interface grafica do mtkclient
echo   4. RESET DE FABRICA (apaga dados do usuario)
echo   5. Reler a particao nvdata e verificar se esta vazia (so leitura)
echo   6. Ler logs de travamento (expdb/misc) e analisar (so leitura)
echo   7. Ler e verificar imagens de boot dos slots A e B (so leitura)
echo   8. Gravar boot.img de ESTOQUE nos slots A e B (corrige o bootloop)
echo   9. Gravar a ROM de estoque INTEIRA (sem IMEI, preloader e dados)
echo  10. Sair
echo.
echo   Depois de escolher, CONECTE o cabo USB quando aparecer
echo   "Waiting for device"/"Preloader". Se nao conectar, desligue e
echo   conecte segurando VOLUME + e VOLUME - juntos.
echo.
set /p OP="Escolha uma opcao: "

if "%OP%"=="1" goto info
if "%OP%"=="2" goto backup
if "%OP%"=="3" goto gui
if "%OP%"=="4" goto reset
if "%OP%"=="5" goto nvdata
if "%OP%"=="6" goto logs
if "%OP%"=="7" goto bootimg
if "%OP%"=="8" goto gravarboot
if "%OP%"=="9" goto gravarrom
if "%OP%"=="10" exit /b 0
goto menu

:gravarrom
if not exist logs mkdir logs
echo.
set "ROM=%~dp0firmware\rom"
if not exist "%ROM%" (
  echo [ERRO] Extraia o .zip da ROM dentro de:
  echo        %ROM%
  pause
  goto menu
)
echo Montando o plano - nada e gravado nesta etapa...
"%PY%" "%~dp0tools\gravar_rom.py" "%ROM%" "logs\particoes.txt" > logs\plano_rom.txt 2>&1
set "PLANO=%errorlevel%"
type logs\plano_rom.txt
echo.
echo O plano foi salvo em logs\plano_rom.txt
if not "%PLANO%"=="0" (
  echo [CANCELADO] O plano tem problemas. Mande logs\plano_rom.txt para o Claude.
  pause
  goto menu
)
echo.
echo  Isto grava as particoes marcadas como "grava" acima. Nao mexe no
echo  IMEI, no preloader nem nos seus arquivos. Pode levar 20-30 minutos.
echo.
set /p CONF="Digite GRAVAR para confirmar: "
if /i not "%CONF%"=="GRAVAR" (
  echo Cancelado.
  pause
  goto menu
)
"%PY%" "%~dp0tools\gravar_rom.py" "%ROM%" "logs\particoes.txt" --executar "%PY%" "%MTK%"
echo.
pause
goto menu

:gravarboot
echo.
set "BOOTIMG=%~dp0firmware\boot.img"
if not exist "%BOOTIMG%" (
  echo [ERRO] Coloque o boot.img da ROM de estoque do X6812B em:
  echo        %BOOTIMG%
  pause
  goto menu
)
if exist backup\boot_b.bin (
  echo Imagem que esta hoje no slot B, a que trava o aparelho:
  "%PY%" "%~dp0tools\verificar_bootimg.py" "backup\boot_b.bin"
  echo.
)
echo Imagem que vai ser gravada:
"%PY%" "%~dp0tools\verificar_bootimg.py" "%BOOTIMG%"
if errorlevel 1 (
  echo.
  echo [CANCELADO] O boot.img escolhido nao passou na verificacao.
  pause
  goto menu
)
echo.
echo  Isto grava o boot.img acima em boot_a e boot_b. Nao apaga fotos,
echo  apps nem o IMEI. A imagem antiga do slot B esta em backup\boot_b.bin.
echo.
set /p CONF="Digite GRAVAR para confirmar: "
if /i not "%CONF%"=="GRAVAR" (
  echo Cancelado.
  pause
  goto menu
)
echo Conecte o cabo segurando VOLUME + e VOLUME - .
"%PY%" "%MTK%" w boot_a,boot_b "%BOOTIMG%","%BOOTIMG%"
echo.
echo Pronto. Desconecte o cabo e ligue o aparelho segurando POWER.
pause
goto menu

:bootimg
if not exist backup mkdir backup
echo.
if not exist logs mkdir logs
echo Lendo UMA particao por vez (boot_b primeiro). Arquivos ja completos sao pulados.
call :lerpart boot_b 33554432
call :lerpart vendor_boot_b 67108864
call :lerpart boot_a 33554432
call :lerpart vendor_boot_a 67108864
echo.
"%PY%" "%~dp0tools\analisar_boot.py" "backup" > logs\boot_analise.txt 2>&1
type logs\boot_analise.txt
echo.
pause
goto menu

:lerpart
rem %1 = particao, %2 = tamanho esperado em bytes
set "SZ=0"
if exist "backup\%1.bin" for %%F in ("backup\%1.bin") do set "SZ=%%~zF"
if "%SZ%"=="%2" (
  echo [OK] backup\%1.bin ja esta completo - pulando.
  exit /b 0
)
echo.
echo ==============================================================
echo  Lendo %1. DESCONECTE e conecte o cabo de novo segurando
echo  VOLUME + e VOLUME - . Nao mexa no cabo durante a leitura.
echo ==============================================================
powershell -NoProfile -Command "& '%PY%' '%MTK%' r %1 'backup\%1.bin' 2>&1 | Tee-Object -FilePath 'logs\leitura_%1.txt'"
set "SZ=0"
if exist "backup\%1.bin" for %%F in ("backup\%1.bin") do set "SZ=%%~zF"
if "%SZ%"=="%2" (echo [OK] %1 lido completo.) else (echo [FALHOU] %1 incompleto: %SZ% de %2 bytes. Rode a opcao 7 de novo para tentar so o que faltou.)
exit /b 0

:logs
if not exist backup mkdir backup
if not exist logs mkdir logs
echo.
echo Lendo as particoes expdb e misc ...
"%PY%" "%MTK%" r expdb,misc backup\expdb.bin,backup\misc.bin
echo.
"%PY%" "%~dp0tools\analisar_logs.py" "backup\expdb.bin" "backup\misc.bin" "logs"
echo.
pause
goto menu

:nvdata
if not exist backup mkdir backup
echo.
echo Relendo a particao nvdata para backup\nvdata_releitura.bin ...
"%PY%" "%MTK%" r nvdata backup\nvdata_releitura.bin
echo.
"%PY%" "%~dp0tools\verificar_nvdata.py" "backup\nvdata_releitura.bin" "backup\nvdata.bin"
echo.
pause
goto menu

:info
if not exist logs mkdir logs
echo.
echo Lendo tabela de particoes... (o resultado tambem vai para logs\particoes.txt)
echo Conecte o cabo agora. Ctrl+C cancela.
powershell -NoProfile -Command "& '%PY%' '%MTK%' printgpt 2>&1 | Tee-Object -FilePath 'logs\particoes.txt'"
echo.
pause
goto menu

:backup
if not exist backup mkdir backup
echo.
echo Fazendo backup de: proinfo, nvram, nvcfg, nvdata, protect1, protect2, persist, seccfg
echo Guarde a pasta "backup" em lugar seguro - ela tem o IMEI do aparelho.
echo.
"%PY%" "%MTK%" gpt backup
echo.
echo ==============================================================
echo  Passo 1 concluido. DESCONECTE o cabo e conecte de novo
echo  segurando VOLUME + e VOLUME - para o passo 2.
echo ==============================================================
"%PY%" "%MTK%" r proinfo,nvram,nvcfg,nvdata,protect1,protect2,persist,seccfg backup\proinfo.bin,backup\nvram.bin,backup\nvcfg.bin,backup\nvdata.bin,backup\protect1.bin,backup\protect2.bin,backup\persist.bin,backup\seccfg.bin
echo.
dir backup
echo.
pause
goto menu

:gui
start "" "%PY%" "%~dp0tools\mtkclient-main\mtk_gui.py"
goto menu

:reset
echo.
echo  ATENCAO: isto apaga TODOS os dados do usuario (fotos, apps, contas)
echo  das particoes userdata e metadata. E o mesmo que um reset de fabrica.
echo  Faca o BACKUP (opcao 2) antes.
echo  Depois do reset, o aparelho pode pedir a conta Google usada antes (FRP).
echo.
set /p CONF="Digite APAGAR para confirmar: "
if /i not "%CONF%"=="APAGAR" (
  echo Cancelado.
  pause
  goto menu
)
"%PY%" "%MTK%" e userdata,metadata
echo.
pause
goto menu
