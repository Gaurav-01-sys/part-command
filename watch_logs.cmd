@echo off
setlocal

cd /d "%~dp0"

set "APP_NAME=%~1"
if "%APP_NAME%"=="" set "APP_NAME=dash_app"

set "LOG_KIND=%~2"
set "LOG_FILE=logs\%APP_NAME%.latest.error.log"
if /I "%LOG_KIND%"=="all" set "LOG_FILE=logs\%APP_NAME%.latest.log"

if not exist "%LOG_FILE%" (
    echo Log file not found: %LOG_FILE%
    echo Start the app first with run_dash_logged.cmd or python dash_app.py
    exit /b 1
)

echo Watching %LOG_FILE% (errors only — pass "all" as 2nd arg for full log)
powershell -NoProfile -Command "Get-Content -Path '%LOG_FILE%' -Wait -Tail 80"
