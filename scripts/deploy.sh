#!/bin/bash
#=============================================================================
# Prompt Evaluation System - Deployment Script (Linux/Mac)
#=============================================================================
# Usage:
#   ./scripts/deploy.sh <github-zip-url-or-local-path>
#
# Examples:
#   ./scripts/deploy.sh https://github.com/user/repo/archive/refs/heads/main.zip
#   ./scripts/deploy.sh /tmp/30_driven_win-main.zip
#
# This script:
#   1. Creates backup of current installation
#   2. Extracts new version
#   3. Preserves database and configuration
#   4. Updates dependencies
#   5. Runs database migrations
#   6. Verifies deployment
#=============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="backup_$TIMESTAMP"

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE} Prompt Evaluation System - Deployment${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""
echo -e "Project directory: ${GREEN}$PROJECT_DIR${NC}"
echo -e "Timestamp: ${GREEN}$TIMESTAMP${NC}"
echo ""

#-----------------------------------------------------------------------------
# Helper functions
#-----------------------------------------------------------------------------
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_command() {
    if ! command -v $1 &> /dev/null; then
        log_error "$1 is not installed"
        exit 1
    fi
}

#-----------------------------------------------------------------------------
# Step 0: Pre-deployment checks
#-----------------------------------------------------------------------------
echo -e "${YELLOW}Step 0: Pre-deployment checks${NC}"

# Check required commands
check_command python3
check_command pip3
check_command unzip

# Check if source is provided
if [ -z "$1" ]; then
    log_error "Usage: $0 <github-zip-url-or-local-path>"
    echo ""
    echo "Examples:"
    echo "  $0 https://github.com/user/repo/archive/refs/heads/main.zip"
    echo "  $0 /tmp/30_driven_win-main.zip"
    exit 1
fi

SOURCE="$1"
log_info "Source: $SOURCE"

# Stop existing server if running
if pgrep -f "python.*main.py" > /dev/null; then
    log_warn "Stopping existing server..."
    pkill -f "python.*main.py" || true
    sleep 2
fi

log_success "Pre-deployment checks passed"
echo ""

#-----------------------------------------------------------------------------
# Step 1: Create backup
#-----------------------------------------------------------------------------
echo -e "${YELLOW}Step 1: Creating backup${NC}"

mkdir -p "$BACKUP_DIR/$BACKUP_NAME"

# Backup database
if [ -f "$PROJECT_DIR/database/app.db" ]; then
    log_info "Backing up database..."
    cp "$PROJECT_DIR/database/app.db" "$BACKUP_DIR/$BACKUP_NAME/app.db"
    log_success "Database backed up"
else
    log_warn "No database found to backup"
fi

# Backup configuration
if [ -f "$PROJECT_DIR/.env" ]; then
    log_info "Backing up .env..."
    cp "$PROJECT_DIR/.env" "$BACKUP_DIR/$BACKUP_NAME/.env"
    log_success ".env backed up"
fi

if [ -d "$PROJECT_DIR/config" ]; then
    log_info "Backing up config directory..."
    cp -r "$PROJECT_DIR/config" "$BACKUP_DIR/$BACKUP_NAME/config"
    log_success "config directory backed up"
fi

# Backup uploads directory
if [ -d "$PROJECT_DIR/uploads" ]; then
    log_info "Backing up uploads directory..."
    cp -r "$PROJECT_DIR/uploads" "$BACKUP_DIR/$BACKUP_NAME/uploads"
    log_success "uploads directory backed up"
fi

# Create backup manifest
echo "Backup created: $TIMESTAMP" > "$BACKUP_DIR/$BACKUP_NAME/MANIFEST.txt"
echo "Source: $SOURCE" >> "$BACKUP_DIR/$BACKUP_NAME/MANIFEST.txt"
ls -la "$BACKUP_DIR/$BACKUP_NAME" >> "$BACKUP_DIR/$BACKUP_NAME/MANIFEST.txt"

log_success "Backup created at: $BACKUP_DIR/$BACKUP_NAME"
echo ""

#-----------------------------------------------------------------------------
# Step 2: Download/Extract new version
#-----------------------------------------------------------------------------
echo -e "${YELLOW}Step 2: Downloading/Extracting new version${NC}"

TEMP_DIR=$(mktemp -d)
log_info "Temp directory: $TEMP_DIR"

# Download if URL, or copy if local file
if [[ "$SOURCE" == http* ]]; then
    log_info "Downloading from URL..."
    curl -L -o "$TEMP_DIR/source.zip" "$SOURCE"
else
    log_info "Copying from local path..."
    cp "$SOURCE" "$TEMP_DIR/source.zip"
fi

log_info "Extracting archive..."
unzip -q "$TEMP_DIR/source.zip" -d "$TEMP_DIR"

# Find extracted directory (GitHub creates a subdirectory)
EXTRACTED_DIR=$(find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)
if [ -z "$EXTRACTED_DIR" ]; then
    log_error "Could not find extracted directory"
    exit 1
fi

log_info "Extracted to: $EXTRACTED_DIR"
log_success "Archive extracted"
echo ""

#-----------------------------------------------------------------------------
# Step 3: Update code files (preserve data)
#-----------------------------------------------------------------------------
echo -e "${YELLOW}Step 3: Updating code files${NC}"

# Files/directories to preserve (not overwrite)
PRESERVE_LIST=(
    "database/app.db"
    ".env"
    "config/config.yaml"
    "uploads"
    "backups"
    "venv"
    "__pycache__"
    "*.pyc"
)

# Remove old code files (but not data)
log_info "Removing old code files..."
cd "$PROJECT_DIR"
for item in app backend docs scripts *.py *.txt *.md; do
    if [ -e "$item" ]; then
        rm -rf "$item"
    fi
done

# Copy new code files
log_info "Copying new code files..."
cp -r "$EXTRACTED_DIR"/* "$PROJECT_DIR/"

# Restore preserved files from backup
log_info "Restoring preserved data..."

# Restore database
if [ -f "$BACKUP_DIR/$BACKUP_NAME/app.db" ]; then
    mkdir -p "$PROJECT_DIR/database"
    cp "$BACKUP_DIR/$BACKUP_NAME/app.db" "$PROJECT_DIR/database/app.db"
    log_success "Database restored"
fi

# Restore .env
if [ -f "$BACKUP_DIR/$BACKUP_NAME/.env" ]; then
    cp "$BACKUP_DIR/$BACKUP_NAME/.env" "$PROJECT_DIR/.env"
    log_success ".env restored"
fi

# Restore config
if [ -d "$BACKUP_DIR/$BACKUP_NAME/config" ]; then
    cp -r "$BACKUP_DIR/$BACKUP_NAME/config" "$PROJECT_DIR/"
    log_success "config directory restored"
fi

# Restore uploads
if [ -d "$BACKUP_DIR/$BACKUP_NAME/uploads" ]; then
    cp -r "$BACKUP_DIR/$BACKUP_NAME/uploads" "$PROJECT_DIR/"
    log_success "uploads directory restored"
fi

log_success "Code files updated"
echo ""

#-----------------------------------------------------------------------------
# Step 4: Update dependencies
#-----------------------------------------------------------------------------
echo -e "${YELLOW}Step 4: Updating dependencies${NC}"

cd "$PROJECT_DIR"

# Activate virtual environment if exists
if [ -d "venv" ]; then
    log_info "Activating virtual environment..."
    source venv/bin/activate
fi

# Update dependencies
log_info "Installing/updating dependencies..."
pip3 install -r requirements.txt --quiet

log_success "Dependencies updated"
echo ""

#-----------------------------------------------------------------------------
# Step 5: Run database migrations
#-----------------------------------------------------------------------------
echo -e "${YELLOW}Step 5: Running database migrations${NC}"

cd "$PROJECT_DIR"

# Run migration via Python
python3 << 'PYEOF'
import sys
sys.path.insert(0, '.')

from backend.database import init_db, migrate_db

print("Running database initialization and migrations...")
try:
    init_db()
    print("✓ Database initialized/migrated successfully")
except Exception as e:
    print(f"✗ Migration error: {e}")
    sys.exit(1)
PYEOF

if [ $? -ne 0 ]; then
    log_error "Database migration failed"
    echo ""
    echo -e "${YELLOW}To rollback, run:${NC}"
    echo "  ./scripts/rollback.sh $BACKUP_NAME"
    exit 1
fi

log_success "Database migrations completed"
echo ""

#-----------------------------------------------------------------------------
# Step 6: Verify deployment
#-----------------------------------------------------------------------------
echo -e "${YELLOW}Step 6: Verifying deployment${NC}"

cd "$PROJECT_DIR"

# Quick verification
python3 << 'PYEOF'
import sys
sys.path.insert(0, '.')

print("Verifying deployment...")

# Check imports
try:
    from backend.database import SessionLocal, Project, Job
    print("✓ Database models importable")
except Exception as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)

# Check database connection
try:
    db = SessionLocal()
    project_count = db.query(Project).count()
    job_count = db.query(Job).count()
    db.close()
    print(f"✓ Database connection OK (Projects: {project_count}, Jobs: {job_count})")
except Exception as e:
    print(f"✗ Database error: {e}")
    sys.exit(1)

# Check FastAPI app
try:
    from main import app
    print("✓ FastAPI app importable")
except Exception as e:
    print(f"✗ App error: {e}")
    sys.exit(1)

print("\n✓ Deployment verification passed!")
PYEOF

if [ $? -ne 0 ]; then
    log_error "Deployment verification failed"
    echo ""
    echo -e "${YELLOW}To rollback, run:${NC}"
    echo "  ./scripts/rollback.sh $BACKUP_NAME"
    exit 1
fi

log_success "Deployment verified"
echo ""

#-----------------------------------------------------------------------------
# Cleanup
#-----------------------------------------------------------------------------
log_info "Cleaning up temp files..."
rm -rf "$TEMP_DIR"

#-----------------------------------------------------------------------------
# Done
#-----------------------------------------------------------------------------
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} Deployment completed successfully!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "Backup location: ${BLUE}$BACKUP_DIR/$BACKUP_NAME${NC}"
echo ""
echo -e "To start the server:"
echo -e "  ${BLUE}cd $PROJECT_DIR && python main.py${NC}"
echo ""
echo -e "To rollback if needed:"
echo -e "  ${BLUE}./scripts/rollback.sh $BACKUP_NAME${NC}"
echo ""
