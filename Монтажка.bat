@echo off
title Montazhnaya
cd /d "%~dp0studio"
if exist ".venv\Scripts\python.exe" goto run
echo First start: creating Python environment...
set "UV_PYTHON_INSTALL_DIR=D:\Captions my\.tools\python"
"D:\Captions my\.tools\uv.exe" venv .venv --python 3.12
if errorlevel 1 goto fail
"D:\Captions my\.tools\uv.exe" pip install --python .venv\Scripts\python.exe -r requirements.txt
if errorlevel 1 goto fail
:run
echo Montazhnaya: http://127.0.0.1:8790  (do not close this window)
".venv\Scripts\python.exe" run.py
pause
exit /b
:fail
echo Failed to prepare the environment.
pause
