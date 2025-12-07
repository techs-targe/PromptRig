@echo off
REM =============================================================================
REM Prompt Evaluation System - Deployment Script (Windows)
REM =============================================================================
REM Usage:
REM   scripts\deploy.bat <github-zip-url-or-local-path>
REM
REM Examples:
REM   scripts\deploy.bat https://github.com/user/repo/archive/refs/heads/main.zip
REM   scripts\deploy.bat C:\temp\30_driven_win-main.zip
REM
REM This script:
REM   1. Creates backup of current installation
REM   2. Extracts new version
REM   3. Preserves database and configuration
REM   4. Updates dependencies
REM   5. Runs database migrations
REM   6. Verifies deployment
REM =============================================================================

setlocal enabledelayedexpansion

REM Configuration
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
cd /d "%PROJECT_DIR%"
set PROJECT_DIR=%CD%
set BACKUP_DIR=%PROJECT_DIR%\backups

REM Generate timestamp
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /format:list') do set datetime=%%I
set TIMESTAMP=%datetime:~0,4%%datetime:~4,2%%datetime:~6,2%_%datetime:~8,2%%datetime:~10,2%%datetime:~12,2%
set BACKUP_NAME=backup_%TIMESTAMP%

echo ============================================
echo  Prompt Evaluation System - Deployment
echo ============================================
echo.
echo Project directory: %PROJECT_DIR%
echo Timestamp: %TIMESTAMP%
echo.

REM -----------------------------------------------------------------------------
REM Step 0: Pre-deployment checks
REM -----------------------------------------------------------------------------
echo [Step 0] Pre-deployment checks

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    exit /b 1
)
echo [OK] Python found

REM Check pip
pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip is not installed or not in PATH
    exit /b 1
)
echo [OK] pip found

REM Check if source is provided
if "%~1"=="" (
    echo [ERROR] Usage: %0 ^<github-zip-url-or-local-path^>
    echo.
    echo Examples:
    echo   %0 https://github.com/user/repo/archive/refs/heads/main.zip
    echo   %0 C:\temp\30_driven_win-main.zip
    exit /b 1
)

set SOURCE=%~1
echo [INFO] Source: %SOURCE%

REM Stop existing server if running
echo [INFO] Stopping existing server if running...
taskkill /f /im python.exe /fi "WINDOWTITLE eq *main.py*" >nul 2>&1
timeout /t 2 /nobreak >nul

echo [OK] Pre-deployment checks passed
echo.

REM -----------------------------------------------------------------------------
REM Step 1: Create backup
REM -----------------------------------------------------------------------------
echo [Step 1] Creating backup

if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
mkdir "%BACKUP_DIR%\%BACKUP_NAME%"

REM Backup database
if exist "%PROJECT_DIR%\database\app.db" (
    echo [INFO] Backing up database...
    copy "%PROJECT_DIR%\database\app.db" "%BACKUP_DIR%\%BACKUP_NAME%\app.db" >nul
    echo [OK] Database backed up
) else (
    echo [WARN] No database found to backup
)

REM Backup configuration
if exist "%PROJECT_DIR%\.env" (
    echo [INFO] Backing up .env...
    copy "%PROJECT_DIR%\.env" "%BACKUP_DIR%\%BACKUP_NAME%\.env" >nul
    echo [OK] .env backed up
)

if exist "%PROJECT_DIR%\config" (
    echo [INFO] Backing up config directory...
    xcopy "%PROJECT_DIR%\config" "%BACKUP_DIR%\%BACKUP_NAME%\config\" /E /I /Q >nul
    echo [OK] config directory backed up
)

REM Backup uploads directory
if exist "%PROJECT_DIR%\uploads" (
    echo [INFO] Backing up uploads directory...
    xcopy "%PROJECT_DIR%\uploads" "%BACKUP_DIR%\%BACKUP_NAME%\uploads\" /E /I /Q >nul
    echo [OK] uploads directory backed up
)

REM Create backup manifest
echo Backup created: %TIMESTAMP% > "%BACKUP_DIR%\%BACKUP_NAME%\MANIFEST.txt"
echo Source: %SOURCE% >> "%BACKUP_DIR%\%BACKUP_NAME%\MANIFEST.txt"
dir "%BACKUP_DIR%\%BACKUP_NAME%" >> "%BACKUP_DIR%\%BACKUP_NAME%\MANIFEST.txt"

echo [OK] Backup created at: %BACKUP_DIR%\%BACKUP_NAME%
echo.

REM -----------------------------------------------------------------------------
REM Step 2: Download/Extract new version
REM -----------------------------------------------------------------------------
echo [Step 2] Downloading/Extracting new version

set TEMP_DIR=%TEMP%\deploy_%TIMESTAMP%
mkdir "%TEMP_DIR%"
echo [INFO] Temp directory: %TEMP_DIR%

REM Check if source is URL or local file
echo %SOURCE% | findstr /i "^http" >nul
if not errorlevel 1 (
    echo [INFO] Downloading from URL...
    curl -L -o "%TEMP_DIR%\source.zip" "%SOURCE%"
    if errorlevel 1 (
        echo [ERROR] Download failed
        exit /b 1
    )
) else (
    echo [INFO] Copying from local path...
    copy "%SOURCE%" "%TEMP_DIR%\source.zip" >nul
    if errorlevel 1 (
        echo [ERROR] Copy failed
        exit /b 1
    )
)

echo [INFO] Extracting archive...
powershell -command "Expand-Archive -Path '%TEMP_DIR%\source.zip' -DestinationPath '%TEMP_DIR%\extracted' -Force"
if errorlevel 1 (
    echo [ERROR] Extraction failed
    exit /b 1
)

REM Find extracted directory
for /d %%D in ("%TEMP_DIR%\extracted\*") do set EXTRACTED_DIR=%%D
echo [INFO] Extracted to: %EXTRACTED_DIR%
echo [OK] Archive extracted
echo.

REM -----------------------------------------------------------------------------
REM Step 3: Update code files (preserve data)
REM -----------------------------------------------------------------------------
echo [Step 3] Updating code files

REM Remove old code files (but not data)
echo [INFO] Removing old code files...
cd /d "%PROJECT_DIR%"
if exist "app" rmdir /s /q "app" 2>nul
if exist "backend" rmdir /s /q "backend" 2>nul
if exist "docs" rmdir /s /q "docs" 2>nul
if exist "scripts" rmdir /s /q "scripts" 2>nul
for %%f in (*.py *.txt *.md) do if not "%%f"=="requirements.txt" del /q "%%f" 2>nul

REM Copy new code files
echo [INFO] Copying new code files...
xcopy "%EXTRACTED_DIR%\*" "%PROJECT_DIR%\" /E /I /Q /Y >nul

REM Restore preserved files from backup
echo [INFO] Restoring preserved data...

REM Restore database
if exist "%BACKUP_DIR%\%BACKUP_NAME%\app.db" (
    if not exist "%PROJECT_DIR%\database" mkdir "%PROJECT_DIR%\database"
    copy "%BACKUP_DIR%\%BACKUP_NAME%\app.db" "%PROJECT_DIR%\database\app.db" >nul
    echo [OK] Database restored
)

REM Restore .env
if exist "%BACKUP_DIR%\%BACKUP_NAME%\.env" (
    copy "%BACKUP_DIR%\%BACKUP_NAME%\.env" "%PROJECT_DIR%\.env" >nul
    echo [OK] .env restored
)

REM Restore config
if exist "%BACKUP_DIR%\%BACKUP_NAME%\config" (
    xcopy "%BACKUP_DIR%\%BACKUP_NAME%\config" "%PROJECT_DIR%\config\" /E /I /Q /Y >nul
    echo [OK] config directory restored
)

REM Restore uploads
if exist "%BACKUP_DIR%\%BACKUP_NAME%\uploads" (
    xcopy "%BACKUP_DIR%\%BACKUP_NAME%\uploads" "%PROJECT_DIR%\uploads\" /E /I /Q /Y >nul
    echo [OK] uploads directory restored
)

echo [OK] Code files updated
echo.

REM -----------------------------------------------------------------------------
REM Step 4: Update dependencies
REM -----------------------------------------------------------------------------
echo [Step 4] Updating dependencies

cd /d "%PROJECT_DIR%"

REM Activate virtual environment if exists
if exist "venv\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment...
    call venv\Scripts\activate.bat
)

REM Update dependencies
echo [INFO] Installing/updating dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Dependency installation failed
    exit /b 1
)

echo [OK] Dependencies updated
echo.

REM -----------------------------------------------------------------------------
REM Step 5: Run database migrations
REM -----------------------------------------------------------------------------
echo [Step 5] Running database migrations

cd /d "%PROJECT_DIR%"

python -c "import sys; sys.path.insert(0, '.'); from backend.database import init_db; init_db(); print('[OK] Database initialized/migrated successfully')"
if errorlevel 1 (
    echo [ERROR] Database migration failed
    echo.
    echo To rollback, run:
    echo   scripts\rollback.bat %BACKUP_NAME%
    exit /b 1
)

echo [OK] Database migrations completed
echo.

REM -----------------------------------------------------------------------------
REM Step 6: Verify deployment
REM -----------------------------------------------------------------------------
echo [Step 6] Verifying deployment

cd /d "%PROJECT_DIR%"

python -c "import sys; sys.path.insert(0, '.'); from backend.database import SessionLocal, Project, Job; db = SessionLocal(); pc = db.query(Project).count(); jc = db.query(Job).count(); db.close(); print(f'[OK] Database connection OK (Projects: {pc}, Jobs: {jc})'); from main import app; print('[OK] FastAPI app importable')"
if errorlevel 1 (
    echo [ERROR] Deployment verification failed
    echo.
    echo To rollback, run:
    echo   scripts\rollback.bat %BACKUP_NAME%
    exit /b 1
)

echo [OK] Deployment verified
echo.

REM -----------------------------------------------------------------------------
REM Cleanup
REM -----------------------------------------------------------------------------
echo [INFO] Cleaning up temp files...
rmdir /s /q "%TEMP_DIR%" 2>nul

REM -----------------------------------------------------------------------------
REM Done
REM -----------------------------------------------------------------------------
echo ============================================
echo  Deployment completed successfully!
echo ============================================
echo.
echo Backup location: %BACKUP_DIR%\%BACKUP_NAME%
echo.
echo To start the server:
echo   cd %PROJECT_DIR% ^&^& python main.py
echo.
echo To rollback if needed:
echo   scripts\rollback.bat %BACKUP_NAME%
echo.

endlocal
