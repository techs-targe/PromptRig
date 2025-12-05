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

REM Use python main.py instead of uvicorn directly
REM This ensures sys.path is set correctly before any imports
REM and avoids reload subprocess issues on Windows
python main.py

pause
