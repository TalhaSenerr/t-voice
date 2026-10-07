@echo off
cd /d "%~dp0"
if exist "dist\T-Voice\T-Voice.exe" (
    start "" "dist\T-Voice\T-Voice.exe"
) else if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "run.py"
) else (
    echo T-Voice kurulumu bulunamadi. Once Kurulum.ps1 dosyasini calistirin.
    pause
)
