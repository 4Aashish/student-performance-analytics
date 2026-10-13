@echo off
REM Double-click to run all tests.
cd /d "%~dp0"
call venv\Scripts\activate
pytest
pause
