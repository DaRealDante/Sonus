@echo off
chcp 65001 >nul
title Sonus - Disinstalla tutto
set "KM_PY="
py -3 -c "import sys" >nul 2>nul && set "KM_PY=py -3"
if not defined KM_PY python -c "import sys" >nul 2>nul && set "KM_PY=python"
if not defined KM_PY (
    echo Python non trovato. Disinstalla da Impostazioni di Windows - App - Sonus.
    pause
    exit /b 1
)
%KM_PY% "%~dp0sonus_build.py" --uninstall & exit /b
