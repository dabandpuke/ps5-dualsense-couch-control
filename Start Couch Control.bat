@echo off
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo [First-Time Setup] Creating local Python environment and installing requirements...
    python -m venv "%~dp0.venv"
    "%~dp0.venv\Scripts\pip.exe" install -r "%~dp0requirements.txt"
)
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"
) else (
    python "%~dp0app.py"
)
