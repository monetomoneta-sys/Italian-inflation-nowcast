@echo off
cd /d "%~dp0"
py -m venv .venv
if errorlevel 1 python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
echo.
echo Installazione completata. Ora fai doppio clic su AVVIA_WINDOWS.bat
pause
