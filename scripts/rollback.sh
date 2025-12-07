#!/bin/bash
#=============================================================================
# Prompt Evaluation System - Rollback Script (Linux/Mac)
#=============================================================================
# Usage:
#   ./scripts/rollback.sh <backup_name>
#
# Examples:
#   ./scripts/rollback.sh backup_20251207_130000
#   ./scripts/rollback.sh   # Lists available backups
#
# This script:
#   1. Stops running server
#   2. Restores database from backup
#   3. Restores configuration from backup
#   4. Verifies restoration
#=============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE} Prompt Evaluation System - Rollback${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# List available backups if no argument
if [ -z "$1" ]; then
    echo -e "${YELLOW}Available backups:${NC}"
    echo ""
    if [ -d "$BACKUP_DIR" ]; then
        ls -la "$BACKUP_DIR" | grep "^d" | grep "backup_" | awk '{print "  " $NF}'
        if [ $(ls -d "$BACKUP_DIR"/backup_* 2>/dev/null | wc -l) -eq 0 ]; then
            echo "  (No backups found)"
        fi
    else
        echo "  (No backups directory)"
    fi
    echo ""
    echo -e "Usage: $0 <backup_name>"
    echo -e "Example: $0 backup_20251207_130000"
    exit 0
fi

BACKUP_NAME="$1"
BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"

# Check backup exists
if [ ! -d "$BACKUP_PATH" ]; then
    echo -e "${RED}[ERROR]${NC} Backup not found: $BACKUP_PATH"
    exit 1
fi

echo -e "Backup to restore: ${GREEN}$BACKUP_NAME${NC}"
echo ""

# Confirmation
read -p "Are you sure you want to rollback? This will replace current data. (y/N): " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Rollback cancelled."
    exit 0
fi

echo ""

#-----------------------------------------------------------------------------
# Step 1: Stop server
#-----------------------------------------------------------------------------
echo -e "${YELLOW}Step 1: Stopping server${NC}"

if pgrep -f "python.*main.py" > /dev/null; then
    echo "[INFO] Stopping server..."
    pkill -f "python.*main.py" || true
    sleep 2
    echo -e "${GREEN}[OK]${NC} Server stopped"
else
    echo "[INFO] Server not running"
fi

echo ""

#-----------------------------------------------------------------------------
# Step 2: Restore database
#-----------------------------------------------------------------------------
echo -e "${YELLOW}Step 2: Restoring database${NC}"

if [ -f "$BACKUP_PATH/app.db" ]; then
    echo "[INFO] Restoring database..."
    mkdir -p "$PROJECT_DIR/database"
    cp "$BACKUP_PATH/app.db" "$PROJECT_DIR/database/app.db"
    echo -e "${GREEN}[OK]${NC} Database restored"
else
    echo -e "${YELLOW}[WARN]${NC} No database in backup"
fi

echo ""

#-----------------------------------------------------------------------------
# Step 3: Restore configuration
#-----------------------------------------------------------------------------
echo -e "${YELLOW}Step 3: Restoring configuration${NC}"

if [ -f "$BACKUP_PATH/.env" ]; then
    echo "[INFO] Restoring .env..."
    cp "$BACKUP_PATH/.env" "$PROJECT_DIR/.env"
    echo -e "${GREEN}[OK]${NC} .env restored"
fi

if [ -d "$BACKUP_PATH/config" ]; then
    echo "[INFO] Restoring config directory..."
    rm -rf "$PROJECT_DIR/config"
    cp -r "$BACKUP_PATH/config" "$PROJECT_DIR/"
    echo -e "${GREEN}[OK]${NC} config directory restored"
fi

if [ -d "$BACKUP_PATH/uploads" ]; then
    echo "[INFO] Restoring uploads directory..."
    rm -rf "$PROJECT_DIR/uploads"
    cp -r "$BACKUP_PATH/uploads" "$PROJECT_DIR/"
    echo -e "${GREEN}[OK]${NC} uploads directory restored"
fi

echo ""

#-----------------------------------------------------------------------------
# Step 4: Verify
#-----------------------------------------------------------------------------
echo -e "${YELLOW}Step 4: Verifying restoration${NC}"

cd "$PROJECT_DIR"

python3 << 'PYEOF'
import sys
sys.path.insert(0, '.')

from backend.database import SessionLocal, Project, Job

db = SessionLocal()
try:
    project_count = db.query(Project).count()
    job_count = db.query(Job).count()
    print(f"[OK] Database OK (Projects: {project_count}, Jobs: {job_count})")
except Exception as e:
    print(f"[ERROR] Database error: {e}")
    sys.exit(1)
finally:
    db.close()
PYEOF

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR]${NC} Verification failed"
    exit 1
fi

echo ""

#-----------------------------------------------------------------------------
# Done
#-----------------------------------------------------------------------------
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} Rollback completed successfully!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "To start the server:"
echo -e "  ${BLUE}cd $PROJECT_DIR && python main.py${NC}"
echo ""
