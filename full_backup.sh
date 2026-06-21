#!/bin/bash
# =============================================================================
# full_backup.sh
#
# Full backup script for Nagios Dashboard.
# Run on the PRODUCTION server.
#
# Backs up:
#   1. App code (app.py, services/, utils/, blueprints/, templates/, static/)
#   2. Config files (config/*.json, secret_key, activity_logs/)
#   3. Nagios host configs (localhost.cfg per container)
#   4. Docker metadata (container names, ports, image info)
#   5. Docker image (nagios-ldap:latest)
#   6. LDAP data (via slapcat from LDAP container)
#   7. Proxy logs (/tmp/proxy_*.log)
#
# Usage:
#   chmod +x full_backup.sh
#   ./full_backup.sh
#
# Output: /svr/dashboard-nagios/config/backups/full_backup_<timestamp>.tar.gz
# =============================================================================

set -o pipefail

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
PROD_PATH="/svr/dashboard-nagios"
BACKUP_BASE="$PROD_PATH/config/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_BASE/full_backup_$TIMESTAMP"
KEEP=3

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  Nagios Dashboard — Full Backup            ${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

mkdir -p "$BACKUP_DIR"
log "Backup directory: $BACKUP_DIR"
echo ""

# -----------------------------------------------------------------------------
# 1. App code
# -----------------------------------------------------------------------------
log "=== 1. Backing up app code ==="

APP_FILES=(
    "app.py"
    "proxy.py"
    "start_proxy.sh"
    "start_proxy_daemon.py"
    "migrate_encrypt_creds.py"
    "requirements.txt"
    "README.md"
    "deploy_from_dev.sh"
)

for FILE in "${APP_FILES[@]}"; do
    if [ -f "$PROD_PATH/$FILE" ]; then
        cp "$PROD_PATH/$FILE" "$BACKUP_DIR/"
        ok "$FILE"
    fi
done

for DIR in services utils blueprints templates static; do
    if [ -d "$PROD_PATH/$DIR" ]; then
        cp -r "$PROD_PATH/$DIR" "$BACKUP_DIR/$DIR"
        ok "$DIR/"
    fi
done
echo ""

# -----------------------------------------------------------------------------
# 2. Config files
# -----------------------------------------------------------------------------
log "=== 2. Backing up config files ==="

mkdir -p "$BACKUP_DIR/config"

# JSON configs + secret_key
for FILE in "$PROD_PATH/config/"*.json "$PROD_PATH/config/secret_key"; do
    if [ -f "$FILE" ]; then
        cp "$FILE" "$BACKUP_DIR/config/"
        ok "config/$(basename $FILE)"
    fi
done

# Activity logs (monthly files)
if [ -d "$PROD_PATH/config/activity_logs" ]; then
    cp -r "$PROD_PATH/config/activity_logs" "$BACKUP_DIR/config/activity_logs"
    ok "config/activity_logs/"
fi

# Legacy activity log
if [ -f "$PROD_PATH/config/activity_log.txt" ]; then
    cp "$PROD_PATH/config/activity_log.txt" "$BACKUP_DIR/config/"
    ok "config/activity_log.txt"
fi
echo ""

# -----------------------------------------------------------------------------
# 3. Nagios host configs (from Docker containers)
# -----------------------------------------------------------------------------
log "=== 3. Backing up Nagios host configs ==="

mkdir -p "$BACKUP_DIR/nagios_configs"

NAGIOS_COUNT=0
for container in $(docker ps -a --filter 'ancestor=nagios-ldap:latest' --format '{{.Names}}' 2>/dev/null); do
    config_path="/svr/$container/etc/objects/localhost.cfg"
    if [ -f "$config_path" ]; then
        cp "$config_path" "$BACKUP_DIR/nagios_configs/${container}_localhost.cfg"
        ok "$container → ${container}_localhost.cfg"
        NAGIOS_COUNT=$((NAGIOS_COUNT + 1))
    else
        # Try extracting from container
        if docker cp "$container:/opt/nagios/etc/objects/localhost.cfg" "$BACKUP_DIR/nagios_configs/${container}_localhost.cfg" 2>/dev/null; then
            ok "$container → ${container}_localhost.cfg (via docker cp)"
            NAGIOS_COUNT=$((NAGIOS_COUNT + 1))
        else
            warn "Could not backup config for $container"
        fi
    fi
done

if [ "$NAGIOS_COUNT" -eq 0 ]; then
    warn "No Nagios containers found"
fi
echo ""

# -----------------------------------------------------------------------------
# 4. Docker metadata
# -----------------------------------------------------------------------------
log "=== 4. Backing up Docker metadata ==="

mkdir -p "$BACKUP_DIR/docker"

# Container list
docker ps -a --filter 'ancestor=nagios-ldap:latest' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' > "$BACKUP_DIR/docker/containers.txt" 2>/dev/null
ok "docker/containers.txt"

# Full inspect for all nagios containers
for container in $(docker ps -a --filter 'ancestor=nagios-ldap:latest' --format '{{.Names}}' 2>/dev/null); do
    docker inspect "$container" > "$BACKUP_DIR/docker/inspect_${container}.json" 2>/dev/null
    ok "docker/inspect_${container}.json"
done

# Image info
docker images nagios-ldap:latest --format '{{.Repository}}:{{.Tag}} | {{.ID}} | {{.CreatedAt}} | {{.Size}}' > "$BACKUP_DIR/docker/image_info.txt" 2>/dev/null
ok "docker/image_info.txt"
echo ""

# -----------------------------------------------------------------------------
# 5. Docker image (nagios-ldap:latest)
# -----------------------------------------------------------------------------
log "=== 5. Backing up Docker image ==="

if docker images nagios-ldap:latest --format '{{.ID}}' 2>/dev/null | grep -q .; then
    log "Saving nagios-ldap:latest image (this may take a while)..."
    if docker save nagios-ldap:latest | gzip > "$BACKUP_DIR/docker/nagios-ldap_latest.tar.gz"; then
        ok "docker/nagios-ldap_latest.tar.gz ($(du -h "$BACKUP_DIR/docker/nagios-ldap_latest.tar.gz" | cut -f1))"
    else
        warn "Failed to save Docker image"
    fi
else
    warn "nagios-ldap:latest image not found"
fi
echo ""

# -----------------------------------------------------------------------------
# 6. LDAP data
# -----------------------------------------------------------------------------
log "=== 6. Backing up LDAP data ==="

LDAP_CONTAINER=$(docker ps --filter 'ancestor=osixia/openldap' --format '{{.Names}}' 2>/dev/null | head -1)
if [ -z "$LDAP_CONTAINER" ]; then
    LDAP_CONTAINER=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -i ldap | head -1)
fi

if [ -n "$LDAP_CONTAINER" ]; then
    if docker exec "$LDAP_CONTAINER" slapcat > "$BACKUP_DIR/docker/ldap_dump.ldif" 2>/dev/null; then
        ok "docker/ldap_dump.ldif ($(wc -l < "$BACKUP_DIR/docker/ldap_dump.ldif") entries)"
    else
        warn "slapcat failed — trying alternative method"
        # Try with explicit path
        docker exec "$LDAP_CONTAINER" /usr/sbin/slapcat > "$BACKUP_DIR/docker/ldap_dump.ldif" 2>/dev/null && \
            ok "docker/ldap_dump.ldif" || warn "LDAP backup failed"
    fi
else
    warn "LDAP container not found"
fi
echo ""

# -----------------------------------------------------------------------------
# 7. Proxy logs
# -----------------------------------------------------------------------------
log "=== 7. Backing up proxy logs ==="

mkdir -p "$BACKUP_DIR/logs"
PROXY_LOG_COUNT=0
for logfile in /tmp/proxy_*.log; do
    if [ -f "$logfile" ]; then
        cp "$logfile" "$BACKUP_DIR/logs/"
        PROXY_LOG_COUNT=$((PROXY_LOG_COUNT + 1))
    fi
done
if [ "$PROXY_LOG_COUNT" -gt 0 ]; then
    ok "logs/ ($PROXY_LOG_COUNT proxy log files)"
else
    warn "No proxy logs found"
fi
echo ""

# -----------------------------------------------------------------------------
# 8. Compress everything
# -----------------------------------------------------------------------------
log "=== 8. Compressing backup ==="

TARBALL="$BACKUP_BASE/full_backup_$TIMESTAMP.tar.gz"
cd "$BACKUP_BASE"
tar -czf "full_backup_$TIMESTAMP.tar.gz" "full_backup_$TIMESTAMP/"
TARBALL_SIZE=$(du -h "$TARBALL" | cut -f1)

# Remove uncompressed directory
rm -rf "$BACKUP_DIR"

ok "Compressed: $TARBALL ($TARBALL_SIZE)"
echo ""

# -----------------------------------------------------------------------------
# 9. Cleanup old backups (keep latest N)
# -----------------------------------------------------------------------------
log "=== 9. Cleaning up old full backups (keep latest $KEEP) ==="

OLD_BACKUPS=($(ls -dt "$BACKUP_BASE"/full_backup_*.tar.gz 2>/dev/null))
if [ ${#OLD_BACKUPS[@]} -gt $KEEP ]; then
    for OLD in "${OLD_BACKUPS[@]:$KEEP}"; do
        rm -f "$OLD"
        log "Removed: $(basename $OLD)"
    done
fi
echo ""

# -----------------------------------------------------------------------------
# DONE
# -----------------------------------------------------------------------------
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Backup complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  File:  ${YELLOW}$TARBALL${NC}"
echo -e "  Size:  ${YELLOW}$TARBALL_SIZE${NC}"
echo ""
echo -e "  To restore:"
echo -e "  ${CYAN}cd /tmp && tar -xzf $TARBALL${NC}"
echo -e "  ${CYAN}# Then copy files back to $PROD_PATH/${NC}"
echo ""
