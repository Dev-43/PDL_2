@echo off
setlocal EnableExtensions

set "SERVICE_ID=BehaviorShieldLogger"
set "TASK_NAME=BehaviorShieldLogger"
set "LOGGER_DIR=%ProgramData%\SysLogger"
set "LOGGER_EXE=%LOGGER_DIR%\logger.exe"
set "WATCHDOG_CMD=%LOGGER_DIR%\logger_watchdog.cmd"

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator privileges are required.
    exit /b 1
)

if not exist "%LOGGER_DIR%" mkdir "%LOGGER_DIR%"

if not exist "%LOGGER_EXE%" (
    echo [ERROR] Missing logger executable: %LOGGER_EXE%
    exit /b 1
)

echo [*] Cleaning legacy WinSW logger service (if present)...
if exist "%LOGGER_DIR%\%SERVICE_ID%.exe" "%LOGGER_DIR%\%SERVICE_ID%.exe" stop >nul 2>&1
if exist "%LOGGER_DIR%\%SERVICE_ID%.exe" "%LOGGER_DIR%\%SERVICE_ID%.exe" uninstall >nul 2>&1
sc stop "%SERVICE_ID%" >nul 2>&1
sc delete "%SERVICE_ID%" >nul 2>&1
del /f /q "%LOGGER_DIR%\%SERVICE_ID%.exe" >nul 2>&1
del /f /q "%LOGGER_DIR%\%SERVICE_ID%.xml" >nul 2>&1
del /f /q "%LOGGER_DIR%\%SERVICE_ID%.wrapper.log" >nul 2>&1
del /f /q "%LOGGER_DIR%\%SERVICE_ID%.out*" >nul 2>&1
del /f /q "%LOGGER_DIR%\%SERVICE_ID%.err*" >nul 2>&1

echo [*] Creating startup watchdog script...
> "%WATCHDOG_CMD%" echo @echo off
>> "%WATCHDOG_CMD%" echo :loop
>> "%WATCHDOG_CMD%" echo "%LOGGER_EXE%" --db "%LOGGER_DIR%\logs.db"
>> "%WATCHDOG_CMD%" echo timeout /t 5 /nobreak ^>nul
>> "%WATCHDOG_CMD%" echo goto loop

echo [*] Registering startup task as SYSTEM...
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
schtasks /create /tn "%TASK_NAME%" /sc ONSTART /ru SYSTEM /rl HIGHEST ^
    /tr "\"%SystemRoot%\System32\cmd.exe\" /c \"\"%WATCHDOG_CMD%\"\"" /f >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Failed to create startup task.
    exit /b 1
)

schtasks /run /tn "%TASK_NAME%" >nul 2>&1

echo [SUCCESS] Logger background task installed and started.
echo         Task: %TASK_NAME%
echo         Executable: %LOGGER_EXE%
exit /b 0
