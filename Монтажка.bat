@echo off
chcp 65001 >nul
title Монтажная
cd /d "%~dp0studio"
if not exist ".venv\Scripts\python.exe" (
  echo Первый запуск: создаю окружение Python...
  set "UV_PYTHON_INSTALL_DIR=D:\Captions my\.tools\python"
  "D:\Captions my\.tools\uv.exe" venv .venv --python 3.12 || goto :fail
  "D:\Captions my\.tools\uv.exe" pip install --python .venv\Scripts\python.exe -r requirements.txt || goto :fail
)
echo Монтажная: http://127.0.0.1:8790  (не закрывайте это окно)
".venv\Scripts\python.exe" run.py
pause
exit /b
:fail
echo Не удалось подготовить окружение.
pause
