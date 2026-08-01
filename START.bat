@echo off
REM Launches the app from source (development). End users should run
REM "SHEET auto FILL.exe" instead.
cd /d "%~dp0"

if exist "dist\SHEET auto FILL.exe" (
    start "" "dist\SHEET auto FILL.exe"
    exit /b
)

REM pythonw runs without a console window
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw desktop.py
) else (
    py desktop.py
)
