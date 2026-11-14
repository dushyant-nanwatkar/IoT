@echo off
setlocal enabledelayedexpansion
title Sentinel AI Core Launcher

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Check if PowerShell is available for rich experience
where powershell >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start.ps1" %*
    if errorlevel 1 (
        echo.
        echo [ERROR] Sentinel exited with error code !ERRORLEVEL!.
        echo Press any key to exit...
        pause >nul
    )
    exit /b !ERRORLEVEL!
)

REM Fallback if PowerShell is unavailable
echo [INFO] PowerShell not detected. Running Command Prompt fallback launcher...

REM Find Python in venv
if exist "%SCRIPT_DIR%sentinel-laptop-core\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%sentinel-laptop-core\.venv\Scripts\python.exe"
) else if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo [INFO] Using Python: !PYTHON_EXE!
cd /d "%SCRIPT_DIR%sentinel-laptop-core"

REM Check for mock flag
if /i "%~1"=="-Mock" (
    "%PYTHON_EXE%" test_mock_phone.py
    goto :done
)
if /i "%~1"=="mock" (
    "%PYTHON_EXE%" test_mock_phone.py
    goto :done
)

"%PYTHON_EXE%" run_sentinel.py %*

:done
if errorlevel 1 (
    echo.
    echo [ERROR] Process exited with error code !ERRORLEVEL!.
    pause
)
