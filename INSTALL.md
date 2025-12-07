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

## Updating / アップデート

```bash
git pull origin main
pip install -r requirements.txt --upgrade
```

---

# Deployment Guide / デプロイガイド

This section explains how to deploy updates to a release server that already has an older version installed.

## Deployment Quick Start / デプロイクイックスタート

### Linux/Mac

```bash
# Download and deploy from GitHub
./scripts/deploy.sh https://github.com/user/repo/archive/refs/heads/main.zip

# Or deploy from local zip file
./scripts/deploy.sh /path/to/30_driven_win-main.zip
```

### Windows

```batch
REM Download and deploy from GitHub
scripts\deploy.bat https://github.com/user/repo/archive/refs/heads/main.zip

REM Or deploy from local zip file
scripts\deploy.bat C:\path\to\30_driven_win-main.zip
```

---

## What the Deployment Script Does

1. **Pre-deployment Checks**
   - Verifies Python and pip are installed
   - Stops any running server

2. **Creates Backup**
   - Database (`database/app.db`)
   - Configuration (`.env`, `config/`)
   - Uploaded files (`uploads/`)
   - Backup location: `backups/backup_YYYYMMDD_HHMMSS/`

3. **Updates Code**
   - Downloads/extracts new version
   - Replaces code files (app/, backend/, etc.)
   - Preserves database and configuration

4. **Updates Dependencies**
   - Runs `pip install -r requirements.txt`

5. **Runs Database Migrations**
   - Automatically applies schema changes
   - Preserves existing data

6. **Verifies Deployment**
   - Tests database connection
   - Tests application imports

---

## Manual Deployment Steps

If you prefer manual deployment:

### Step 1: Stop Server

```bash
# Linux
pkill -f "python.*main.py"

# Windows
taskkill /f /im python.exe
```

### Step 2: Backup Current Installation

```bash
# Create backup directory
mkdir -p backups/manual_backup

# Backup database
cp database/app.db backups/manual_backup/

# Backup configuration
cp .env backups/manual_backup/
cp -r config backups/manual_backup/

# Backup uploads
cp -r uploads backups/manual_backup/
```

### Step 3: Download New Version

```bash
# Option 1: Download from GitHub
curl -L -o new_version.zip https://github.com/user/repo/archive/refs/heads/main.zip

# Option 2: Copy from local
# Copy the zip file to the server
```

### Step 4: Extract New Version

```bash
# Extract to temp directory
unzip new_version.zip -d /tmp/new_version

# Find extracted directory (GitHub creates subdirectory)
ls /tmp/new_version/
```

### Step 5: Update Code Files

```bash
# Remove old code files (NOT database/config)
rm -rf app backend scripts *.py *.txt *.md

# Copy new code files
cp -r /tmp/new_version/30_driven_win-main/* .

# Restore database
cp backups/manual_backup/app.db database/

# Restore configuration
cp backups/manual_backup/.env .
cp -r backups/manual_backup/config .
cp -r backups/manual_backup/uploads .
```

### Step 6: Update Dependencies

```bash
# Activate virtual environment (if used)
source venv/bin/activate  # Linux
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

### Step 7: Run Database Migrations

```bash
python -c "
import sys
sys.path.insert(0, '.')
from backend.database import init_db
init_db()
print('Database migrated successfully')
"
```

### Step 8: Start Server

```bash
python main.py
```

---

## Database Migrations

The system automatically handles database schema changes:

### Current Migrations

| Column | Table | Description |
|--------|-------|-------------|
| `merged_csv_output` | jobs | Stores merged CSV output for batch jobs |
| `model_name` | jobs | Stores LLM model name used for execution |

### How Migrations Work

1. On startup, `init_db()` calls `migrate_db()`
2. `migrate_db()` checks existing columns vs expected schema
3. Missing columns are added automatically
4. Existing data is preserved

---

## Rollback Procedure

If deployment fails or issues occur:

### Using Rollback Script

```bash
# Linux/Mac
./scripts/rollback.sh backup_20251207_130000

# Windows
scripts\rollback.bat backup_20251207_130000

# List available backups
./scripts/rollback.sh     # Linux
scripts\rollback.bat      # Windows
```

### Manual Rollback

```bash
# Stop server
pkill -f "python.*main.py"

# Restore database
cp backups/backup_YYYYMMDD_HHMMSS/app.db database/

# Restore configuration
cp backups/backup_YYYYMMDD_HHMMSS/.env .
cp -r backups/backup_YYYYMMDD_HHMMSS/config .

# Start server
python main.py
```

---

## Deployment Troubleshooting

### "Database migration failed"

Check the error message. Common issues:

1. **Permission denied**: Ensure write access to `database/` directory
2. **Locked database**: Stop all server processes first
3. **Corrupt database**: Restore from backup

```bash
# Check database integrity
sqlite3 database/app.db "PRAGMA integrity_check;"
```

### Configuration Lost

Restore from backup:

```bash
cp backups/backup_YYYYMMDD_HHMMSS/.env .
```

---

## File Structure After Deployment

```
project_root/
├── main.py                 # Entry point
├── requirements.txt        # Dependencies
├── .env                    # Configuration (preserved)
├── app/                    # Frontend (updated)
├── backend/                # Backend (updated)
├── scripts/                # Deployment scripts (updated)
│   ├── deploy.sh           # Linux deployment
│   ├── deploy.bat          # Windows deployment
│   ├── rollback.sh         # Linux rollback
│   └── rollback.bat        # Windows rollback
├── database/
│   └── app.db              # SQLite database (preserved)
├── uploads/                # Uploaded files (preserved)
├── config/                 # Configuration (preserved)
└── backups/                # Backup history
    └── backup_YYYYMMDD_HHMMSS/
        ├── app.db
        ├── .env
        ├── config/
        ├── uploads/
        └── MANIFEST.txt
```

---

## Best Practices

1. **Always backup before deployment**
   - The script does this automatically
   - Keep at least 3 recent backups

2. **Test in staging first**
   - Deploy to a test environment before production

3. **Monitor after deployment**
   - Check server logs for errors
   - Verify functionality works

4. **Keep .env secure**
   - Never commit to git
   - Store API keys securely

5. **Regular backups**
   - Beyond deployment, schedule regular database backups
