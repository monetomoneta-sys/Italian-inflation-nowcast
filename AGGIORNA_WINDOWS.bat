@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python run_pipeline.py --headless
pause
