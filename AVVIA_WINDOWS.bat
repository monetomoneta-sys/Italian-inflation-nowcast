@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Prima esegui INSTALLA_WINDOWS.bat
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python run_pipeline.py
echo.
echo Premi un tasto per chiudere.
pause >nul
