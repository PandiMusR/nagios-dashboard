# Phase 1 — Production Deploy Readiness

> Status: ✅ READY (all mitigations resolved)  
> Date: 2026-07-12

---

## Mitigation Status

| # | Mitigation | Status | Notes |
|---|---|---|---|
| 1 | Python 3.8 tar.extractall | ✅ RESOLVED | Prod is Python 3.12.12 — `filter='data'` natively supported |
| 2 | Deploy script template coverage | ✅ RESOLVED | `FILES_TO_UPDATE` now has all 17 active templates + `preflight_check.sh` |
| 3 | LDAP env var check | ✅ RESOLVED | `_require_env()` in config.py + `preflight_check.sh` |
| 4 | Password encryption migration | ✅ RESOLVED | `decrypt_value()`/`encrypt_value()` in encryption.py. Migration scripts ready. |
| 5 | Permission audit mode | ✅ RESOLVED | Two-phase toggle: `audit` (log only) → `enforce` (block). Default: audit |

---

## Files Changed (Dev Environment)

| File | Change | Auto-Deploy? |
|---|---|---|
| `services/config.py` | `_require_env()` replaces `os.environ.get('LDAP_ADMIN_PASSWORD', 'admin')` | ✅ MODULE_DIRS |
| `services/encryption.py` | Added `encrypt_value()` + `decrypt_value()` (backward-compatible) | ✅ MODULE_DIRS |
| `services/nextcloud.py` | Use `decrypt_value()` for nextcloud_password | ✅ MODULE_DIRS |
| `services/uptime_kuma.py` | Use `decrypt_value()` for uptime_kuma_password | ✅ MODULE_DIRS |
| `blueprints/global_settings.py` | Use `encrypt_value()` when saving passwords | ✅ MODULE_DIRS |
| `utils/permissions.py` | Audit/enforce mode + audit log + `check_permission()` | ✅ MODULE_DIRS |
| `deploy_from_dev.sh` | Updated FILES_TO_UPDATE with 9 new templates + `preflight_check.sh` | ✅ FILES_TO_UPDATE |
| `preflight_check.sh` (NEW) | Pre-deploy env var validation | ✅ FILES_TO_UPDATE |
| `migrate_passwords.py` (NEW) | Encrypt plaintext passwords in global_config.json | ❌ Manual SCP |
| `verify_migration.py` (NEW) | Verify all password fields encrypted | ❌ Manual SCP |

---

## Pre-Deployment Checklist

- [ ] **SSH access verified:** `ssh -p 2325 rif@103.73.74.98 "echo OK"`
- [ ] **Backup config/:** `cp -r /svr/dashboard-nagios/config/ /svr/dashboard-nagios/config.backup-phase1-$(date +%Y%m%d_%H%M)/`
- [ ] **Verify LDAP_ADMIN_PASSWORD set at prod:** `ssh -p 2325 rif@103.73.74.98 "cat /etc/conf.d/dashboard-nagios"` — must have `export LDAP_ADMIN_PASSWORD=...`
- [ ] **Docker running:** `ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker ps --format '{{.Names}}' | wc -l"` → must be > 0
- [ ] **Service status:** `ssh -p 2325 rif@103.73.74.98 "rc-service dashboard-nagios status"`
- [ ] **Health check before:** `curl -s -o /dev/null -w "%{http_code}" http://103.73.74.98:80/health` → must return 200
- [ ] **flask-wtf installed on dev:** `pip install flask-wtf && echo "flask-wtf" >> requirements.txt` (if not already)

---

## Deployment Sequence

```
=== PHASE 1A: MIGRATION (run BEFORE code deploy) ===

STEP 1 — SCP migration scripts to prod
  scp -P 2325 migrate_passwords.py rif@103.73.74.98:/svr/dashboard-nagios/
  scp -P 2325 verify_migration.py rif@103.73.74.98:/svr/dashboard-nagios/

STEP 2 — Dry-run migration
  ssh -p 2325 rif@103.73.74.98 "python3 /svr/dashboard-nagios/migrate_passwords.py --dry-run"
  → Should show: WOULD encrypt: nextcloud_password, uptime_kuma_password

STEP 3 — Run migration
  ssh -p 2325 rif@103.73.74.98 "python3 /svr/dashboard-nagios/migrate_passwords.py"
  → Should show: Encrypted: nextcloud_password, uptime_kuma_password
  → Backup saved to: global_config.json.migration-backup

STEP 4 — Verify migration
  ssh -p 2325 rif@103.73.74.98 "python3 /svr/dashboard-nagios/verify_migration.py"
  → Must show: PASS: all N password field(s) encrypted

STEP 5 — Set permission_check_mode to audit
  ssh -p 2325 rif@103.73.74.98 "python3 -c \"
import json
with open('/svr/dashboard-nagios/config/monitoring_config.json') as f:
    c = json.load(f)
c['permission_check_mode'] = 'audit'
with open('/svr/dashboard-nagios/config/monitoring_config.json', 'w') as f:
    json.dump(c, f, indent=2)
print('permission_check_mode set to audit')
\""


=== PHASE 1B: CODE DEPLOY ===

STEP 6 — Verify dev has flask-wtf
  cd /root/apps/nagiosDashboard
  pip install flask-wtf
  pip freeze | grep -i flask-wtf >> requirements.txt

STEP 7 — Deploy code
  ssh -p 2325 rif@103.73.74.98 "cd /svr/dashboard-nagios && ./deploy_from_dev.sh"
  → Auto-stops service → SCPs files → pip install → starts service → health check
  → Auto-rollback on failure

STEP 8 — Verify service
  ssh -p 2325 rif@103.73.74.98 "rc-service dashboard-nagios status" | grep started
  curl -s -o /dev/null -w "%{http_code}" http://103.73.74.98:80/health → must return 200


=== PHASE 1C: POST-DEPLOY VERIFICATION ===

STEP 9 — Login test
  curl -s http://103.73.74.98:80/ | grep -q "Nagios Dashboard" && echo "PASS: login page" || echo "FAIL"

STEP 10 — Verify permission audit log exists
  ssh -p 2325 rif@103.73.74.98 "ls -la /svr/dashboard-nagios/config/permission_audit.log 2>/dev/null && echo 'audit log exists' || echo '(will be created on first denial)'"

STEP 11 — Verify Nextcloud/Uptime Kuma still connects
  (check from browser — verify monitoring_intens page loads without errors)

STEP 12 — Verify CSRF
  curl -s -X POST http://103.73.74.98:80/login -d "username=test&password=test" | grep -i csrf
  → Should show CSRF error (not login failure)
```

---

## Phase B: Permission Enforce Mode (2-3 days later)

After reviewing permission_audit.log and confirming all legitimate access is approved:

```
STEP B1 — Analyze audit log
  ssh -p 2325 rif@103.73.74.98 "cat /svr/dashboard-nagios/config/permission_audit.log | python3 -c \"
import json, sys
from collections import Counter
counts = Counter()
for line in sys.stdin:
    try:
        d = json.loads(line.strip())
        counts[(d['username'], d['permission'])] += 1
    except: pass
for (u, p), n in counts.most_common():
    print(f'{u:20s} {p:25s} {n:4d}')
\""

STEP B2 — Fix user_permissions.json if needed
  (if legitimate users show up in audit log, grant them permissions)

STEP B3 — Switch to enforce mode
  ssh -p 2325 rif@103.73.74.98 "python3 -c \"
import json
with open('/svr/dashboard-nagios/config/monitoring_config.json') as f:
    c = json.load(f)
c['permission_check_mode'] = 'enforce'
with open('/svr/dashboard-nagios/config/monitoring_config.json', 'w') as f:
    json.dump(c, f, indent=2)
print('permission_check_mode set to enforce')
\""

STEP B4 — Restart service
  ssh -p 2325 rif@103.73.74.98 "rc-service dashboard-nagios restart"

STEP B5 — Verify
  (log in as non-admin user → try to access protected route → should get 403)
```

---

## Rollback Plan

### Full Rollback (Phase 1A + 1B)

```bash
ssh -p 2325 rif@103.73.74.98 "

  # Stop service
  rc-service dashboard-nagios stop

  # Restore code from deploy backup
  LATEST_BACKUP=\$(ls -td /svr/dashboard-nagios/config/backups/deploy_backup_* 2>/dev/null | head -1)
  cp \"\$LATEST_BACKUP\"/app.py /svr/dashboard-nagios/
  cp \"\$LATEST_BACKUP\"/proxy.py /svr/dashboard-nagios/
  for d in services utils blueprints; do
    rm -rf /svr/dashboard-nagios/\$d
    cp -r \"\$LATEST_BACKUP/\$d\" /svr/dashboard-nagios/\$d
  done
  pip install -r \"\$LATEST_BACKUP/requirements.txt\" --break-system-packages -q

  # Restore global_config.json (undo password encryption)
  cp /svr/dashboard-nagios/config/global_config.json.migration-backup \\
     /svr/dashboard-nagios/config/global_config.json

  # Restore monitoring_config.json (remove permission_check_mode)
  cp /svr/dashboard-nagios/config/monitoring_config.json \\
     /svr/dashboard-nagios/config/monitoring_config.json.phase1
  python3 -c \"
import json
with open('/svr/dashboard-nagios/config/monitoring_config.json.phase1') as f:
    c = json.load(f)
c.pop('permission_check_mode', None)
with open('/svr/dashboard-nagios/config/monitoring_config.json', 'w') as f:
    json.dump(c, f, indent=2)
\"

  # Restore user_permissions.json if changed
  cp /svr/dashboard-nagios/config.backup-phase1-*/user_permissions.json \\
     /svr/dashboard-nagios/config/ 2>/dev/null

  rc-service dashboard-nagios start
  curl -sf http://localhost:80/health && echo 'Rollback OK' || echo 'ROLLBACK FAILED'
"
```

### Partial Rollback: Undo Password Encryption Only

```bash
ssh -p 2325 rif@103.73.74.98 "
  cp /svr/dashboard-nagios/config/global_config.json.migration-backup \\
     /svr/dashboard-nagios/config/global_config.json
  rc-service dashboard-nagios restart
"
```

### Partial Rollback: Revert Permission Mode to Audit

```bash
ssh -p 2325 rif@103.73.74.98 "
  python3 -c \"
import json
with open('/svr/dashboard-nagios/config/monitoring_config.json') as f:
    c = json.load(f)
c['permission_check_mode'] = 'audit'
with open('/svr/dashboard-nagios/config/monitoring_config.json', 'w') as f:
    json.dump(c, f, indent=2)
\"
  rc-service dashboard-nagios restart
"
```
