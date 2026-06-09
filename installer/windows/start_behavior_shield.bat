@echo off
setlocal
set "APP_EXE=%ProgramFiles%\BehaviorShield\BehaviorShield.exe"

if not exist "%APP_EXE%" (
    echo [ERROR] BehaviorShield.exe not found at:
    echo         %APP_EXE%
    exit /b 1
)

start "" "%APP_EXE%"
exit /b 0
