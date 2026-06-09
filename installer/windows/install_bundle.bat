@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "APP_DIR=%ProgramFiles%\BehaviorShield"
set "LOGGER_DIR=%ProgramData%\SysLogger"
set "APP_EXE=BehaviorShield.exe"
set "LOGGER_EXE=logger.exe"

echo ============================================================
echo   BehaviorShield Bundle Installer
echo ============================================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Please run this script as Administrator.
    exit /b 1
)

if not exist "%SCRIPT_DIR%%APP_EXE%" (
    echo [ERROR] Missing %APP_EXE% next to installer.
    exit /b 1
)
if not exist "%SCRIPT_DIR%%LOGGER_EXE%" (
    echo [ERROR] Missing %LOGGER_EXE% next to installer.
    exit /b 1
)

echo [1/4] Creating install directories...
if not exist "%APP_DIR%" mkdir "%APP_DIR%"
if not exist "%LOGGER_DIR%" mkdir "%LOGGER_DIR%"

echo [2/4] Copying application files...
copy /Y "%SCRIPT_DIR%%APP_EXE%" "%APP_DIR%\%APP_EXE%" >nul
copy /Y "%SCRIPT_DIR%%LOGGER_EXE%" "%LOGGER_DIR%\%LOGGER_EXE%" >nul
copy /Y "%SCRIPT_DIR%register_logger_service.bat" "%APP_DIR%\register_logger_service.bat" >nul
copy /Y "%SCRIPT_DIR%unregister_logger_service.bat" "%APP_DIR%\unregister_logger_service.bat" >nul
copy /Y "%SCRIPT_DIR%uninstall_bundle.bat" "%APP_DIR%\uninstall_bundle.bat" >nul
copy /Y "%SCRIPT_DIR%start_behavior_shield.bat" "%APP_DIR%\start_behavior_shield.bat" >nul

echo [3/4] Registering logger background task...
call "%SCRIPT_DIR%register_logger_service.bat"
if errorlevel 1 (
    echo [ERROR] Logger background registration failed.
    exit /b 1
)

echo [4/4] Finalizing install...
if not exist "%ProgramData%\BehaviorShield" mkdir "%ProgramData%\BehaviorShield"
copy /Y "%SCRIPT_DIR%uninstall_bundle.bat" "%ProgramData%\BehaviorShield\uninstall_bundle.bat" >nul

echo.
echo [SUCCESS] Installation complete.
echo.
echo App location:     %APP_DIR%\%APP_EXE%
echo Logger DB path:   %LOGGER_DIR%\logs.db
echo Uninstall script: %ProgramData%\BehaviorShield\uninstall_bundle.bat
echo.
echo Launch app with:
echo   "%APP_DIR%\%APP_EXE%"
echo.
exit /b 0
