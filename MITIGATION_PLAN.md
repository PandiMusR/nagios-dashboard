# Nagios Dashboard — Mitigation Plan for Production Risks

> Target: 5 critical risks from `DEPLOYMENT_SAFETY.md`  
> Status: PLAN ONLY — no implementation yet

---

## Overview

| # | Mitigation | Task Ref | Risk | Approach |
|---|---|---|---|---|
| 1 | Python 3.8 `tar.extractall` compat | Task 2.2 | ✅ RESOLVED | Prod is Python 3.12.12 — `filter='data'` works natively. See `PYTHON_UPGRADE_LOG.md`. |
| 2 | Deploy script template coverage | Task 1.5 | Silent breakage | Add 9 templates to `FILES_TO_UPDATE` |
| 3 | LDAP admin password env var check | Task 1.1 | Crash | Pre-flight script + graceful error in config.py |
| 4 | Password encryption migration order | Task 2.1 | Crash | Migration before deploy + backward-compatible decrypt |
| 5 | Permission checks rollout | Task 1.4 | User lockout | Audit-mode (log-only) → enforce-mode (block) |

---

## Mitigation 1: ✅ RESOLVED — Production Already Python 3.12

### Finding (2026-07-12)

Production server is Alpine 3.21.5 with Python 3.12.12 — NOT Python 3.8 as assumed.
`/usr/bin/python3 → python3.12`. `tar.extractall(filter='data')` is natively supported.

**See `PYTHON_UPGRADE_LOG.md` for full pre-flight check results.**

### Updated Approach for Task 2.2

Since BOTH dev (3.12.3) and prod (3.12.12) support `filter='data'`, use it directly:

**File: `blueprints/global_settings.py` — line 161**

```python
# BEFORE (line 159-161):
        with tarfile.open(backup_file, 'r:gz') as tar:
            tar.extractall('/tmp/restore_temp')

# AFTER:
        with tarfile.open(backup_file, 'r:gz') as tar:
            tar.extractall('/tmp/restore_temp', filter='data')
```

**No new file needed.** No `safe_extract()` fallback. One-line change.

### Verification

```bash
python3 -c "
import tarfile
import tempfile, os

# Verify filter='data' is supported
with tempfile.TemporaryDirectory() as tmp:
    tar_path = os.path.join(tmp, 'test.tar.gz')
    # Create test tar
    with tarfile.open(tar_path, 'w:gz') as tar:
        import io
        info = tarfile.TarInfo(name='test.txt')
        info.size = 0
        tar.addfile(info)
    # Test extraction with filter='data'
    dest = os.path.join(tmp, 'out')
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(tar_path, 'r:gz') as tar:
        tar.extractall(dest, filter='data')
    print('PASS: filter=data supported')
"
```

### No further action needed for this mitigation

Proceed to Mitigation 2.

---

## Mitigation 2: Deploy Script Template Coverage

### Problem

`deploy_from_dev.sh:87-102` defines `FILES_TO_UPDATE` — a whitelist of individual files SCP'd from dev to prod. Task 1.5 adds `{{ csrf_token() }}` to every template with `<form>`, but 9 templates are NOT in the whitelist. If these templates are modified but not deployed, they'll be missing the CSRF token → all forms on those pages will be rejected with 400 Bad Request.

**Templates receiving CSRF tokens that are MISSING from FILES_TO_UPDATE:**

| Template | Has `<form method="POST">`? | In FILES_TO_UPDATE? |
|---|---|---|
| `templates/servers.html` | Yes | ❌ |
| `templates/host_manager.html` | Yes | ❌ |
| `templates/users.html` | Yes | ❌ |
| `templates/login.html` | Yes | ❌ |
| `templates/setup.html` | Yes | ❌ |
| `templates/dashboard.html` | No forms (stats load via AJAX) | ❌ |
| `templates/monitoring_intens.html` | Yes (config forms) | ❌ |
| `templates/nagios_view.html` | No forms (view only) | ❌ |
| `templates/edit_config.html` | Yes (config editor) | ❌ |

### Options

#### Option A: Update FILES_TO_UPDATE (explicit whitelist)

Replace the existing `FILES_TO_UPDATE` block in `deploy_from_dev.sh:87-102`:

```bash
FILES_TO_UPDATE=(
    "app.py"
    "proxy.py"
    "templates/base.html"
    "templates/login.html"
    "templates/setup.html"
    "templates/dashboard.html"
    "templates/servers.html"
    "templates/host_manager.html"
    "templates/users.html"
    "templates/monitoring.html"
    "templates/monitoring_intens.html"
    "templates/monitoring_settings.html"
    "templates/user_permissions.html"
    "templates/active_users.html"
    "templates/global_settings.html"
    "templates/stage_history.html"
    "templates/activity_logs.html"
    "templates/nagios_view.html"
    "templates/edit_config.html"
    "requirements.txt"
    "migrate_encrypt_creds.py"
    "README.md"
    "USER_GUIDE.md"
)
```

**Pros:** Exact control over what gets deployed. If a template file is accidentally deleted from dev, deploy script catches it (`warn "File not found, skipping backup"`).  
**Cons:** Must manually maintain this list forever. Adding a new template = must update deploy script.

#### Option B: Replace whitelist with `rsync` for templates/

Replace the individual template entries in `FILES_TO_UPDATE` with a directory-level sync, and keep the individual entries for non-template files:

```bash
# In deploy_from_dev.sh, replace the per-template FILES_TO_UPDATE entries
# with a single rsync for templates/

# Remove all "templates/*.html" entries from FILES_TO_UPDATE, then add
# this after the FILES_TO_UPDATE loop:

log "Syncing templates directory..."
rsync -avz $SSH_OPTS \
    "$DEV_USER@$DEV_HOST:$DEV_PATH/templates/" \
    "$PROD_PATH/templates/" \
    --exclude='*_old.html' \
    --include='*.html' \
    --exclude='*'
```

**Pros:** Never need to update deploy script when templates change.  
**Cons:** SCP is already used for the SSH tunnel; rsync adds another tool dependency. Also, the CONTROL socket is already set up for SCP — rsync would need its own SSH config. Changes deploy behavior that currently works.

### Recommendation

**Option A ✓** — Update `FILES_TO_UPDATE` to include all 18 templates. The whitelist approach is safer because:

1. It matches the existing deploy pattern — no new tool dependencies
2. It reuses the existing `CONTROL_SSH` socket for SCP (no extra SSH connection)
3. It's auditable — `grep FILES_TO_UPDATE deploy_from_dev.sh` shows exactly what gets deployed
4. It handles file-not-found gracefully (existing `warn` fallback at line 118)
5. Templates rarely change — maintenance cost is negligible after this update

The full 18-template list is exactly the output of `ls templates/*.html | sed 's|templates/||' | sort` minus the `*_old.html` files which are being removed in Phase 4.

### Verification Step

```bash
# After updating FILES_TO_UPDATE, check all templates are covered:
cd /root/apps/nagiosDashboard

MISSING=$(comm -23 \
    <(ls templates/*.html | sed 's|templates/||' | grep -v '_old.html' | sort) \
    <(grep -A50 'FILES_TO_UPDATE' deploy_from_dev.sh | grep 'templates/' | xargs -n1 basename | sort))

if [ -z "$MISSING" ]; then
    echo "PASS: all templates in FILES_TO_UPDATE"
else
    echo "FAIL: missing templates from FILES_TO_UPDATE:"
    echo "$MISSING"
fi
```

---

## Mitigation 3: LDAP Admin Password Env Var Check

### Problem

`services/config.py:19` has `LDAP_ADMIN_PASSWORD = os.environ.get('LDAP_ADMIN_PASSWORD', 'admin')`. Task 1.1 changes this to `os.environ['LDAP_ADMIN_PASSWORD']` (no fallback). If the prod OpenRC service config doesn't export `LDAP_ADMIN_PASSWORD`, the app crashes on `import services.config` with a cryptic `KeyError: 'LDAP_ADMIN_PASSWORD'`.

### Solution

Two-part approach:

1. **Pre-flight check script** that runs BEFORE `rc-service restart` and validates all required env vars exist
2. **Graceful error in config.py** that catches the missing env var and logs a clear message before exiting

### Pre-flight Script

**New file: `pre_flight_check.sh`** (deployed alongside `deploy_from_dev.sh`)

```bash
#!/bin/sh
# pre_flight_check.sh — verify production environment before deploy
# Called by deploy_from_dev.sh BEFORE stopping the service
# Exit 0 = OK, exit 1 = block deploy

REQUIRED_VARS="LDAP_ADMIN_PASSWORD"
MISSING=""

for VAR in $REQUIRED_VARS; do
    if ! eval "test -n \"\${$VAR}\"" 2>/dev/null; then
        # Try OpenRC config file
        VALUE="$(grep "^export $VAR=" /etc/conf.d/dashboard-nagios 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'")"
        if [ -z "$VALUE" ]; then
            MISSING="$MISSING $VAR"
        fi
    fi
done

if [ -n "$MISSING" ]; then
    echo "ERROR: Required environment variables not set:$MISSING" >&2
    echo "Add them to /etc/conf.d/dashboard-nagios:" >&2
    for VAR in $MISSING; do
        echo "  export $VAR=\"your-value-here\"" >&2
    done
    exit 1
fi

echo "Pre-flight check PASSED"
exit 0
```

**Integration into `deploy_from_dev.sh`** — add after line 224 (after `log "Stopping OpenRC service..."`):

```bash
# Run pre-flight check before stopping service
log "Running pre-flight check..."
if ! bash "$DEV_PATH/pre_flight_check.sh"; then
    fail "Pre-flight check failed. Fix environment variables before deploying."
fi
```

Wait — the deploy script runs ON PROD and SCPs FROM dev. So the check should run on prod before stopping. The pre-flight script needs to be SCP'd to prod first, or it runs inline.

Let me revise: the pre-flight check should be an inline check at the top of `deploy_from_dev.sh`:

```bash
# Insert at line 69 (just before "STEP 1 — Backup current files"):

# STEP 0: Pre-flight check
log "STEP 0: Pre-flight environment check..."
MISSING_VARS=""
for VAR in LDAP_ADMIN_PASSWORD; do
    if ! eval "test -n \"\${$VAR:-}\"" 2>/dev/null; then
        CONF_VALUE="$(grep "^export $VAR=" /etc/conf.d/dashboard-nagios 2>/dev/null || true)"
        if [ -z "$CONF_VALUE" ]; then
            MISSING_VARS="$MISSING_VARS $VAR"
        fi
    fi
done
if [ -n "$MISSING_VARS" ]; then
    fail "Required env vars not set:$MISSING_VARS. Add them to /etc/conf.d/dashboard-nagios"
fi
ok "All required environment variables present"
```

### Code Fix in config.py

**File: `services/config.py` — replace lines 7 and 19**

```python
# BEFORE:
APP_PORT = int(os.environ.get('APP_PORT', '5000'))
# ...
LDAP_ADMIN_PASSWORD = os.environ.get('LDAP_ADMIN_PASSWORD', 'admin')

# AFTER:
import sys

def _require_env(name: str) -> str:
    """Get required env var, abort with clear message if missing."""
    value = os.environ.get(name)
    if not value:
        print(f'FATAL: Environment variable {name} is not set.', file=sys.stderr)
        print(f'Add "export {name}=<value>" to /etc/conf.d/dashboard-nagios', file=sys.stderr)
        sys.exit(1)
    return value

APP_PORT = int(os.environ.get('APP_PORT', '5000'))       # safe default for dev
LDAP_ADMIN_PASSWORD = _require_env('LDAP_ADMIN_PASSWORD')  # no default — must be set
```

This approach:
- Catches the missing env var at import time
- Prints a clear, actionable error message to stderr (visible in `rc-service` logs)
- Calls `sys.exit(1)` — the process terminates before Waitress starts, so `rc-service` reports failure
- `APP_PORT` keeps its default of `'5000'` — only `LDAP_ADMIN_PASSWORD` is made mandatory

### Full Env Var List

After scanning the entire codebase with `grep -rn "os.environ\|os.getenv" --include="*.py"`:

| Variable | File:Line | Used For | Required? | Default |
|---|---|---|---|---|
| `APP_PORT` | `services/config.py:7` | Flask listen port | No | `5000` |
| `LDAP_ADMIN_PASSWORD` | `services/config.py:19` | LDAP admin bind | **YES** | (was `admin`, now NONE) |

Only 2 environment variables in the entire codebase. Only `LDAP_ADMIN_PASSWORD` becomes mandatory after the fix.

> **AGENTS.md update needed:** Update line 382-383 to reflect that `LDAP_ADMIN_PASSWORD` now has no default and is required. Add `APP_PORT` default to `5000` in docs (line 381 says `80` but code says `5000`).

### Verification Step

```bash
# Test 1: Without env var, app should print FATAL and exit 1
unset LDAP_ADMIN_PASSWORD
python3 -c "from services.config import LDAP_ADMIN_PASSWORD" 2>&1 | grep -q "FATAL" && echo "PASS: graceful error" || echo "FAIL"

# Test 2: With env var, normal import works
export LDAP_ADMIN_PASSWORD="test-pass"
python3 -c "from services.config import LDAP_ADMIN_PASSWORD; print('PASS' if LDAP_ADMIN_PASSWORD == 'test-pass' else 'FAIL')"

# Test 3: Pre-flight check in deploy script
bash -c '
LDAP_ADMIN_PASSWORD=set; MISSING_VARS=""
for VAR in LDAP_ADMIN_PASSWORD; do
    if ! eval "test -n \"\${$VAR:-}\""; then MISSING_VARS="$MISSING_VARS $VAR"; fi
done
if [ -n "$MISSING_VARS" ]; then echo "FAIL: missing$MISSING_VARS"; else echo "PASS: pre-flight"; fi
'
```

---

## Mitigation 4: Password Encryption Migration Order

### Problem

`global_config.json` in production stores `nextcloud_password` and `uptime_kuma_password` as plaintext. After Task 2.1 code deploys, `services/nextcloud.py:19` and `services/uptime_kuma.py:18` call their existing `config.get()` paths, but `global_settings.py` write functions start calling `encrypt_value()` on password fields. If the migration runs AFTER the deploy, the decrypt path encounters plaintext and crashes.

Meanwhile, the existing `save_encrypted_json()` / `load_encrypted_json()` in `services/encryption.py` works on whole-dict level with `__ENC__` prefix — it's used for `user_passwords.json` and `nagios_creds_*.json`. For `global_config.json`, password fields need per-field encryption because the config file has mixed plaintext (domain, API key) and secret fields.

### Solution

Three-pronged approach:

1. **Migration script** encrypts plaintext passwords in `global_config.json` — run BEFORE code deploy
2. **Verification script** confirms all password fields have `__ENC__` prefix
3. **Backward-compatible decrypt** — `decrypt_value()` falls back to plaintext if value lacks `__ENC__` prefix (safe in both directions during transition)

### 3-Step Deployment Sequence

```
STEP A — RUN MIGRATION ON PROD (service stays running, code unchanged)
  SCP migrate_encrypt_global_config.py to prod
  ssh prod: python3 /svr/dashboard-nagios/migrate_encrypt_global_config.py
  Verify: `grep -c '__ENC__' /svr/dashboard-nagios/config/global_config.json` ≥ jumlah password fields

STEP B — VERIFY MIGRATION
  ssh prod: python3 /svr/dashboard-nagios/verify_global_config_encryption.py
  Must return "PASS: all password fields encrypted"

STEP C — DEPLOY NEW CODE
  ssh prod: cd /svr/dashboard-nagios && ./deploy_from_dev.sh
  New code uses decrypt_value() which handles both __ENC__ and plaintext (backward compatible)
```

### Migration Script

**New file: `migrate_encrypt_global_config.py`** (deploy to prod root)

```python
#!/usr/bin/env python3
"""Encrypt plaintext password fields in global_config.json.

Idempotent — skips fields already prefixed with __ENC__.
Backs up original to global_config.json.migration-backup before modifying.
"""
import json
import os
import sys
from datetime import datetime

# This runs on prod where APP_ROOT is /svr/dashboard-nagios
PROD_CONFIG = '/svr/dashboard-nagios/config/global_config.json'

if not os.path.exists(PROD_CONFIG):
    print(f'ERROR: {PROD_CONFIG} not found')
    sys.exit(1)

# --- bootstrap encryption (mirrors proxy.py approach) ---
import base64
import hashlib
from cryptography.fernet import Fernet

SECRET_KEY_PATH = '/svr/dashboard-nagios/config/secret_key'
with open(SECRET_KEY_PATH, 'r') as f:
    secret_key = f.read().strip()
key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
fernet = Fernet(key)

ENCRYPTED_MARKER = '__ENC__'


def encrypt_value(value: str) -> str:
    """Encrypt a string value, prefixing with __ENC__."""
    return ENCRYPTED_MARKER + fernet.encrypt(value.encode()).decode()


# --- load config ---
with open(PROD_CONFIG, 'r') as f:
    config = json.load(f)

# Backup
backup_path = PROD_CONFIG + '.migration-backup'
with open(backup_path, 'w') as f:
    json.dump(config, f, indent=2)
print(f'Backup saved to {backup_path}')

# Fields that contain passwords (check both old and new key names)
PASSWORD_FIELDS = [
    'nextcloud_password',
    'password',               # legacy Uptime Kuma key (might be 'password')
    'uptime_kuma_password',   # current Uptime Kuma key
]

changed = []
for field in PASSWORD_FIELDS:
    value = config.get(field)
    if value and isinstance(value, str) and not value.startswith(ENCRYPTED_MARKER):
        config[field] = encrypt_value(value)
        changed.append(field)
        print(f'  Encrypted: {field} ({value[:4]}... -> {config[field][:14]}...)')

if not changed:
    print('No plaintext passwords found — already migrated.')
else:
    with open(PROD_CONFIG, 'w') as f:
        json.dump(config, f, indent=2)
    print(f'Encrypted {len(changed)} field(s): {", ".join(changed)}')

print('Migration complete.')
```

> **Note:** `migrate_encrypt_global_config.py` must be added to `FILES_TO_UPDATE` in `deploy_from_dev.sh` OR SCP'd manually to prod.

### Verification Script

**New file: `verify_global_config_encryption.py`** (deploy alongside migration script)

```python
#!/usr/bin/env python3
"""Verify all password fields in global_config.json are encrypted."""
import json
import os
import sys

PROD_CONFIG = '/svr/dashboard-nagios/config/global_config.json'

PASSWORD_FIELDS = ['nextcloud_password', 'password', 'uptime_kuma_password']

with open(PROD_CONFIG, 'r') as f:
    config = json.load(f)

failures = []
for field in PASSWORD_FIELDS:
    value = config.get(field)
    if value and isinstance(value, str) and not value.startswith('__ENC__'):
        failures.append(f'{field} is NOT encrypted')

if failures:
    print('FAIL:')
    for f in failures:
        print(f'  {f}')
    sys.exit(1)

print('PASS: all password fields encrypted')
```

### Backward-Compatibility Patch

**File: `services/encryption.py` — add after `load_encrypted_json()` (around line 89)**

```python
def decrypt_value(value: str) -> str:
    """Decrypt a single value, falling back to plaintext if not encrypted.

    Safe to call on both encrypted and plaintext values — if the value
    doesn't have the __ENC__ marker, it's returned as-is.  This provides
    backward compatibility during the migration transition window.
    """
    if not isinstance(value, str):
        return value
    if not value.startswith(ENCRYPTED_MARKER):
        return value
    try:
        return _fernet.decrypt(value[len(ENCRYPTED_MARKER):].encode()).decode()
    except Exception:
        return value


def encrypt_value(value: str) -> str:
    """Encrypt a single value and prefix with __ENC__ marker."""
    return ENCRYPTED_MARKER + _fernet.encrypt(value.encode()).decode()
```

Then update the password consumers to use `decrypt_value()`:

**File: `services/nextcloud.py:19`**

```python
# BEFORE:
password = config.get('nextcloud_password', '')

# AFTER:
from services.encryption import decrypt_value
password = decrypt_value(config.get('nextcloud_password', ''))
```

**File: `services/uptime_kuma.py:18`**

```python
# BEFORE:
password = config.get('uptime_kuma_password', '')

# AFTER:
from services.encryption import decrypt_value
password = decrypt_value(config.get('uptime_kuma_password', ''))
```

**File: `blueprints/global_settings.py:262`**

```python
# BEFORE:
config['nextcloud_password'] = password

# AFTER:
from services.encryption import encrypt_value
config['nextcloud_password'] = encrypt_value(password)
```

**File: `blueprints/global_settings.py:333`**

```python
# BEFORE:
config['uptime_kuma_password'] = uptime_kuma_password

# AFTER:
config['uptime_kuma_password'] = encrypt_value(uptime_kuma_password)
```

> **AGENTS.md update needed:** Add `decrypt_value()` and `encrypt_value()` to the Encryption section (line 189-193). These are new public API functions for per-field encryption (vs `save_encrypted_json`/`load_encrypted_json` which encrypt entire files).

### Verification Step

```bash
# Step A: Test migration script (on dev)
cp config/global_config.json config/global_config.json.test-backup
python3 -c "
import json
with open('config/global_config.json') as f:
    c = json.load(f)
c['nextcloud_password'] = 'plaintext-test'
c['uptime_kuma_password'] = 'plaintext-test2'
with open('config/global_config.json', 'w') as f:
    json.dump(c, f, indent=2)
print('Wrote plaintext test values')
"
python3 migrate_encrypt_global_config.py
python3 verify_global_config_encryption.py
# Restore
cp config/global_config.json.test-backup config/global_config.json

# Step B: Test backward-compatible decrypt
python3 -c "
from services.encryption import encrypt_value, decrypt_value
plain = 'my-password'
enc = encrypt_value(plain)
# decrypt_value works on both
assert decrypt_value(plain) == plain, 'plaintext roundtrip failed'
assert decrypt_value(enc) == plain, 'encrypted roundtrip failed'
print('PASS: backward-compatible decrypt')
"
```

---

## Mitigation 5: Permission Checks Rollout

### Problem

Task 1.4 adds `check_permission()` calls to 25+ routes. Users who previously had access because there was NO permission check will suddenly get 403 Forbidden. The production `user_permissions.json` may have incomplete permission assignments. Deploying enforcement immediately could lock out legitimate users — including admins if their permission set is empty (admins bypass via role check, but if the LDAP group mapping breaks, they fall back to permission-based).

### Solution

Two-phase rollout controlled by a config toggle in `monitoring_config.json`:

- **Phase A (audit mode):** Deploy with `permission_check_mode: "audit"`. Permission checks LOG unauthorized attempts to `config/permission_audit.log` but ALLOW access. Run for 1-2 days, collect data.
- **Phase B (enforce mode):** After reviewing the audit log and ensuring all users have correct permissions in `user_permissions.json`, switch config to `permission_check_mode: "enforce"`. Permission checks now block (return 403).

### Two-Phase Rollout

```
Phase A Day 0   Deploy code with audit mode. monitor permission_audit.log.
Phase A Day 1   Review log — identify which users hit which protected routes.
                Fix user_permissions.json gaps.
Phase A Day 2   Confirm audit log is clean (no more unexpected blocks).
Phase B          Toggle config to enforce mode. Restart service.
Phase B+1        Monitor for 403 complaints.
```

### Code

**Modified file: `utils/permissions.py` — replace `check_permission()` at line 83**

```python
from __future__ import annotations

import os
import json
import logging
from datetime import datetime
from flask import session, request

from services.config import CONFIG_DIR, MONITORING_CONFIG_PATH, USER_PERMISSIONS_PATH

logger = logging.getLogger(__name__)

AUDIT_LOG_PATH = os.path.join(CONFIG_DIR, 'permission_audit.log')


def _get_permission_check_mode() -> str:
    """Read permission check mode from monitoring config. Default: 'audit'."""
    try:
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                return config.get('permission_check_mode', 'audit')
    except (json.JSONDecodeError, OSError):
        pass
    return 'audit'


def _log_permission_denial(permission: str, username: str) -> None:
    """Log a permission denial to the audit log."""
    entry = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'username': username,
        'permission': permission,
        'route': request.path,
        'method': request.method,
        'remote_addr': request.remote_addr
    }
    try:
        with open(AUDIT_LOG_PATH, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except OSError:
        pass


def check_permission(permission: str) -> bool:
    """Check if user has permission. Admin bypasses all checks.

    When permission_check_mode is 'audit', unauthorized access is
    logged but allowed.  When 'enforce', access is denied (returns False).
    """
    if session.get('role') == 'admin':
        return True

    has_permission = session.get('permissions', {}).get(permission, False)

    if not has_permission:
        mode = _get_permission_check_mode()
        username = session.get('username', 'unknown')
        _log_permission_denial(permission, username)

        if mode == 'enforce':
            logger.warning(
                f'Permission denied: {username} -> {permission} '
                f'({request.method} {request.path})'
            )
            return False
        else:
            logger.info(
                f'AUDIT: would deny {username} -> {permission} '
                f'({request.method} {request.path})'
            )
            return True  # audit mode: log but allow

    return True


# Existing functions below remain unchanged
# load_user_permissions(), get_default_permissions(), save_user_permissions(),
# save_user_password(), get_user_password()
```

**Config file update: `config/monitoring_config.json`**

The file already exists on prod (deploy script doesn't overwrite `config/`). Add this via the migration script or manual:

```json
{
    "... existing keys ...": "...",
    "permission_check_mode": "audit"
}
```

On Phase B, change `"audit"` to `"enforce"` and restart the service.

### Audit Log Format

**File: `config/permission_audit.log`** — JSONL (one JSON object per line)

```jsonl
{"timestamp": "2026-07-12T08:15:23Z", "username": "operator_joko", "permission": "servers", "route": "/servers/batch-start", "method": "POST", "remote_addr": "192.168.1.50"}
{"timestamp": "2026-07-12T08:16:01Z", "username": "staff_ani", "permission": "monitoring_settings", "route": "/monitoring-settings/edit-category", "method": "POST", "remote_addr": "192.168.1.51"}
```

Format: JSONL — easy to grep, easy to parse with `python3 -c "import json,sys; ..."`.

**Analysis commands:**

```bash
# Count denials by user
cat config/permission_audit.log | python3 -c "
import json, sys
from collections import Counter
counts = Counter()
for line in sys.stdin:
    d = json.loads(line)
    counts[(d['username'], d['permission'])] += 1
for (user, perm), n in counts.most_common():
    print(f'{user:20s} {perm:25s} {n:4d}')
"

# Check if admin is being blocked (shouldn't happen)
grep '"username":"admin"' config/permission_audit.log

# Check what routes are most frequently denied
cat config/permission_audit.log | python3 -c "
import json, sys
from collections import Counter
print(Counter(json.loads(l)['route'] for l in sys.stdin).most_common(10))
"
```

### Config Toggle Locations

| Location | Phase A Value | Phase B Value | How to change |
|---|---|---|---|
| `config/monitoring_config.json` `permission_check_mode` | `"audit"` | `"enforce"` | Manual edit on prod + `rc-service dashboard-nagios restart` |

### Verification Step

```bash
# Test 1: Audit mode logs but allows
python3 -c "
from flask import Flask
from flask.sessions import SecureCookieSession
app = Flask(__name__)
app.config['SECRET_KEY'] = 'test'
with app.test_request_context('/test', method='GET'):
    from flask import session
    session['username'] = 'test_user'
    session['role'] = 'user'
    session['permissions'] = {}  # no permissions
    from utils.permissions import check_permission
    # In audit mode, check_permission returns True even without permission
    result = check_permission('servers')
    assert result == True, f'Expected True in audit mode, got {result}'
    print('PASS: audit mode allows access')
"

# Test 2: Enforce mode blocks
python3 -c "
import json, tempfile, os  
# Write monitoring_config.json with enforce mode
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
    json.dump({'permission_check_mode': 'enforce'}, tmp)
    tmp_path = tmp.name
# Can't easily override MONITORING_CONFIG_PATH without modifying config.py
# Instead, test the _get_permission_check_mode function directly
# This is a simplified check
print('SKIP: enforce test needs full Flask test client with config override')
"

# Test 3: Admin always passes regardless of mode
python3 -c "
from flask import Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = 'test'
with app.test_request_context('/test', method='GET'):
    from flask import session
    session['username'] = 'admin'
    session['role'] = 'admin'
    session['permissions'] = {}
    from utils.permissions import check_permission
    assert check_permission('servers') == True
    print('PASS: admin bypasses all checks')
"
```

---

## Summary: Order of Operations for Phase 1 Deploy

Combining all 5 mitigations, here is the EXACT deployment order for Phase 1:

```
PRE-DEPLOY (before touching prod)
  1. [Mitigation 2] Update deploy_from_dev.sh FILES_TO_UPDATE — add 9 templates
  2. [Mitigation 1] Create services/archive_utils.py with safe_extract()
  3. [Mitigation 1] Update global_settings.py:161 to use safe_extract()
  4. [Mitigation 3] Update services/config.py to use _require_env() for LDAP_ADMIN_PASSWORD
  5. [Mitigation 3] Add pre-flight check to deploy_from_dev.sh
  6. [Mitigation 5] Update utils/permissions.py with audit-mode check_permission()
  7. [Mitigation 5] Set monitoring_config.json permission_check_mode to 'audit' in dev
  8. [Mitigation 4] Add decrypt_value() / encrypt_value() to services/encryption.py
  9. [Mitigation 4] Update nextcloud.py, uptime_kuma.py, global_settings.py to use encrypt/decrypt_value()
  10.[Mitigation 4] Create migrate_encrypt_global_config.py
  11.[Mitigation 4] Create verify_global_config_encryption.py
  12. Execute ACTION_PLAN.md Tasks 1.1 through 1.5 (code changes)
  13. Test everything on dev VPS (curl smoke tests)

PROD PRE-FLIGHT (SSH to prod, service still running)
  14. SSH: Verify LDAP_ADMIN_PASSWORD is set in /etc/conf.d/dashboard-nagios
  15. SCP: Copy migrate_encrypt_global_config.py to /svr/dashboard-nagios/
  16. SSH: Run python3 migrate_encrypt_global_config.py
  17. SSH: Run python3 verify_global_config_encryption.py
  18. SSH: Set permission_check_mode to 'audit' in config/monitoring_config.json
  19. SSH: Backup config/ directory

DEPLOY
  20. SSH: Run cd /svr/dashboard-nagios && ./deploy_from_dev.sh
  21. Deploy script auto-runs pre-flight check → stops service → SCPs files →
      pip install flask-wtf → starts service → health check

POST-DEPLOY VERIFICATION
  22. curl http://prod:PORT/health → 200 OK
  23. Login as non-admin → pages load, forms have CSRF tokens
  24. POST without CSRF token → 400 Bad Request
  25. Check permission_audit.log has entries (not empty)
  26. Verify Nextcloud/Uptime Kuma still connect (passwords decrypt correctly)

PHASE B (1-2 days later, after reviewing audit log)
  27. SSH: Change permission_check_mode to 'enforce' in monitoring_config.json
  28. SSH: rc-service dashboard-nagios restart
  29. Verify: non-admin user blocked from protected routes → 403
```
