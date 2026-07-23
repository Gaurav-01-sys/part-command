@echo off
setlocal

cd /d "%~dp0"

if not exist logs mkdir logs

echo Starting Dash app with runtime logging enabled.
echo Latest combined log: logs\dash_app.latest.log
echo Latest error log:    logs\dash_app.latest.error.log
echo.

".\ld\Scripts\python.exe" dash_app.py
