# Installation Guide / インストールガイド

## Quick Start (Windows)

### 1. Install Python

Download and install Python 3.10-3.12 from [python.org](https://www.python.org/downloads/)

**Important:** Check "Add Python to PATH" during installation

### 2. Clone Repository

```cmd
git clone https://github.com/techs-targe/PromptRig.git
cd PromptRig
```

### 3. One-Click Setup (Windows)

Double-click `setup.bat` or run:

```cmd
setup.bat
```

This will:
- Create virtual environment
- Install dependencies
- Create `.env` file template
- Initialize database

### 4. Configure API Keys

Edit `.env` file:

```bash
# Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-azure-api-key
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment-name
AZURE_OPENAI_API_VERSION=2024-02-15-preview

# Optional: Separate deployments for GPT-5 models
AZURE_OPENAI_GPT5_MINI_DEPLOYMENT_NAME=your-gpt5-mini-deployment
AZURE_OPENAI_GPT5_NANO_DEPLOYMENT_NAME=your-gpt5-nano-deployment

# OpenAI Configuration (Optional)
OPENAI_API_KEY=your-openai-api-key

# Database
DATABASE_PATH=database/app.db

# Default Model
ACTIVE_LLM_MODEL=azure-gpt-4.1
```

### 5. Run Application

Double-click `run.bat` or run:

```cmd
run.bat
```

Open browser: http://localhost:9200

---

## Manual Installation (All Platforms)

### Prerequisites

- Python 3.10-3.12
- pip (included with Python)
- Git

### Windows

#### 1. Create Virtual Environment

```cmd
python -m venv venv
venv\Scripts\activate
```

#### 2. Install Dependencies

```cmd
pip install -r requirements.txt
```

#### 3. Configure Environment

Copy `.env.example` to `.env` and edit with your API keys:

```cmd
copy .env.example .env
notepad .env
```

#### 4. Run Application

```cmd
python main.py
```

### Linux / macOS

#### 1. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

#### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 3. Configure Environment

```bash
cp .env.example .env
nano .env
```

#### 4. Run Application

```bash
python main.py
```

---

## Batch Files (Windows Helper Scripts)

### setup.bat
```batch
@echo off
echo Creating virtual environment...
python -m venv venv
call venv\Scripts\activate

echo Installing dependencies...
pip install -r requirements.txt

echo Creating .env file...
if not exist .env (
    copy .env.example .env
    echo Please edit .env file with your API keys
) else (
    echo .env file already exists
)

echo Setup complete!
pause
```

### run.bat
```batch
@echo off
call venv\Scripts\activate
python main.py
pause
```

---

## Verification

After starting the application, you should see:

```
============================================================
Prompt Evaluation System - Phase 2 COMPLETE
============================================================
Starting server on http://127.0.0.1:9200

Phase 2 Features:
  ✓ Multiple project management
  ✓ Prompt/parser revision tracking
  ✓ Excel dataset import
  ✓ Batch execution
  ✓ System settings API
  ✓ Job progress tracking
============================================================
```

Access the web interface at: **http://localhost:9200**

---

## Troubleshooting

### Port 9200 Already in Use

Edit `main.py` to change the port:

```python
uvicorn.run(app, host="127.0.0.1", port=9201)
```

### Virtual Environment Issues (Windows)

If `venv\Scripts\activate` fails:

```cmd
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Missing Dependencies

```cmd
pip install --upgrade pip
pip install -r requirements.txt
```

### Database Initialization

If database is corrupted:

1. Stop the application
2. Delete `database/` folder
3. Restart the application (database will be recreated)

---

## Development Mode

Run with auto-reload:

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 9200
```

---

## Updating

```bash
git pull origin main
pip install -r requirements.txt --upgrade
```
