@echo off
REM =============================================================================
REM Prompt Evaluation System - Rollback Script (Windows)
REM =============================================================================
REM Usage:
REM   scripts\rollback.bat <backup_name>
REM
REM Examples:
REM   scripts\rollback.bat backup_20251207_130000
REM   scripts\rollback.bat   (Lists available backups)
REM
REM This script:
REM   1. Stops running server
REM   2. Restores database from backup
REM   3. Restores configuration from backup
REM   4. Verifies restoration
REM =============================================================================

setlocal enabledelayedexpansion

REM Configuration
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
cd /d "%PROJECT_DIR%"
set PROJECT_DIR=%CD%
set BACKUP_DIR=%PROJECT_DIR%\backups

echo ============================================
echo  Prompt Evaluation System - Rollback
echo ============================================
echo.

REM List available backups if no argument
if "%~1"=="" (
    echo Available backups:
    echo.
    if exist "%BACKUP_DIR%" (
        for /d %%D in ("%BACKUP_DIR%\backup_*") do echo   %%~nxD
    ) else (
        echo   ^(No backups directory^)
    )
    echo.
    echo Usage: %0 ^<backup_name^>
    echo Example: %0 backup_20251207_130000
    exit /b 0
)

set BACKUP_NAME=%~1
set BACKUP_PATH=%BACKUP_DIR%\%BACKUP_NAME%

REM Check backup exists
if not exist "%BACKUP_PATH%" (
    echo [ERROR] Backup not found: %BACKUP_PATH%
    exit /b 1
)

echo Backup to restore: %BACKUP_NAME%
echo.

REM Confirmation
set /p confirm="Are you sure you want to rollback? This will replace current data. (y/N): "
if /i not "%confirm%"=="y" (
    echo Rollback cancelled.
    exit /b 0
)

echo.

REM -----------------------------------------------------------------------------
REM Step 1: Stop server
REM -----------------------------------------------------------------------------
echo [Step 1] Stopping server

taskkill /f /im python.exe /fi "WINDOWTITLE eq *main.py*" >nul 2>&1
timeout /t 2 /nobreak >nul
echo [OK] Server stop attempted

echo.

REM -----------------------------------------------------------------------------
REM Step 2: Restore database
REM -----------------------------------------------------------------------------
echo [Step 2] Restoring database

if exist "%BACKUP_PATH%\app.db" (
    echo [INFO] Restoring database...
    if not exist "%PROJECT_DIR%\database" mkdir "%PROJECT_DIR%\database"
    copy "%BACKUP_PATH%\app.db" "%PROJECT_DIR%\database\app.db" >nul
    echo [OK] Database restored
) else (
    echo [WARN] No database in backup
)

echo.

REM -----------------------------------------------------------------------------
REM Step 3: Restore configuration
REM -----------------------------------------------------------------------------
echo [Step 3] Restoring configuration

if exist "%BACKUP_PATH%\.env" (
    echo [INFO] Restoring .env...
    copy "%BACKUP_PATH%\.env" "%PROJECT_DIR%\.env" >nul
    echo [OK] .env restored
)

if exist "%BACKUP_PATH%\config" (
    echo [INFO] Restoring config directory...
    rmdir /s /q "%PROJECT_DIR%\config" 2>nul
    xcopy "%BACKUP_PATH%\config" "%PROJECT_DIR%\config\" /E /I /Q >nul
    echo [OK] config directory restored
)

if exist "%BACKUP_PATH%\uploads" (
    echo [INFO] Restoring uploads directory...
    rmdir /s /q "%PROJECT_DIR%\uploads" 2>nul
    xcopy "%BACKUP_PATH%\uploads" "%PROJECT_DIR%\uploads\" /E /I /Q >nul
    echo [OK] uploads directory restored
)

echo.

REM -----------------------------------------------------------------------------
REM Step 4: Verify
REM -----------------------------------------------------------------------------
echo [Step 4] Verifying restoration

cd /d "%PROJECT_DIR%"

python -c "import sys; sys.path.insert(0, '.'); from backend.database import SessionLocal, Project, Job; db = SessionLocal(); pc = db.query(Project).count(); jc = db.query(Job).count(); db.close(); print(f'[OK] Database OK (Projects: {pc}, Jobs: {jc})')"
if errorlevel 1 (
    echo [ERROR] Verification failed
    exit /b 1
)

echo.

REM -----------------------------------------------------------------------------
REM Done
REM -----------------------------------------------------------------------------
echo ============================================
echo  Rollback completed successfully!
echo ============================================
echo.
echo To start the server:
echo   cd %PROJECT_DIR% ^&^& python main.py
echo.

endlocal
