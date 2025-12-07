# Deployment Guide / デプロイガイド

This guide explains how to deploy updates to a release server that already has an older version installed.

## Quick Start / クイックスタート

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
rm -rf app backend docs scripts *.py *.txt *.md

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

### Adding New Migrations

Edit `backend/database/database.py`:

```python
def migrate_db():
    # ... existing code ...

    # Add new migration
    if 'new_column' not in columns:
        print("Adding new_column to jobs table...")
        db.execute(text('ALTER TABLE jobs ADD COLUMN new_column TEXT'))
        db.commit()
```

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

## Troubleshooting

### "Database migration failed"

Check the error message. Common issues:

1. **Permission denied**: Ensure write access to `database/` directory
2. **Locked database**: Stop all server processes first
3. **Corrupt database**: Restore from backup

```bash
# Check database integrity
sqlite3 database/app.db "PRAGMA integrity_check;"
```

### "Module not found"

Dependencies not installed:

```bash
pip install -r requirements.txt
```

### "Address already in use"

Server already running:

```bash
# Find process
lsof -i :9200  # Linux
netstat -ano | findstr :9200  # Windows

# Kill process
kill <PID>  # Linux
taskkill /PID <PID> /F  # Windows
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
├── docs/                   # Documentation (updated)
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
