# Nagios Dashboard — Deployment Safety Analysis

> Cross-reference: `ACTION_PLAN.md` vs `AGENTS.md`  
> **Rule:** AGENTS.md wins when there is a contradiction.

---

## AGENTS.md Summary

### Production Environment

| Attribute | Value |
|---|---|
| Server | `103.73.74.98:2325` |
| User | `rif` (SSH key, passwordless) |
| OS | Alpine Linux (OpenRC, NOT systemd) |
| Python | 3.8+ (prod) vs 3.12.3 (dev) |
| App path | `/svr/dashboard-nagios/` |
| Service name | `dashboard-nagios` (OpenRC) |
| Service cmd | `rc-service dashboard-nagios {start,stop,restart,status}` |
| Docker | `sudo` required — `echo "<pass>" | sudo -S docker ...` |
| Deploy method | `./deploy_from_dev.sh` — SCP pulls FROM dev server |

### Key Constraints from AGENTS.md

1. **Do NOT add comments** to code unless explicitly asked (line 401)
2. **Do NOT commit** unless explicitly asked (line 402)
3. **Production uses OpenRC** — not systemd (line 403)
4. **Config directory is gitignored** — contains credentials, must never be committed or overwritten blindly (line 404)
5. **Docker volume paths hardcoded** `/svr/<server>/` — intentional, cannot be changed (line 202)
6. **No CSRF protection** — marked "Hold (local network only)" in known issues (line 390)
7. **`nagios.conf` has hardcoded `AuthLDAPBindPassword "admin"`** — but this is in container build files, not runtime app (line 103-105)
8. **Container names fixed** — 13 known containers: LaurensiaEnergiCorp_SPPBE, BackupLink-USB-LTE, TIF, Adiarsa, Wifi-Public, OPD, Kelurahan, Kecamatan, TanjungMekar, Tamelang-Cilamaya, Klari, Niaga, Bhome (line 371)
9. **Venv issues**: if pip shebang broken, `rm -rf venv && python3 -m venv venv && pip install -r requirements.txt` (line 412)

### Deploy Script Coverage (CRITICAL FOR CROSS-REFERENCE)

**`FILES_TO_UPDATE`** (individual files scp'd from dev→prod):
```
app.py, proxy.py, templates/base.html, templates/monitoring.html,
templates/user_permissions.html, templates/active_users.html,
templates/global_settings.html, templates/monitoring_settings.html,
templates/stage_history.html, templates/activity_logs.html,
requirements.txt, migrate_encrypt_creds.py, README.md, USER_GUIDE.md
```

**`MODULE_DIRS`** (entire directories scp'd):
```
services/  utils/  blueprints/
```

**Templates NOT in FILES_TO_UPDATE** (⚠️ will NOT be deployed unless manually added!):
```
login.html, setup.html, dashboard.html, servers.html, host_manager.html,
users.html, monitoring_intens.html, nagios_view.html, edit_config.html
```

**New files auto-deployed if in these dirs:** `services/`, `utils/`, `blueprints/`
**New files NOT auto-deployed anywhere else** — must be manually added to `FILES_TO_UPDATE`

---

## Cross-Reference: ACTION_PLAN.md vs AGENTS.md

### 🔴 Critical Production Contradictions

#### 1. Python `filter='data'` — ✅ VERIFIED (2026-07-12)

| | Dev | Prod |
|---|---|---|
| Python | 3.12.3 | 3.12.12 |
| `tar.extractall(filter='data')` | ✅ Supported | ✅ Supported |

**Production is Alpine 3.21.5 with Python 3.12.12 as the only Python.** See `PYTHON_UPGRADE_LOG.md` for full pre-flight checks. `filter='data'` works natively on both dev and prod — no fallback needed. One-line fix: add `filter='data'` to `global_settings.py:161`.

#### 2. CSRF vs AGENTS.md Known Issues

**AGENTS.md line 390:** "No CSRF protection: Hold (local network only)"  
**ACTION_PLAN.md Task 1.5:** Implement CSRF globally

This is an intentional override — the audit found CSRF to be critical despite the app being internal. The user authorized this plan. However, `deploy_from_dev.sh` MUST be updated since some templates needing CSRF tokens are not in `FILES_TO_UPDATE`.

#### 3. Templates NOT Deployed — Silent Deployment Failures

Task 1.5 adds `{{ csrf_token() }}` to ALL templates with `<form>`. But the following templates are NOT in `FILES_TO_UPDATE`:
- `templates/servers.html`
- `templates/host_manager.html`
- `templates/users.html`
- `templates/login.html`
- `templates/setup.html`
- `templates/dashboard.html`

If these templates are modified but `deploy_from_dev.sh` is not updated, **the CSRF tokens will only be deployed to some templates, not all.** Forms without CSRF tokens will be rejected, breaking the app.

#### 4. `nagios.conf` Passwords Cannot Be Fixed via App Deploy

`create-nagios/nagios.conf` is a container BUILD file, not runtime. Changing lines 20, 34 (`AuthLDAPBindPassword "admin"`) requires rebuilding Docker images and recreating containers — NOT part of `deploy_from_dev.sh`. This fix must be done separately via Docker operations.

---

## Per-Task Production Safety Evaluation

| Task # | Phase | Task Name | Prod-Safe? | Risk Level | Notes |
|---|---|---|---|---|---|
| 1.1 | P0 | Hapus LDAP admin password default | Conditional | High | Prod sudah set `LDAP_ADMIN_PASSWORD` env var? Jika belum, app akan CRASH saat startup. **Harus verifikasi env var di prod sebelum deploy.** `nagios.conf` lines 20,34,56,70 tetap hardcoded — tidak bisa di-fix via app deploy, perlu rebuild container. |
| 1.2 | P0 | Hapus nagiosadmin fallback | Conditional | Medium | `proxy.py` DI `FILES_TO_UPDATE` → auto-deploy ✓. `host_manager.py` DI `MODULE_DIRS` → auto-deploy ✓. Tapi: jika ada creds file yang hilang/corrupt di prod, proxy dan host_manager akan return 401/400, bukan fallback. Ini BREAKING CHANGE. Pastikan semua `nagios_creds_*.json` intact di prod. |
| 1.3 | P0 | Buat decorator permission_required | Yes | Low | `utils/permissions.py` DI `MODULE_DIRS` → auto-deploy ✓. Hanya tambah fungsi baru, tidak mengubah behaviour existing. |
| 1.4 | P0 | Tambah permission check ke 25+ route | Yes | Medium | Semua file di `MODULE_DIRS` → auto-deploy ✓. Tapi: **BREAKING CHANGE** — user non-admin tanpa explicit permission akan tiba-tiba kena 403 di route yang sebelumnya bisa diakses. Harus audit siapa yang punya permission apa di prod `user_permissions.json`. Jangan sampai admin prod malah ke-lockout. |
| 1.5 | P0 | CSRF protection global | Conditional | High | **`app.py`** DI `FILES_TO_UPDATE` ✓. **Tapi** 9 template perlu CSRF token — hanya 6 yang di `FILES_TO_UPDATE`. `servers.html`, `host_manager.html`, `users.html`, `login.html`, `setup.html`, `dashboard.html`, `nagios_view.html`, `edit_config.html`, `monitoring_intens.html` TIDAK ADA. **Harus tambahkan semua template ke `FILES_TO_UPDATE` di `deploy_from_dev.sh` sebelum deploy.** Juga perlu tambah `flask-wtf` ke `requirements.txt`. |
| 2.1 | P1 | Enkripsi Nextcloud & Uptime Kuma password | Conditional | High | **Data migration needed!** `global_config.json` di prod punya password plaintext. Setelah deploy, app akan coba `decrypt_value()` pada value yang belum terenkripsi → CRASH. **Harus jalankan migration script DULU sebelum restart service.** Migration script perlu di-SCP manual atau ditambahkan ke `FILES_TO_UPDATE`. |
| 2.2 | P1 | Fix tar.extractall() path traversal | Yes | Low | Prod is Python 3.12.12 — `filter='data'` works natively. `global_settings.py` DI `MODULE_DIRS` → auto-deploy ✓. Satu baris perubahan. |
| 2.3 | P1 | Fix hardcoded admin di Uptime Kuma | Yes | Low | `monitoring_intens.py` DI `MODULE_DIRS` → auto-deploy ✓. Backward compatible — jika `config['username']` tidak ada, fallback ke `'admin'`. |
| 2.4 | P1 | Whitelist sound file extension | Yes | Low | `monitoring_settings.py` DI `MODULE_DIRS` → auto-deploy ✓. `monitoring_settings.html` DI `FILES_TO_UPDATE` → auto-deploy ✓. Backward compatible — cuma nambah validasi. |
| 2.5 | P1 | secure_filename() untuk plugin upload | Yes | Low | `servers.py` DI `MODULE_DIRS` → auto-deploy ✓. Backward compatible — `secure_filename()` hanya sanitasi, tidak tolak filename valid. |
| 2.6 | P1 | Validasi container name sebelum rm -rf | Yes | Low | `servers.py` DI `MODULE_DIRS` → auto-deploy ✓. Backward compatible — cuma nambah safety check. |
| 3.1 | P2 | Hapus debug print & error disclosure | Yes | Low | `dashboard.py`, `servers.py` DI `MODULE_DIRS` → auto-deploy ✓. Tidak ada behaviour change. |
| 3.2 | P2 | Fix silent exception swallowing | Yes | Low | `dashboard.py`, `ldap_service.py`, `auth.py` DI `MODULE_DIRS` → auto-deploy ✓. Cuma nambah logging, tidak mengubah behaviour. |
| 3.3 | P2 | Fix LDAP injection | Yes | Low | `ldap_service.py` DI `MODULE_DIRS` → auto-deploy ✓. `ldap3` sudah built-in di prod. |
| 3.4 | P2 | Hapus duplicate get_nagios_servers | Conditional | Medium | `monitoring.py` DI `MODULE_DIRS` → auto-deploy ✓. Tapi: jika versi `shared_helpers.py` BELUM punya behaviour yang sama dengan local copy, monitoring bisa return data berbeda. **Harus verify dulu output identik sebelum deploy.** |
| 3.5 | P2 | Fix race condition stage tracking | Conditional | High | ⚠️ Ini logic core. Stage tracking salah → host bisa tidak ter-resolve atau stage history corrupt. **Harus test dengan concurrent request scenario sebelum deploy ke prod.** Minimal manual test dengan 2 browser tab concurrent refresh. |
| 3.6 | P2 | Pre-save validation Nagios config | Conditional | Medium | `servers.py` DI `MODULE_DIRS` → auto-deploy ✓. Butuh `docker exec` untuk run `nagios -v` — ini akan jalan via sudo di prod. Pastikan user `rif` bisa `sudo docker exec`. Juga: container name harus ada di Docker. **Timeout risk:** `nagios -v` di container bisa lambat. |
| 3.7 | P2 | Extract config-loading utility | Yes | Low | `shared_helpers.py` DI `MODULE_DIRS` → auto-deploy ✓. Semua blueprint DI `MODULE_DIRS`. Refactor murni — behaviour identik. |
| 3.8 | P2 | Extract host definition builder | Conditional | Medium | File BARU `services/nagios_config.py` DI `MODULE_DIRS` → auto-deploy ✓. `host_manager.py` & `api.py` DI `MODULE_DIRS`. Tapi: **host definition berubah bisa bikin config Nagios invalid.** Harus test add host + batch add via API setelah refactor — pastikan output string identical. |
| 3.9 | P2 | Connection pooling Nagios CGI | Conditional | Low | File BARU `services/http_client.py` DI `MODULE_DIRS` → auto-deploy ✓. Butuh `requests` (sudah ada). Session global — pastikan thread-safe (requests.Session IS thread-safe untuk GET, tapi perlu verifikasi). |
| 4.1 | P3 | Pin dependencies & upgrade requests | Conditional | Medium | `requirements.txt` DI `FILES_TO_UPDATE` → auto-deploy ✓. Deploy script auto-run `pip install -r requirements.txt` di prod. **⚠️ `requests==2.32.3` mungkin tidak tersedia di Alpine edge/testing repo.** Prod pakai Python 3.8, bisa jadi perlu pin ke `2.32.0` yang support 3.8. Verifikasi: cek apakah pip install sukses di Alpine. |
| 4.2 | P3 | Buat .env.example | Yes | None | File baru, tidak perlu deploy ke prod. Hanya dokumentasi. |
| 4.3 | P3 | Hapus deprecated _old.html templates | Yes | None | File tidak di-deploy karena bukan di FILES_TO_UPDATE ✓. Cuma `git rm`. |
| 4.4 | P3 | Hapus TRENDS_DUMMY_GUIDE.md | Yes | None | Cuma `git rm`, tidak mempengaruhi prod. |
| 4.5 | P3 | Extract PROXY_PORT_OFFSET constant | Yes | Low | `config.py` DI `MODULE_DIRS` (services/), `servers.py` DI `MODULE_DIRS`. Refactor murni. |
| 4.6 | P3 | Setup linting dengan ruff | Yes | None | `pyproject.toml` — tidak perlu deploy, development-only. |
| 4.7 | P3 | Unit tests | Yes | None | `tests/` directory — tidak perlu deploy ke prod. Development-only. |
| 4.8 | P3 | GitHub Actions CI | Yes | None | `.github/workflows/` — git-only, tidak deploy. |
| 4.9a | P3 | Fix APP_PORT default | Conditional | Medium | `config.py` DI `MODULE_DIRS`. AGENTS.md says default `80`, code says `5000`. **Prod mungkin mengandalkan default `5000`.** Ubah ke `80` hanya jika prod SET `APP_PORT` env var. Jika prod tidak set, app akan listen di port yang berbeda → BREAK. **Harus cek `rc-service` config atau env var di prod dulu.** |
| 4.9b | P3 | Standardize path construction | Yes | Low | Refactor murni, `os.path.join()` sudah dipakai di banyak tempat. |
| 4.9c | P3 | API documentation | Yes | None | Tidak deploy, development-only. |

---

## Flagged High-Risk Tasks

### ⚠️ TASK 1.1 WILL BREAK PRODUCTION IF ENV VAR NOT SET

**Problem:** Prod mungkin tidak set `LDAP_ADMIN_PASSWORD` env var karena sebelumnya ada fallback `'admin'`. Setelah perubahan, `os.environ['LDAP_ADMIN_PASSWORD']` akan raise `KeyError` → app crash saat import `services.config`.

**Recommended fix:** Sebelum deploy, SSH ke prod dan verifikasi:
```bash
ssh -p 2325 rif@103.73.74.98 "grep LDAP_ADMIN_PASSWORD /etc/conf.d/dashboard-nagios 2>/dev/null || echo 'NOT SET'"
```
Jika tidak diset, tambahkan ke OpenRC service config file.

### ⚠️ TASK 2.1 NEEDS DATA MIGRATION BEFORE SERVICE RESTART

**Problem:** `global_config.json` di prod punya Nextcloud/Uptime Kuma password dalam plaintext. Setelah code update, `decrypt_value()` akan dipanggil pada plaintext string → kemungkinan crash.

**Deployment order MUST be:**
1. SCP migration script ke prod
2. Jalankan migration script (encrypt existing plaintext)
3. Verifikasi `global_config.json` sekarang pakai `__ENC__` prefix
4. Baru deploy code + restart service

### ⚠️ TASK 2.2 WILL CRASH ON PYTHON 3.8 (ALPINE PRODUCTION)

**Problem:** `tar.extractall(path, filter='data')` adalah Python 3.10.6+ feature. Alpine production kemungkinan pakai Python 3.8.

**Recommended fix:** Ganti implementasi di ACTION_PLAN.md Task 2.2 dari `filter='data'` ke fallback manual `safe_extract()` yang validasi `os.path.realpath()` per member.

### ⚠️ TASK 1.5 CSRF — 9 TEMPLATES NOT IN DEPLOY SCRIPT

**Problem:** CSRF tokens ditambahkan ke templates, tapi `servers.html`, `host_manager.html`, `users.html`, `login.html`, `setup.html`, `dashboard.html`, `nagios_view.html`, `edit_config.html`, `monitoring_intens.html` TIDAK ada di `FILES_TO_UPDATE`. Template ini TIDAK akan ter-deploy.

**MUST mupdate `deploy_from_dev.sh` FILES_TO_UPDATE array** untuk menambahkan semua template yang dimodifikasi. Atau, ubah `deploy_from_dev.sh` agar mendeploy SELURUH `templates/` directory (seperti `MODULE_DIRS`).

### ⚠️ TASK 4.9a APP_PORT DEFAULT CHANGE — RISK PORT MISMATCH

**Problem:** AGENTS.md says default `80`, code says `5000`. Jika prod TIDAK set `APP_PORT` env var dan kita ubah default ke `80`, app akan listen di port 80, bukan 5000. Jika ada reverse proxy atau port forwarding yang pointing ke 5000 → broken.

**Before changing:** Cek apakah prod set `APP_PORT`:
```bash
ssh -p 2325 rif@103.73.74.98 "grep -r 'APP_PORT\|:5000\|:80' /etc/conf.d/ /svr/dashboard-nagios/ 2>/dev/null | head -10"
```

---

## Deployment Safety Protocol

### Pre-Deployment Checklist (all phases)

- [ ] **SSH access verified:** `ssh -p 2325 rif@103.73.74.98 "echo OK"`
- [ ] **Backup `config/` directory:** `cp -r /svr/dashboard-nagios/config/ /svr/dashboard-nagios/config.backup-$(date +%Y%m%d_%H%M)/`
- [ ] **Docker running:** `ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker ps --format '{{.Names}}' | wc -l"` → harus > 0
- [ ] **Service status:** `ssh -p 2325 rif@103.73.74.98 "rc-service dashboard-nagios status"`
- [ ] **Health check before:** `curl -s http://103.73.74.98:5000/health` (atau port yg dipakai)
- [ ] **Read prod config:** `ssh -p 2325 rif@103.73.74.98 "cat /svr/dashboard-nagios/config/global_config.json | python3 -m json.tool"` → catat values
- [ ] **Read env vars:** `ssh -p 2325 rif@103.73.74.98 "grep -E 'APP_PORT|LDAP_ADMIN' /etc/conf.d/dashboard-nagios 2>/dev/null; rc-service dashboard-nagios env 2>/dev/null"`
- [ ] **Git branch clean:** `git status --short` → harus empty (atau hanya file audit yg untracked)

### Deployment Sequence (per phase)

#### Phase 1 Deployment

```
STEP 1 — PREPARE
  ✓ Update deploy_from_dev.sh FILES_TO_UPDATE — tambahkan SEMUA template yg dimodifikasi:
    "templates/login.html" "templates/setup.html" "templates/dashboard.html"
    "templates/servers.html" "templates/host_manager.html" "templates/users.html"
    "templates/monitoring_intens.html" "templates/nagios_view.html" "templates/edit_config.html"

  ✓ Verifikasi LDAP_ADMIN_PASSWORD env var di prod:
    ssh -p 2325 rif@103.73.74.98 "grep LDAP_ADMIN_PASSWORD /etc/conf.d/dashboard-nagios"
    → Jika tidak ada, TAMBAHKAN dulu. Jangan deploy tanpa ini.

  ✓ Install flask-wtf di dev: pip install flask-wtf && pip freeze | grep flask-wtf >> requirements.txt

STEP 2 — BACKUP
  ssh -p 2325 rif@103.73.74.98 "
    cd /svr/dashboard-nagios
    cp -r config/ config.backup-phase1-\$(date +%Y%m%d_%H%M)/
    echo 'Backup OK'
  "

STEP 3 — DEPLOY
  ssh -p 2325 rif@103.73.74.98 "
    cd /svr/dashboard-nagios
    ./deploy_from_dev.sh
  "
  → Script ini auto: stop service → SCP files → pip install → restart proxies → start service → health check
  → Auto-rollback jika gagal

STEP 4 — VERIFY PERMISSIONS
  Login sebagai user non-admin (tanpa permission servers/host_manager/monitoring_settings)
  Verifikasi akses:
    - POST /servers/batch-start → 403 ✓
    - POST /servers/delete/<name> → 403 ✓
    - POST /monitoring-settings/edit-category → 403 ✓
    - POST /host-manager/backup → 403 ✓
    - GET /monitoring → 200 ✓ (monitoring permission tetap jalan)
    - GET /dashboard → 200 ✓ (dashboard permission tetap jalan)

STEP 5 — VERIFY CSRF
  curl -X POST http://103.73.74.98:5000/login -d "username=test&password=test" -s | grep -i csrf
  → Harus ada error CSRF

STEP 6 — SMOKE TEST
  - Login normal → harus OK
  - Dashboard → harus load dengan stats
  - Monitoring → harus fetch data
  - Logout → harus OK
```

#### Phase 2 Deployment

```
STEP 1 — PREPARE MIGRATION SCRIPT
  Buat /root/apps/nagiosDashboard/migrate_encrypt_global_config.py:
    (content dari ACTION_PLAN.md Task 2.1)
  SCP ke prod:
    scp -P 2325 migrate_encrypt_global_config.py rif@103.73.74.98:/svr/dashboard-nagios/

STEP 2 — BACKUP + MIGRATE (BEFORE code deploy)
  ssh -p 2325 rif@103.73.74.98 "
    cd /svr/dashboard-nagios
    cp config/global_config.json config/global_config.json.phase2-backup
    python3 migrate_encrypt_global_config.py
    cat config/global_config.json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(\"nextcloud_pw:\", d.get(\"nextcloud_password\",\"N/A\")[:10]); print(\"uptime_pw:\", d.get(\"password\",\"N/A\")[:10])'
    # Kedua value harus prefix __ENC__
  "

STEP 3 — DEPLOY CODE
  ssh -p 2325 rif@103.73.74.98 "
    cd /svr/dashboard-nagios
    ./deploy_from_dev.sh
  "

STEP 4 — VERIFY
  - Backup restore → harus jalan (tar safe extract)
  - Monitoring Intens → harus bisa konek Uptime Kuma (password ter-decrypt)
  - Upload sound file .php → harus ditolak
  - Upload plugin ../../../ → harus ditolak
```

#### Phase 3 & 4 Deployment

```
Phase 3 (P2) dan Phase 4 (P3) bisa deploy dengan ./deploy_from_dev.sh standar.
Tidak perlu migration khusus.

PROSEDUR STANDAR:
  ssh -p 2325 rif@103.73.74.98 "
    cd /svr/dashboard-nagios
    cp -r config/ config.backup-phase3-\$(date +%Y%m%d_%H%M)/
    ./deploy_from_dev.sh
  "

EXCEPTION: Task 3.5 (race condition fix) — test concurrent scenario dulu di dev sebelum deploy.
EXCEPTION: Task 4.9a (APP_PORT) — pastikan env var ada di prod sebelum deploy.
```

### Post-Deployment Verification (every phase)

```bash
# 1. Service running
ssh -p 2325 rif@103.73.74.98 "rc-service dashboard-nagios status" | grep -q started && echo "PASS: service" || echo "FAIL: service"

# 2. Health endpoint
curl -sf http://103.73.74.98:5000/health && echo "PASS: health" || echo "FAIL: health"

# 3. Login page loads
curl -sf http://103.73.74.98:5000/ | grep -q "login\|Login" && echo "PASS: login page" || echo "FAIL: login page"

# 4. Docker accessible (proxy check)
ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker ps | grep -q nagios-ldap" && echo "PASS: docker" || echo "FAIL: docker"

# 5. Check error logs (Alpine: /var/log/messages or app log)
ssh -p 2325 rif@103.73.74.98 "tail -20 /var/log/messages 2>/dev/null | grep -i dashboard" || echo "(no dashboard errors in syslog)"
```

### Rollback Procedure (per phase)

#### Phase 1 Rollback

```bash
ssh -p 2325 rif@103.73.74.98 "
  cd /svr/dashboard-nagios
  rc-service dashboard-nagios stop
  
  # Restore dari backup deploy (deploy script auto-backup ke config/backups/deploy_backup_*)
  LATEST_BACKUP=\$(ls -td config/backups/deploy_backup_* 2>/dev/null | head -1)
  if [ -n \"\$LATEST_BACKUP\" ]; then
    cp \"\$LATEST_BACKUP\"/app.py .
    cp \"\$LATEST_BACKUP\"/proxy.py .
    cp -r \"\$LATEST_BACKUP\"/services/* services/
    cp -r \"\$LATEST_BACKUP\"/utils/* utils/
    cp -r \"\$LATEST_BACKUP\"/blueprints/* blueprints/
    echo 'Restored from: '\$LATEST_BACKUP
  else
    echo 'No backup found — manual git checkout needed'
    git checkout main
  fi
  
  # Restore configs
  cp config.backup-phase1-*/user_permissions.json config/ 2>/dev/null || true
  
  rc-service dashboard-nagios start
  curl -sf http://localhost:5000/health && echo 'Rollback OK' || echo 'ROLLBACK FAILED'
"
```

#### Phase 2 Rollback

```bash
ssh -p 2325 rif@103.73.74.98 "
  cd /svr/dashboard-nagios
  rc-service dashboard-nagios stop
  
  # Restore code dari backup
  LATEST_BACKUP=\$(ls -td config/backups/deploy_backup_* 2>/dev/null | head -1)
  cp \"\$LATEST_BACKUP\"/app.py .
  cp -r \"\$LATEST_BACKUP\"/services/* services/
  cp -r \"\$LATEST_BACKUP\"/blueprints/* blueprints/
  cp -r \"\$LATEST_BACKUP\"/utils/* utils/
  
  # Restore global_config.json (undo encryption migration)
  cp config/global_config.json.phase2-backup config/global_config.json
  
  rc-service dashboard-nagios start
  curl -sf http://localhost:5000/health && echo 'Rollback OK' || echo 'ROLLBACK FAILED'
"
```

#### Phase 3/4 Rollback

```bash
# Standar: restore dari latest deploy backup
ssh -p 2325 rif@103.73.74.98 "
  cd /svr/dashboard-nagios
  rc-service dashboard-nagios stop
  
  LATEST_BACKUP=\$(ls -td config/backups/deploy_backup_* 2>/dev/null | head -1)
  for d in services utils blueprints; do
    if [ -d \"\$LATEST_BACKUP/\$d\" ]; then
      rm -rf \"\$d\" && cp -r \"\$LATEST_BACKUP/\$d\" \"\$d\"
    fi
  done
  
  rc-service dashboard-nagios start
  curl -sf http://localhost:5000/health && echo 'Rollback OK'
"
```

---

## Summary: Must-Fix Before Deploy Phase 1

1. **[ACTION_PLAN.md Task 1.5] Update `deploy_from_dev.sh`** — tambahkan 9 template ke `FILES_TO_UPDATE`:
   ```bash
   "templates/login.html" "templates/setup.html" "templates/dashboard.html"
   "templates/servers.html" "templates/host_manager.html" "templates/users.html"
   "templates/monitoring_intens.html" "templates/nagios_view.html" "templates/edit_config.html"
   ```

2. **[ACTION_PLAN.md Task 1.1] Verifikasi `LDAP_ADMIN_PASSWORD`** di prod sebelum deploy.

3. **[ACTION_PLAN.md Task 1.4] Audit `user_permissions.json` di prod** — catat siapa punya permission apa, pastikan admin tidak ke-lockout.

4. **[ACTION_PLAN.md Task 2.2] Ganti `filter='data'` dengan manual `safe_extract()`** — Python 3.8 production tidak support.

5. **[ACTION_PLAN.md Task 2.1] Migration script untuk encrypt `global_config.json`** — harus dijalankan SEBELUM code deploy.
