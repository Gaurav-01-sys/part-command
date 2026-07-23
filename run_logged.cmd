@echo off
setlocal

cd /d "%~dp0"

set "APP_SCRIPT=%~1"
if "%APP_SCRIPT%"=="" set "APP_SCRIPT=dash_app.py"

if not exist "%APP_SCRIPT%" (
    echo App script not found: %APP_SCRIPT%
    exit /b 1
)

if not exist logs mkdir logs

for %%F in ("%APP_SCRIPT%") do set "APP_NAME=%%~nF"

echo Starting %APP_SCRIPT% with runtime logging enabled.
echo Latest combined log: logs\%APP_NAME%.latest.log
echo Latest error log:    logs\%APP_NAME%.latest.error.log
echo.

".\ld\Scripts\python.exe" "%APP_SCRIPT%"
