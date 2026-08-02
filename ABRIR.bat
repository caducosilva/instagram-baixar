@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente virtual...
  where py >nul 2>&1 && (
    py -3 -m venv .venv
  ) || (
    python -m venv .venv
  )
  ".venv\Scripts\python.exe" -m pip install -U pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  ".venv\Scripts\python.exe" -m playwright install chromium
)

REM Evita abrir com Python do sistema (duplicata). So o .venv.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"
endlocal
