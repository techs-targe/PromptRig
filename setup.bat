@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo PromptRig Setup
echo ============================================================
echo.

echo [1/4] Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment
    echo Python 3.10-3.12 is required
    echo.
    pause
    exit /b 1
)

echo.
echo [2/4] Activating virtual environment...
call venv\Scripts\activate

echo.
echo [3/4] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    echo.
    pause
    exit /b 1
)

echo.
echo [4/4] Creating configuration file...
if not exist .env (
    (
        echo # Azure OpenAI Configuration
        echo AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
        echo AZURE_OPENAI_API_KEY=your-azure-api-key
        echo AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment-name
        echo AZURE_OPENAI_API_VERSION=2024-02-15-preview
        echo.
        echo # Optional: Separate deployments for GPT-5 models
        echo #AZURE_OPENAI_GPT5_MINI_DEPLOYMENT_NAME=your-gpt5-mini-deployment
        echo #AZURE_OPENAI_GPT5_NANO_DEPLOYMENT_NAME=your-gpt5-nano-deployment
        echo.
        echo # OpenAI Configuration (Optional^)
        echo #OPENAI_API_KEY=your-openai-api-key
        echo.
        echo # Database
        echo DATABASE_PATH=database/app.db
        echo.
        echo # Default Model
        echo ACTIVE_LLM_MODEL=azure-gpt-4.1
    ) > .env
    echo Created .env file
    echo Please edit .env with your API keys
) else (
    echo .env file already exists
)

echo.
echo ============================================================
echo Setup complete!
echo ============================================================
echo.
echo Next steps:
echo 1. Edit .env file with your API keys
echo 2. Run run.bat to start the application
echo.
pause
