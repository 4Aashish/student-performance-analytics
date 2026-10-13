@echo off
REM Double-click to start the app. Close this window (or press Ctrl+C) to stop it.
cd /d "%~dp0"
call venv\Scripts\activate
streamlit run app\main.py
pause
