#!/bin/bash
# =============================================================================
# deploy_from_dev.sh
#
# Run this script ON THE PRODUCTION SERVER.
# It will:
#   1. Back up current files + module directories
#   2. Pull new versions from the dev server via SCP
#   3. Clean __pycache__ (prevent stale bytecode conflicts)
#   4. Install Python dependencies
#   5. Run creds encryption migration (idempotent)
#   6. Restart proxy daemons
#   7. Restart the Flask app
#
# Usage:
#   chmod +x deploy_from_dev.sh
#   ./deploy_from_dev.sh
# =============================================================================

# Note: no 'set -e' — we handle errors explicitly per step

# -----------------------------------------------------------------------------
# CONFIG — edit these before running
# -----------------------------------------------------------------------------
DEV_USER="root"
DEV_HOST="194.233.73.24"                        # ← Public IP of your dev server
DEV_PORT="21212"                                 # ← Custom SSH port on dev server
DEV_PATH="/root/apps/nagiosDashboard"

PROD_PATH="/svr/dashboard-nagios"               # ← Production app path (OpenRC service)
SERVICE_NAME="dashboard-nagios"                 # ← OpenRC service name

# SSH key (optional). Leave empty to use password prompt.
# Set to key path if you've run ssh-copy-id, e.g. ~/.ssh/id_ed25519
SSH_KEY=""

# SSH ControlMaster socket — reuses one connection for all SCP calls
# so password is only asked ONCE even without a key
CTRL_SOCKET="/tmp/deploy_ssh_ctl_$$"
SSH_OPTS="-P $DEV_PORT -o StrictHostKeyChecking=no -o ControlMaster=auto -o ControlPath=$CTRL_SOCKET -o ControlPersist=60"
if [ -n "$SSH_KEY" ]; then
    SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
fi
# -----------------------------------------------------------------------------

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Cleanup SSH socket on exit
cleanup() {
    rm -f "$CTRL_SOCKET" 2>/dev/null
}
trap cleanup EXIT

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  Nagios Dashboard — Deploy from Dev Server ${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Validate config
if [ -z "$DEV_HOST" ]; then
    fail "DEV_HOST is not set. Please edit this script and fill in the dev server IP."
fi

if [ ! -d "$PROD_PATH" ]; then
    fail "PROD_PATH '$PROD_PATH' does not exist on this server."
fi

# -----------------------------------------------------------------------------
# STEP 1: Create a timestamped backup directory
# -----------------------------------------------------------------------------
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$PROD_PATH/config/backups/deploy_backup_$TIMESTAMP"
mkdir -p "$BACKUP_DIR"
log "Backup directory: $BACKUP_DIR"

FILES_TO_UPDATE=(
    "app.py"
    "proxy.py"
    "templates/base.html"
    "templates/dashboard.html"
    "templates/edit_config.html"
    "templates/host_manager.html"
    "templates/login.html"
    "templates/monitoring.html"
    "templates/monitoring_intens.html"
    "templates/monitoring_settings.html"
    "templates/nagios_view.html"
    "templates/servers.html"
    "templates/setup.html"
    "templates/stage_history.html"
    "templates/users.html"
    "templates/user_permissions.html"
    "templates/active_users.html"
    "templates/global_settings.html"
    "templates/activity_logs.html"
    "requirements.txt"
    "migrate_encrypt_creds.py"
    "migrate_stages_to_db.py"
    "start_proxy_daemon.py"
    "start_proxy.sh"
    "preflight_check.sh"
    "README.md"
    "USER_GUIDE.md"
    "DEVELOPMENT.md"
)

MODULE_DIRS=(
    "services"
    "utils"
    "blueprints"
)

# Whole directories. static/assets (alarm sounds) and config/ are not in this list.
ASSET_DIRS=(
    "static/css"
    "static/js"
)
TREE_BACKUP_DIRS=(
    "templates"
    "static/css"
    "static/js"
)

# HOLD 2026-08-21: Intensive Monitoring must not land on Prod.
# FILES_TO_UPDATE already omits the UI/worker, but MODULE_DIRS is a full
# `scp -r` of services/ and blueprints/, which would copy intensive.py,
# intensive_db.py, and intensive-worker.initd unless we strip them after sync.
INTENSIVE_HOLD_EXCLUDE=(
    "intensive_worker.py"
    "blueprints/intensive.py"
    "services/intensive_db.py"
    "services/intensive-worker.initd"
    "templates/intensive.html"
    "static/js/intensive.js"
    "static/css/intensive.css"
)

is_intensive_hold_file() {
    local rel="$1"
    local ex
    for ex in "${INTENSIVE_HOLD_EXCLUDE[@]}"; do
        if [ "$rel" = "$ex" ]; then
            return 0
        fi
    done
    return 1
}

strip_intensive_hold_files() {
    log "Ensuring Intensive Monitoring HOLD files are not on Prod..."
    local rel target
    for rel in "${INTENSIVE_HOLD_EXCLUDE[@]}"; do
        target="$PROD_PATH/$rel"
        if [ -e "$target" ]; then
            rm -f "$target"
            ok "Removed (HOLD): $rel"
        fi
    done
}

log "Backing up current files..."
for FILE in "${FILES_TO_UPDATE[@]}"; do
    if is_intensive_hold_file "$FILE"; then
        warn "Skipping HOLD file (not deployed): $FILE"
        continue
    fi
    SRC="$PROD_PATH/$FILE"
    DEST="$BACKUP_DIR/$(basename $FILE)"
    if [ -f "$SRC" ]; then
        cp "$SRC" "$DEST"
        ok "Backed up: $FILE"
    else
        warn "File not found, skipping backup: $FILE"
    fi
done

log "Backing up module directories..."
for DIR in "${MODULE_DIRS[@]}"; do
    SRC="$PROD_PATH/$DIR"
    DEST="$BACKUP_DIR/$DIR"
    if [ -d "$SRC" ]; then
        cp -r "$SRC" "$DEST"
        ok "Backed up: $DIR/"
    else
        warn "Directory not found, skipping backup: $DIR/"
    fi
done

log "Backing up templates and static css/js..."
for DIR in "${TREE_BACKUP_DIRS[@]}"; do
    SRC="$PROD_PATH/$DIR"
    DEST="$BACKUP_DIR/$DIR"
    if [ -d "$SRC" ]; then
        mkdir -p "$(dirname "$DEST")"
        cp -r "$SRC" "$DEST"
        ok "Backed up: $DIR/"
    else
        warn "Directory not found, skipping backup: $DIR/"
    fi
done
echo ""

# -----------------------------------------------------------------------------
# STEP 1b: Cleanup old backups (keep latest 3)
# -----------------------------------------------------------------------------
BACKUPS_PARENT="$PROD_PATH/config/backups"
KEEP=3

for PREFIX in deploy_backup creds_migration; do
    OLD_BACKUPS=($(ls -dt "$BACKUPS_PARENT"/${PREFIX}_* 2>/dev/null))
    if [ ${#OLD_BACKUPS[@]} -gt $KEEP ]; then
        for OLD in "${OLD_BACKUPS[@]:$KEEP}"; do
            rm -rf "$OLD"
            log "Cleaned up old backup: $(basename $OLD)"
        done
    fi
done
echo ""

# -----------------------------------------------------------------------------
# STEP 2: Pull new files from dev server via SCP
# -----------------------------------------------------------------------------
log "Pulling updated files from dev server ($DEV_USER@$DEV_HOST)..."
echo ""

for FILE in "${FILES_TO_UPDATE[@]}"; do
    if is_intensive_hold_file "$FILE"; then
        warn "Skipping HOLD file (not deployed): $FILE"
        continue
    fi
    SRC="${DEV_USER}@${DEV_HOST}:${DEV_PATH}/${FILE}"
    DEST="$PROD_PATH/$FILE"

    # Ensure destination directory exists (e.g. templates/)
    mkdir -p "$(dirname $DEST)"

    log "Copying: $FILE"
    if scp $SSH_OPTS "$SRC" "$DEST"; then
        ok "Updated: $FILE"
    else
        # Restore backup on failure
        BACKUP_FILE="$BACKUP_DIR/$(basename $FILE)"
        warn "SCP failed for $FILE — restoring backup..."
        if [ -f "$BACKUP_FILE" ]; then
            cp "$BACKUP_FILE" "$DEST"
            warn "Backup restored for $FILE"
        else
            fail "No backup found for $FILE and SCP failed. Check manually."
        fi
        fail "Deployment aborted due to SCP failure on $FILE."
    fi
done
echo ""

# -----------------------------------------------------------------------------
# STEP 2b: Pull module directories (services/, utils/, blueprints/)
# -----------------------------------------------------------------------------
log "Pulling module directories from dev server..."
for DIR in "${MODULE_DIRS[@]}"; do
    SRC="${DEV_USER}@${DEV_HOST}:${DEV_PATH}/${DIR}"
    DEST="$PROD_PATH/$DIR"

    # Remove old directory (backup already saved in Step 1)
    rm -rf "$DEST"

    log "Syncing: $DIR/"
    if scp -r $SSH_OPTS "$SRC" "$PROD_PATH/"; then
        ok "Updated: $DIR/"
    else
        # Restore backup on failure
        BACKUP_DIR_MOD="$BACKUP_DIR/$DIR"
        warn "SCP failed for $DIR/ — restoring backup..."
        if [ -d "$BACKUP_DIR_MOD" ]; then
            cp -r "$BACKUP_DIR_MOD" "$DEST"
            warn "Backup restored for $DIR/"
        else
            fail "No backup found for $DIR/ and SCP failed. Check manually."
        fi
        fail "Deployment aborted due to SCP failure on $DIR/."
    fi
done

# static/css and static/js are full directory copies. static/assets/sound
# and config/ are left untouched.
log "Pulling static css/js directories from dev server..."
for DIR in "${ASSET_DIRS[@]}"; do
    SRC="${DEV_USER}@${DEV_HOST}:${DEV_PATH}/${DIR}"
    DEST="$PROD_PATH/$DIR"
    PARENT="$(dirname "$DEST")"

    rm -rf "$DEST"
    mkdir -p "$PARENT"

    log "Syncing: $DIR/"
    if scp -r $SSH_OPTS "$SRC" "$PARENT/"; then
        ok "Updated: $DIR/"
    else
        BACKUP_DIR_MOD="$BACKUP_DIR/$DIR"
        warn "SCP failed for $DIR/ — restoring backup..."
        if [ -d "$BACKUP_DIR_MOD" ]; then
            rm -rf "$DEST"
            mkdir -p "$PARENT"
            cp -r "$BACKUP_DIR_MOD" "$DEST"
            warn "Backup restored for $DIR/"
        else
            fail "No backup found for $DIR/ and SCP failed. Check manually."
        fi
        fail "Deployment aborted due to SCP failure on $DIR/."
    fi
done

# Full directory copies can bring Intensive HOLD files inside services/,
# blueprints/, static/css/, or static/js/. Strip them after sync.
strip_intensive_hold_files
echo ""

# -----------------------------------------------------------------------------
# STEP 3: Clean __pycache__ (prevent stale bytecode conflicts)
# -----------------------------------------------------------------------------
log "Cleaning __pycache__ directories..."
find "$PROD_PATH" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PROD_PATH" -name "*.pyc" -delete 2>/dev/null || true
ok "Bytecode cache cleaned"
echo ""

# -----------------------------------------------------------------------------
# STEP 4: Stop the service (needed before pip install & migration)
# -----------------------------------------------------------------------------
log "Stopping OpenRC service: $SERVICE_NAME..."
if rc-service "$SERVICE_NAME" stop; then
    ok "Service stopped"
else
    warn "Service stop returned non-zero (may not have been running)"
fi
sleep 2
echo ""

# -----------------------------------------------------------------------------
# STEP 5: Install Python dependencies
# -----------------------------------------------------------------------------
log "Installing Python dependencies..."
if pip install -r "$PROD_PATH/requirements.txt" --break-system-packages -q 2>/dev/null || \
   pip install -r "$PROD_PATH/requirements.txt" -q 2>/dev/null; then
    ok "Dependencies installed"
else
    warn "pip install had warnings (may already be satisfied)"
fi
echo ""

# -----------------------------------------------------------------------------
# STEP 6: Run creds encryption migration (idempotent — safe to re-run)
# -----------------------------------------------------------------------------
log "Running creds encryption migration..."
if python3 "$PROD_PATH/migrate_encrypt_creds.py"; then
    ok "Migration complete"
else
    warn "Migration script returned non-zero (may have already been migrated)"
fi
echo ""

# -----------------------------------------------------------------------------
# STEP 7: Restart iframe proxy multiplexer (replaces per-container proxy.py)
# -----------------------------------------------------------------------------
log "Restarting Nagios iframe proxy multiplexer..."
if python3 "$PROD_PATH/start_proxy_daemon.py" restart; then
    ok "Proxy multiplexer restarted"
else
    warn "Proxy multiplexer failed to restart — check /tmp/nagios-proxy.log or /var/log/nagios-proxy.log"
fi
echo ""

# -----------------------------------------------------------------------------
# STEP 8: Verify new app.py can import before starting service
# -----------------------------------------------------------------------------
log "Verifying app module imports..."
# OpenRC sources /etc/conf.d/$SERVICE_NAME for the service. The check must
# use that same environment. Stay in a subshell and do not trace it.
if (
    set -a
    . "/etc/conf.d/$SERVICE_NAME"
    set +a
    cd "$PROD_PATH" && python3 -c "import sys; sys.path.insert(0, '$PROD_PATH'); from app import app; print(f'OK: {len(app.blueprints)} blueprints, {len(app.url_map._rules)} routes')"
) 2>&1; then
    ok "App module verification passed"
else
    warn "App module verification failed — rolling back app.py, modules, templates, and static..."
    cp "$BACKUP_DIR/app.py" "$PROD_PATH/app.py"
    for DIR in "${MODULE_DIRS[@]}" "${TREE_BACKUP_DIRS[@]}"; do
        BACKUP_DIR_MOD="$BACKUP_DIR/$DIR"
        if [ -d "$BACKUP_DIR_MOD" ]; then
            rm -rf "$PROD_PATH/$DIR"
            mkdir -p "$(dirname "$PROD_PATH/$DIR")"
            cp -r "$BACKUP_DIR_MOD" "$PROD_PATH/$DIR"
        fi
    done
    if rc-service "$SERVICE_NAME" start; then
        warn "Service restarted on restored code"
    else
        warn "Restored code but failed to restart $SERVICE_NAME"
    fi
    fail "App verification failed. Rolled back to backup. Aborting deploy."
fi
echo ""

# -----------------------------------------------------------------------------
# STEP 8b: Migrate host_stages.json → SQLite BEFORE starting Flask
# Must run while the service is stopped. If Flask starts first it can insert
# empty 'new' rows, then this script would SKIP and Prod notes/cs would be lost.
# -----------------------------------------------------------------------------
log "Migrating host stages JSON to SQLite (WAL)..."
if python3 "$PROD_PATH/migrate_stages_to_db.py"; then
    ok "Host stages migration complete"
else
    fail "Host stages migration failed. Service left stopped. JSON was not renamed. Aborting deploy."
fi
echo ""

# -----------------------------------------------------------------------------
# STEP 9: Start the service
# -----------------------------------------------------------------------------
log "Starting OpenRC service: $SERVICE_NAME..."
if rc-service "$SERVICE_NAME" start; then
    ok "Service started"
else
    # Rollback on failure
    warn "Service failed to start — rolling back..."
    rc-service "$SERVICE_NAME" stop 2>/dev/null || true
    cp "$BACKUP_DIR/app.py" "$PROD_PATH/app.py"
    for DIR in "${MODULE_DIRS[@]}" "${TREE_BACKUP_DIRS[@]}"; do
        BACKUP_DIR_MOD="$BACKUP_DIR/$DIR"
        if [ -d "$BACKUP_DIR_MOD" ]; then
            rm -rf "$PROD_PATH/$DIR"
            mkdir -p "$(dirname "$PROD_PATH/$DIR")"
            cp -r "$BACKUP_DIR_MOD" "$PROD_PATH/$DIR"
        fi
    done
    pip install -r "$BACKUP_DIR/requirements.txt" --break-system-packages -q 2>/dev/null || \
        pip install -r "$BACKUP_DIR/requirements.txt" -q 2>/dev/null
    rc-service "$SERVICE_NAME" start 2>/dev/null || true
    fail "Service failed to start. Rolled back to backup. Check logs: rc-service $SERVICE_NAME status"
fi

sleep 3

# Confirm it's running
if rc-service "$SERVICE_NAME" status | grep -q started; then
    ok "Service is running"
else
    warn "Service status unclear — check manually:"
    warn "  rc-service $SERVICE_NAME status"
fi

# Final health check
log "Running health check..."
sleep 2
# Read APP_PORT from services/config.py (single source of truth)
APP_PORT=$(python3 -c "import sys; sys.path.insert(0, '$PROD_PATH'); from services.config import APP_PORT; print(APP_PORT)" 2>/dev/null || echo "80")
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${APP_PORT}/health 2>/dev/null || echo "000")
if [ "$HEALTH" = "200" ]; then
    ok "Health check passed (HTTP 200)"
elif [ "$HEALTH" = "503" ]; then
    warn "Health check returned 503 (degraded) — app is running but some checks failed"
else
    warn "Health check returned HTTP $HEALTH — app may not be responding yet"
fi

# -----------------------------------------------------------------------------
# DONE
# -----------------------------------------------------------------------------
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Deployment complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  Backup saved at:  ${YELLOW}$BACKUP_DIR${NC}"
echo ""
echo -e "  To roll back:"
echo -e "  ${CYAN}rc-service $SERVICE_NAME stop${NC}"
echo -e "  ${CYAN}cp $BACKUP_DIR/app.py $PROD_PATH/app.py${NC}"
for DIR in "${MODULE_DIRS[@]}" "${TREE_BACKUP_DIRS[@]}"; do
    echo -e "  ${CYAN}rm -rf $PROD_PATH/$DIR && mkdir -p \$(dirname $PROD_PATH/$DIR) && cp -r $BACKUP_DIR/$DIR $PROD_PATH/$DIR${NC}"
done
echo -e "  ${CYAN}pip install -r $BACKUP_DIR/requirements.txt${NC}"
echo -e "  ${CYAN}rc-service $SERVICE_NAME start${NC}"
echo ""
