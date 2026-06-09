@echo off
setlocal EnableExtensions

set "APP_DIR=%ProgramFiles%\BehaviorShield"
set "LOGGER_DIR=%ProgramData%\SysLogger"
set "META_DIR=%ProgramData%\BehaviorShield"
set "SERVICE_ID=BehaviorShieldLogger"
set "TASK_NAME=BehaviorShieldLogger"

echo ============================================================
echo   BehaviorShield Bundle Uninstaller
echo ============================================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Please run this script as Administrator.
    exit /b 1
)

echo [1/5] Stopping app process...
taskkill /F /IM BehaviorShield.exe >nul 2>&1

echo [2/5] Removing logger background task...
if exist "%APP_DIR%\unregister_logger_service.bat" (
    call "%APP_DIR%\unregister_logger_service.bat"
) else (
    schtasks /end /tn "%TASK_NAME%" >nul 2>&1
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
    taskkill /F /IM logger.exe >nul 2>&1
)

echo [3/5] Cleaning legacy scheduled tasks...
schtasks /end /tn "BehaviorShieldLoggerWatchdog" >nul 2>&1
schtasks /delete /tn "BehaviorShieldLoggerWatchdog" /f >nul 2>&1
schtasks /end /tn "BehaviorShieldLogger" >nul 2>&1
schtasks /delete /tn "BehaviorShieldLogger" /f >nul 2>&1
schtasks /end /tn "SysLogger" >nul 2>&1
schtasks /delete /tn "SysLogger" /f >nul 2>&1
sc stop "%SERVICE_ID%" >nul 2>&1
sc delete "%SERVICE_ID%" >nul 2>&1

echo [4/5] Removing installed files and logs...
if exist "%APP_DIR%" rmdir /s /q "%APP_DIR%"
if exist "%LOGGER_DIR%" rmdir /s /q "%LOGGER_DIR%"

echo [5/5] Removing uninstall metadata...
if exist "%META_DIR%" rmdir /s /q "%META_DIR%"

echo.
echo [SUCCESS] BehaviorShield and logger were fully removed.
exit /b 0
