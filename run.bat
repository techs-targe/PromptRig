@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo PromptRig - Starting Application
echo ============================================================
echo.

if not exist venv (
    echo ERROR: Virtual environment not found
    echo Please run setup.bat first
    echo.
    pause
    exit /b 1
)

echo Activating virtual environment...
call venv\Scripts\activate

echo Starting server on http://localhost:9200
echo Press Ctrl+C to stop
echo ============================================================
echo.

REM Set PYTHONPATH to include project root for module imports
set PYTHONPATH=%~dp0

REM Use python -m to ensure correct module path resolution
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 9200

pause
