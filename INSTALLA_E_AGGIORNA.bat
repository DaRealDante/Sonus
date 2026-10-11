@echo off
chcp 65001 >nul
title Sonus - Installa / Aggiorna
cd /d "%~dp0"

set "KM_PY="
py -3 -c "import sys" >nul 2>nul && set "KM_PY=py -3"
if not defined KM_PY python -c "import sys" >nul 2>nul && set "KM_PY=python"

if not defined KM_PY (
    echo Python non trovato: lo installo con winget...
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    echo.
    echo Fatto. CHIUDI questa finestra e riapri INSTALLA_E_AGGIORNA.bat
    pause
    exit /b 0
)

if not exist "%~dp0sonus_build.py" (
    echo [ERRORE] Manca sonus_build.py accanto a questo file.
    echo Estrai TUTTO lo zip in una cartella e apri INSTALLA_E_AGGIORNA.bat da li'.
    pause
    exit /b 1
)

%KM_PY% "%~dp0sonus_build.py" %*
if errorlevel 1 pause
