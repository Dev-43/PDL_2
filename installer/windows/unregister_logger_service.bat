@echo off
setlocal EnableExtensions

set "SERVICE_ID=BehaviorShieldLogger"
set "TASK_NAME=BehaviorShieldLogger"
set "LOGGER_DIR=%ProgramData%\SysLogger"
set "WATCHDOG_CMD=%LOGGER_DIR%\logger_watchdog.cmd"

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator privileges are required.
    exit /b 1
)

echo [*] Removing logger startup task...
schtasks /end /tn "%TASK_NAME%" >nul 2>&1
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

if exist "%LOGGER_DIR%\%SERVICE_ID%.exe" "%LOGGER_DIR%\%SERVICE_ID%.exe" stop >nul 2>&1
if exist "%LOGGER_DIR%\%SERVICE_ID%.exe" "%LOGGER_DIR%\%SERVICE_ID%.exe" uninstall >nul 2>&1
sc stop "%SERVICE_ID%" >nul 2>&1
sc delete "%SERVICE_ID%" >nul 2>&1

del /f /q "%LOGGER_DIR%\%SERVICE_ID%.exe" >nul 2>&1
del /f /q "%LOGGER_DIR%\%SERVICE_ID%.xml" >nul 2>&1
del /f /q "%LOGGER_DIR%\%SERVICE_ID%.wrapper.log" >nul 2>&1
del /f /q "%LOGGER_DIR%\%SERVICE_ID%.out*" >nul 2>&1
del /f /q "%LOGGER_DIR%\%SERVICE_ID%.err*" >nul 2>&1
if exist "%WATCHDOG_CMD%" del /f /q "%WATCHDOG_CMD%" >nul 2>&1
taskkill /F /IM logger.exe >nul 2>&1

echo [SUCCESS] Logger background task removed.
exit /b 0
