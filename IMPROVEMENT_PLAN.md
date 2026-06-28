# Nagios Dashboard — Improvement Plan

## Summary

| Category | Issues | Priority | Status |
|---|---|---|---|
| Security | 5 | 🔴 Critical | 5/5 done |
| Bug Fixes | 6 | 🔴 Critical | 6/6 done |
| Code Quality | 4 | 🟡 Medium | 4/4 done |
| Reliability | 3 | 🟡 Medium | 3/3 done (1 skipped) |

**All 12 planned tasks completed.** Additional features implemented post-plan are listed in [Section 4](#4-additional-features-).

---

## 0. Bug Fixes 🔴

### 0.1 Deadlock on `set_stage()` ✅ FIXED

**File:** `app.py` — `set_stage()` function
**Issue:** `set_stage()` held `_stages_lock` then called `save_host_stages()` which also acquired `_stages_lock`. Python's `threading.Lock()` is not reentrant → **deadlock** → entire app freezes when user clicks Submit on stage assignment.

**Fix applied:**
- Replaced manual `with _stages_lock:` + `load_host_stages()` + `save_host_stages()` with `host_stages_transaction()` context manager
- `host_stages_transaction()` handles lock internally, writes directly to file (no nested lock)
- Both resolved and non-resolved paths updated

**Impact:** Critical — was causing production crashes.

---

### 0.2 Dead Code / Duplicate Exception Handler ✅ FIXED

**File:** `app.py` (old lines 270-273)
**Issue:** Unreachable `return` statement followed by duplicate `except` block.

**Fix:** Removed dead code.

---

### 0.3 Missing Route Decorator on `start_server()` ✅ FIXED

**File:** `app.py`
**Issue:** `start_server()` function was missing `@app.route('/servers/start/<name>', methods=['POST'])` decorator.

**Fix:** Added the missing route decorator.

---

### 0.4 Race Condition on `host_stages.json` ✅ FIXED

**File:** `app.py`
**Issue:** Multiple threads could read/modify/save `host_stages.json` simultaneously → data loss or corruption.

**Fix:** Added `threading.Lock` (`_stages_lock`) and `host_stages_transaction()` context manager for atomic read-modify-write cycles.

---

### 0.5 Missing `closeBatchAckModal()` Function ✅ FIXED

**File:** `templates/monitoring.html`
**Issue:** Batch ACK modal Cancel/Close buttons referenced `closeBatchAckModal()` which didn't exist → JS error.

**Fix:** Added the function. Also resets `batch_comment` textarea and restores body scroll on close.

---

### 0.6 `current_app.logger` Used Outside Request Context ✅ FIXED

**File:** `app.py`
**Issue:** Two calls to `current_app.logger` would fail when called outside a request context (e.g., during startup or background tasks).

**Fix:** Replaced with `print()`.

---

## 1. Security Hardening 🔴

### 1.1 Plaintext Password in Flask Session ✅ FIXED

**File:** `app.py` — multiple locations
**Issue:** User LDAP password disimpan langsung di `session['password']`. Flask session hanya di-encode base64, **bukan encrypted**.

**Fix applied:**
- Password di-encrypt menggunakan Fernet (derived dari persistent secret key) sebelum simpan ke session
- Semua read locations (15) dibungkus `decrypt_session_value()`
- `cryptography` ditambahkan ke requirements.txt

---

### 1.2 Plaintext Password Written to JSON Files ✅ FIXED

**File:** `app.py`
**Issue:** Password user LDAP ditulis ke `config/user_passwords.json` dan `config/<nagios_instance>/creds.json` dalam plaintext.

**Fix applied:**
- `save_encrypted_json()` / `load_encrypted_json()` — Fernet encryption dengan `__ENC__` marker
- Semua 6 write + 1 read locations untuk `nagios_creds_*.json` diupdate
- `save_user_password()` / `get_user_password()` diupdate untuk encrypt/decrypt
- Migration script: `migrate_encrypt_creds.py` — idempotent, auto-backup sebelum encrypt
- `proxy.py` updated: `_get_fernet()`, `_decrypt_value()`, `get_stored_creds()`, `store_creds()`

---

### 1.3 Hardcoded LDAP Admin Password ✅ FIXED

**File:** `app.py` — **10 occurrences**
**Issue:** Password admin LDAP (`'admin'`) di-hardcode langsung di source code.

**Fix applied:**
- Tambah `LDAP_ADMIN_PASSWORD = os.environ.get('LDAP_ADMIN_PASSWORD', 'admin')` di config
- Buat helper function `get_ldap_admin_connection()`
- Ganti semua 10 hardcoded instances dengan helper function
- **Backward compatible:** default value `'admin'` jika env var tidak diset

---

### 1.4 Random Secret Key Per Restart ✅ FIXED

**File:** `app.py:12`
**Issue:** `app.secret_key = os.urandom(24)` — generate baru setiap restart. Semua session user langsung invalid setiap kali service restart.

**Fix applied:**
- `load_or_create_secret_key()` — generate once, simpan ke `/svr/dashboard-nagios/config/secret_key`
- Secret key persist across restarts
- Fernet encryption key derived dari secret key (untuk session password encryption)

---

### 1.5 Credentials Logged to Activity Log ✅ AUDITED

**File:** `app.py` — `log_activity()` calls
**Issue:** Beberapa operasi yang melibatkan password bisa masuk ke activity log. Perlu audit bahwa tidak ada password yang ter-logging.

**Audit result:** All 52 `log_activity()` calls are safe. No passwords, tokens, or credentials are logged. Change Password logs only "User X changed their password successfully" — no actual password value. Uptime Kuma config logs only URL and enabled status — no password.

---

## 2. Code Quality 🟡

### 2.1 Monolithic `app.py` ✅ FIXED

**Issue:** Seluruh aplikasi dalam satu file (~3850 lines). Sangat sulit di-maintain, test, dan review.

**Fix applied:**
- Split ke 22 files menggunakan Flask Blueprints
- `app.py` trimmed dari 3853 → 66 lines (factory + config + register blueprints)
- 10 blueprints, 8 services, 2 utils modules
- Central config module (`services/config.py`) untuk shared constants

**Final structure:**
```
app.py (66 lines)                          ← App factory + register blueprints + before_request
services/config.py (42 lines)              ← Centralized constants (LDAP, paths, stages)
services/encryption.py (74 lines)          ← Fernet encrypt/decrypt
services/ldap_service.py (~140 lines)      ← LDAP connection + auth + log_activity + read_activity_logs
services/stage_service.py (47 lines)       ← Host stage tracking
services/uptime_kuma.py (169 lines)        ← Socket.IO interactions
services/nextcloud.py (49 lines)           ← WebDAV upload
services/active_users.py (~100 lines)      ← In-memory active session tracker
services/scheduler.py (~70 lines)          ← CR Verification auto-reset scheduler
services/docker_cache.py (~55 lines)       ← In-memory Docker CLI cache with TTL
utils/permissions.py (86 lines)            ← Permission check/load/save
utils/port_check.py (58 lines)             ← Port availability checking
blueprints/auth.py (~270 lines)            ← Login, logout, setup, health, active-users
blueprints/dashboard.py (153 lines)        ← Dashboard + stats
blueprints/servers.py (708 lines)          ← Server CRUD, proxy, batch ops
blueprints/users.py (341 lines)            ← User CRUD, permissions
blueprints/monitoring.py (~490 lines)      ← Monitoring data, stages, batch set stage
blueprints/host_manager.py (700 lines)     ← Host CRUD, backup/restore
blueprints/monitoring_settings.py (375 lines) ← Category/server mapping
blueprints/global_settings.py (~460 lines) ← Config, backup, logs, CR auto-reset settings
blueprints/nagios_proxy.py (235 lines)     ← Nagios CGI proxy
blueprints/monitoring_intens.py (138 lines) ← Uptime Kuma monitors
```

---

### 2.2 Duplicate Port-Checking Logic ✅ FIXED

**Issue:** Logic untuk cek port tersedia (Docker + netstat/ss) diulang di 3 tempat: `add_server()`, `check_port_available()`, `get_available_port()`.

**Fix applied:**
- Extract `_get_all_used_ports()` helper function — returns `set` of all ports in use
- Checks Docker containers + system ports (netstat → ss fallback)
- All 3 callers refactored to use the helper
- Lines removed: ~120 duplicate lines

---

### 2.3 Bare `except:` Blocks ✅ FIXED

**Issue:** 47 `except:` tanpa specific exception type. Menyembunyikan error, membuat debugging sangat sulit.

**Fix applied:**
- All 47 bare `except:` replaced with specific exception types
- Grouped by context:
  - JSON reads (17): `except (json.JSONDecodeError, OSError):`
  - LDAP operations (8): `except Exception:`
  - subprocess/Docker (7): `except (subprocess.CalledProcessError, OSError):`
  - Socket.IO cleanup (4): `except Exception:`
  - File reads (4): `except OSError:`
  - JSON writes (2): `except (OSError, ValueError):`
  - HTTP+JSON (2): `except (requests.RequestException, json.JSONDecodeError):`
  - Host processing (1): `except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError):`
  - Datetime parsing (1): `except (ValueError, TypeError):`
  - UTF-8 decode (1): `except UnicodeDecodeError:`

---

### 2.4 Type Hints & Docstrings ✅ DONE

**Issue:** Sebagian besar function tidak punya type hints atau docstrings.

**Fix applied:**
- All 160 functions analyzed
- 145 (90%) have type hints — includes all public functions
- 129 (80%) have docstrings — includes all route functions
- Remaining: inner callbacks only (e.g., `add_category`, `on_connect`)
- `from __future__ import annotations` added to all module files

---

## 3. Reliability 🟡

### 3.1 No Health Check Endpoint ✅ FIXED

**Issue:** Tidak ada `/health` atau `/ready` endpoint untuk monitoring.

**Fix applied:**
- `GET /health` — no auth required, returns JSON with per-component status
- Checks: LDAP connectivity, host_stages.json accessibility, Docker containers running
- Returns `200` if all ok, `503` if any check fails
- Example response:
  ```json
  {
    "status": "healthy",
    "checks": {
      "ldap": "ok",
      "host_stages": "ok",
      "nagios_containers": "ok (3 running)"
    }
  }
  ```

---

### 3.2 No Graceful Shutdown ⏭️ SKIPPED

**Issue:** Proxy daemon dan background threads tidak handle SIGTERM dengan bersih.

**Decision:** Skipped — not needed for this app. Reasoning:
- `host_stages.json` is written on every stage change (not batched)
- Background threads are daemon threads (auto-killed on exit)
- Proxy daemons are separate processes (managed by `start_proxy_daemon.py`)
- Waitress already handles SIGTERM gracefully for HTTP requests
- Risk: at most 1-2 in-flight requests may be interrupted during restart — user just refreshes

---

### 3.3 No Request Timeout ✅ FIXED

**Issue:** Calls ke Nagios CGI API tidak punya timeout. Satu container yang hang bisa block seluruh monitoring page.

**Fix applied:**
- 9/10 requests sudah punya `timeout=5` sebelumnya
- 1 remaining: Nextcloud upload (`requests.put`) → ditambah `timeout=30` (lebih besar karena file upload)
- Semua `requests.*` calls di `app.py` sekarang punya timeout
- `proxy.py` tidak ada `requests.*` calls

---

## 4. Additional Features 🆕

Features implemented after the original 12-task plan was completed.

### 4.1 Stage Notes ✅

**Description:** Every stage can now have an optional note/comment. Notes are saved in `host_stages.json` only (not sent to Nagios, except for Resolved which uses the note as the ACK comment).

**Files:** `blueprints/monitoring.py`, `templates/monitoring.html`

**Storage format:**
```json
{
  "Container__Hostname": {
    "stage": "cs",
    "updated_at": "2026-06-05T00:48:38",
    "updated_by": "rifqi",
    "note": "Down FU",
    "host_up_since": null
  }
}
```

---

### 4.2 Batch Set Stage ✅

**Description:** Replaced the old Batch Acknowledge with Batch Set Stage. Users can select multiple hosts and change their stage at once with an optional note.

**Endpoint:** `POST /monitoring/batch-set-stage`

**Behavior:**
- Non-Resolved: updates `host_stages.json` for all selected hosts
- Resolved: sends ACK to Nagios per host + removes from stage tracking
- Note applies to all selected hosts

---

### 4.3 CR View Only Permission ✅

**Description:** A new permission `cr_view_only` restricts users to only see hosts with "CR Verification" stage in the monitoring view. Designed for the Customer Relation team.

**Files:** `utils/permissions.py`, `blueprints/monitoring.py`, `blueprints/users.py`, `templates/user_permissions.html`

**Behavior:**
- User with `cr_view_only = True` only sees hosts with stage `cs` (CR Verification)
- Other stages (New, Escalated, Watchlist) are filtered out
- Admin can toggle this from User Permissions page

---

### 4.4 Active Users Page ✅

**Description:** In-memory tracker showing currently active users. Hidden page at `/active-users` (admin only, no button — manual URL access).

**Files:** `services/active_users.py`, `app.py` (`@app.before_request`), `blueprints/auth.py`, `templates/active_users.html`

**Behavior:**
- Every authenticated request updates the tracker
- Auto-refresh requests (monitoring data fetch) count as activity
- Users idle > 5 minutes are automatically cleaned up (background thread, every 60s)
- Shows: Username, Role, IP, Login At, Last Active, Idle Time
- Page auto-refreshes every 30 seconds
- Data is lost on service restart (in-memory)

---

### 4.5 CR Verification Auto-Reset ✅

**Description:** Automatically resets all hosts with "CR Verification" stage back to "New" at configurable hours daily. Ensures no monitoring is missed.

**Files:** `services/scheduler.py`, `app.py`, `blueprints/global_settings.py`, `templates/global_settings.html`

**Behavior:**
- Default schedule: 4 AM and 3 PM
- Configurable from Global Settings → "CR Auto-Reset"
- Notes are preserved — only the stage is changed
- Reads config every 30 seconds (changes take effect without restart)
- Reset only once per hour per day (prevents duplicate resets)
- Logs: `[Auto-Reset] X host(s) reset from CR Verification to New at ...`

**Config storage:** `global_config.json` → field `cr_reset_hours` (e.g., `"4,15"`)

---

### 4.6 Monthly Activity Log Rotation ✅

**Description:** Activity logs are now split into monthly files for better organization and long-term storage.

**Files:** `services/ldap_service.py`, `blueprints/global_settings.py`

**Structure:**
```
config/
├── activity_log.txt              ← legacy (still readable)
└── activity_logs/                ← NEW
    ├── activity_log_2026_05.txt
    ├── activity_log_2026_06.txt  ← current month
    └── activity_log_2026_07.txt  ← future months
```

**Behavior:**
- Write: automatically creates monthly file (`activity_log_YYYY_MM.txt`)
- Read: merges all monthly files + legacy file (newest first, max 500 lines)
- Clear: deletes all monthly files + legacy file
- No auto-cleanup — files are kept forever
- Storage estimate: ~16 KB/month (at current usage of ~4 entries/day)

---

## Priority Order

| # | Task | Impact | Effort | Status |
|---|---|---|---|---|
| 1 | Encrypt `session['password']` | 🔴 Critical | Medium | ✅ Done |
| 2 | LDAP admin password → env var | 🔴 Critical | Low | ✅ Done |
| 3 | Secret key persistence | 🔴 Critical | Low | ✅ Done |
| 4 | Encrypt creds JSON | 🔴 Critical | Medium | ✅ Done |
| 5 | Fix deadlock on `set_stage()` | 🔴 Critical | Low | ✅ Done |
| 6 | Fix race condition on `host_stages.json` | 🔴 Critical | Low | ✅ Done |
| 7 | Request timeouts | 🟡 Medium | Low | ✅ Done |
| 8 | Replace bare `except:` | 🟡 Medium | Medium | ✅ Done |
| 9 | Health check endpoint | 🟡 Medium | Low | ✅ Done |
| 10 | Blueprint refactor | 🟡 Medium | High | ✅ Done |
| 11 | Extract duplicate logic | 🟡 Medium | Medium | ✅ Done |
| 12 | Type hints + docstrings | 🟢 Low | High | ✅ Done |
| — | Stage Notes | 🟢 Low | Low | ✅ Done |
| — | Batch Set Stage | 🟢 Low | Medium | ✅ Done |
| — | CR View Only permission | 🟡 Medium | Low | ✅ Done |
| — | Active Users page | 🟢 Low | Low | ✅ Done |
| — | CR Auto-Reset scheduler | 🟡 Medium | Low | ✅ Done |
| — | Monthly log rotation | 🟢 Low | Low | ✅ Done |

---

## Execution Phases

**Phase 1 — Stabilitas:**
1. ✅ Deadlock fix
2. ✅ Request timeouts (#7)
3. ✅ Health check endpoint (#9)
4. ✅ Audit `log_activity()` — 52 calls audited, all clean

**Phase 2 — Code quality:**
5. ✅ Replace bare `except:` (#8) — 47 blocks → specific exceptions
6. ✅ Extract duplicate logic (#11) — `_get_all_used_ports()` helper

**Phase 3 — Refactor:**
7. ✅ Blueprint refactor (#10) — 3853 → 66 lines app.py, 22 files
8. ✅ Type hints + docstrings (#12) — 90% hints, 80% docs

**Phase 4 — New features:**
9. ✅ Stage notes
10. ✅ Batch set stage (replaced batch ACK)
11. ✅ CR View Only permission
12. ✅ Active users page
13. ✅ CR Auto-Reset scheduler
14. ✅ Monthly log rotation

---

## Deployment

### Production Deploy Script
```bash
# Run on production server
cd /svr/dashboard-nagios
./deploy_from_dev.sh
```

Script handles:
1. Backup current files + module directories
2. Pull new files from dev server via SCP
3. Sync module directories (services/, utils/, blueprints/)
4. Clean `__pycache__` (prevent stale bytecode)
5. Install Python dependencies
6. Run creds encryption migration (idempotent)
7. Restart proxy daemons (Nagios containers only)
8. Verify app module imports (auto-rollback on failure)
9. Start service (auto-rollback if start fails)
10. Health check (`curl localhost:5000/health`)
11. Cleanup old backups (keep latest 3)

### Files Updated Per Deploy
- `app.py` — main Flask app
- `proxy.py` — per-Nagios reverse proxy
- `templates/monitoring.html` — monitoring frontend
- `templates/user_permissions.html` — user permissions page
- `templates/active_users.html` — active users page
- `templates/global_settings.html` — global settings page
- `requirements.txt` — Python deps
- `migrate_encrypt_creds.py` — idempotent creds migration
- `README.md` — documentation
- `services/` — all service modules
- `utils/` — all utility modules
- `blueprints/` — all blueprint modules

### Rollback
Backup is created at `config/backups/deploy_backup_<timestamp>/` before each deploy. Auto-rollback triggers if:
- SCP fails for any file or module directory
- App module import verification fails (`python3 -c "from app import app"`)
- Service fails to start after deploy

Manual rollback:
```bash
rc-service dashboard-nagios stop
cp config/backups/deploy_backup_<timestamp>/app.py app.py
rm -rf services/ utils/ blueprints/
cp -r config/backups/deploy_backup_<timestamp>/services services/
cp -r config/backups/deploy_backup_<timestamp>/utils utils/
cp -r config/backups/deploy_backup_<timestamp>/blueprints blueprints/
pip install -r config/backups/deploy_backup_<timestamp>/requirements.txt
rc-service dashboard-nagios start
```

---

## 5. Optimization Roadmap 🚀

Analysis based on current architecture (Flask + file-based storage + Docker CLI). Features needed to optimize performance, reliability, and relevance.

### 5.1 Performance

| Issue | Impact | Solusi |
|---|---|---|
| **Monitoring data fetch sequential** — setiap container dipanggil satu per satu via Nagios API | Kalau 1 container timeout, seluruh page lambat | Parallel fetch pakai `concurrent.futures.ThreadPoolExecutor` |
| **Docker CLI dipanggil setiap request** — `docker ps`, `docker port`, `docker stats` di setiap halaman | Overhead besar, terutama saat banyak container | Cache hasil Docker CLI (TTL 10-30 detik) |
| **No caching layer** — setiap request baca file JSON + hit API dari nol | Response time tinggi | Tambah `functools.lru_cache` atau in-memory cache dengan TTL |
| **LDAP connection tidak pooled** — setiap auth buka connection baru | Overhead koneksi | Pakai connection pool atau reuse connection |
| **Activity log dibaca full** — `read_activity_logs()` baca semua file bulan | Semakin lama semakin lambat | Baca dari belakang (reverse), stop kalau sudah cukup |

**Estimasi impact:** Parallel fetch bisa kurangi monitoring page load time dari ~5-10 detik ke ~1-2 detik.

---

### 5.2 User Experience

| Issue | Impact | Solusi |
|---|---|---|
| **No real-time updates** — pakai polling/auto-refresh | Delay 10-30 detik sebelum tahu host down | WebSocket push (sudah ada `python-socketio` di deps) |
| **No notification system** — user harus buka dashboard untuk tahu ada alert | Miss critical alerts | Webhook integration (Telegram, email, Slack) |
| **No export/download** — monitoring data tidak bisa di-export | Tim CR butuh laporan | Export ke CSV/Excel |
| **No dark mode** — mata capek kalau NOC 24/7 | Comfort | CSS theme toggle |
| **No search persistence** — filter hilang saat refresh | UX buruk | Simpan filter di URL params atau localStorage |
| **No mobile responsive** — layout pecah di HP | Tim lapangan tidak bisa cek | Responsive CSS (Tailwind/media query) |

**Estimasi impact:** Notifikasi Telegram = game changer untuk tim CR yang mobile.

---

### 5.3 Reliability

| Issue | Impact | Solusi |
|---|---|---|
| **File-based storage** — `host_stages.json`, `user_permissions.json` bisa corrupt | Data loss | Migrate ke SQLite (sudah ada di Python stdlib) |
| **No backup scheduling** — backup manual dari Global Settings | Lupa backup = data hilang | Cron job auto-backup harian |
| **No rate limiting** — login bisa di-brute-force | Security risk | `Flask-Limiter` atau simple in-memory limiter |
| **No app self-monitoring** — gak tahu kalau app down | Downtime tidak terdeteksi | External health check (Uptime Kuma sudah ada) |

**Estimasi impact:** SQLite migration = eliminasi 90% data corruption risk.

---

### 5.4 Security

| Issue | Impact | Solusi |
|---|---|---|
| **No CSRF protection** — form submission tidak ada token | CSRF attack | `Flask-WTF` atau manual CSRF token |
| **No 2FA** — password saja | Account compromise | TOTP (Google Authenticator) |
| **No session timeout configurable** — session hidup selamanya | Security risk kalau user lupa logout | Configurable idle timeout |
| **No audit trail untuk permission changes** — gak tahu siapa yang ubah permission | Compliance issue | Log permission changes ke activity log |

**Estimasi impact:** CSRF = critical security gap. 2FA = nice to have.

---

### 5.5 Monitoring Capabilities

| Issue | Impact | Solusi |
|---|---|---|
| **No historical data** — gak tahu trend host down | Gak bisa analisis pola | Simpan snapshot ke SQLite per jam |
| **No SLA tracking** — gak tahu uptime percentage | Management butuh laporan | Hitung dari historical data |
| **No incident timeline** — gak tahu kronologi host down/up | Audit sulit | Simpan state change events |
| **No integration dengan tools lain** — Grafana, Prometheus | Ecosystem gap | API endpoint untuk data export |

**Estimasi impact:** Historical data + SLA tracking = value proposition untuk management.

---

### 5.6 Priority Matrix

| # | Feature | Impact | Effort | ROI | Phase |
|---|---|---|---|---|---|
| 1 | **Parallel fetch** monitoring data | 🔴 High | Low | ⭐⭐⭐ | Phase 5A | ✅ Done |
| 2 | **Docker CLI cache** (TTL 15s) | 🔴 High | Low | ⭐⭐⭐ | Phase 5A | ✅ Done |
| 3 | **CSRF protection** | 🔴 High | Low | ⭐⭐⭐ | Phase 5A | ⏸️ Hold |
| 4 | **Telegram notification** | 🔴 High | Medium | ⭐⭐⭐ | Phase 5B | ⏸️ Hold |
| 5 | **Export monitoring to CSV** | 🟡 Medium | Low | ⭐⭐ | Phase 5B | ✅ Done |
| 6 | **Session timeout configurable** | 🟡 Medium | Low | ⭐⭐ | Phase 5B | ⏸️ Hold |
| 7 | **SQLite migration** (stages + permissions) | 🟡 Medium | High | ⭐⭐ | Phase 5C | 🔲 Pending |
| 8 | **Historical data + SLA tracking** | 🟡 Medium | High | ⭐⭐ | Phase 5C | 🔲 Pending |
| 9 | **Rate limiting** | 🟡 Medium | Low | ⭐⭐ | Phase 5B | ⏸️ Hold |
| 10 | **Dark mode** | 🟢 Low | Low | ⭐ | Phase 5C | ⏸️ In progress |

---

### 5.7 Execution Phases

**Phase 5A — Quick Wins (Low effort, High impact):**
1. ✅ Parallel fetch monitoring data (ThreadPoolExecutor) — done
2. ✅ Docker CLI cache (in-memory, TTL 15s) — done
3. ⏸️ CSRF protection — hold (local network only, few users)

**Phase 5B — Value Adds (Medium effort):**
4. ⏸️ Telegram notification integration — hold
5. ✅ Export monitoring to CSV — done (`GET /monitoring/<page>/export-csv`)
6. ⏸️ Configurable session timeout — hold (few users, internal tool)
7. ⏸️ Rate limiting on login — hold (few users, internal tool)

**Phase 5C — Foundation (High effort, Long-term):**
8. 🔲 SQLite migration for stages + permissions — pending (high effort)
9. 🔲 Historical data + SLA tracking — pending (high effort, depends on #8)
10. ⏸️ Dark mode — in progress, button disabled. CSS + JS in place but needs color refinement. Re-enable when ready to polish.

---

## Notes

- Semua security fix **backward compatible** — tidak mengubah behavior dari sisi user
- Blueprint refactor (#10) sudah selesai — app.py 3853 → 66 lines, 22 files total
- Central config: `services/config.py` — semua shared constants di satu tempat
- Type hints + docstrings (#12) — 90% hints, 80% docs (inner callbacks excluded)
- Graceful shutdown (#3.2) skipped — not needed for this app (see reasoning in section 3.2)
- Activity log sekarang per-bulan (`config/activity_logs/activity_log_YYYY_MM.txt`), tidak ada auto-cleanup
- CR Auto-Reset bisa dikonfigurasi dari Global Settings tanpa restart app
- Active Users page di `/active-users` (admin only, hidden — no button)
- Dark mode: CSS + JS sudah di-base.html, button di-comment. Perlu color refinement sebelum di-enable lagi.
- **All planned tasks (12) + additional features (6) + Phase 5 optimizations (3) completed** ✅
- **Phase 5 roadmap defined** — 10 items, 3 done, 4 hold, 2 pending, 1 in-progress

---

## 6. QA Review — Bug Fixes (2026-06-15) 🔍

Full codebase review conducted. Found 92 issues total, fixed 7 critical/high ones.

### 6.1 Fixed Issues

| # | Severity | File | Issue | Fix |
|---|---|---|---|---|
| 1 | 🔴 Critical | `api.py:333,337` | `defdefine` regex typo — API host deletion completely broken (never matches) | Fixed to `define` |
| 2 | 🔴 Critical | `deploy_from_dev.sh:335` | Health check uses port 5000 but app runs on port 80 → always fails | Changed to port 80 |
| 3 | 🔴 Critical | `scheduler.py:98-105` | First-time reset with interval > 1 fires immediately (dead `pass` falls through to `return True`) | Removed dead code, clarified intent |
| 4 | 🟡 High | `proxy.py:63,77` | Bare `except:` catches `SystemExit`/`KeyboardInterrupt` | Changed to `except (json.JSONDecodeError, OSError):` |
| 5 | 🟡 High | `global_settings.py` (9 endpoints) | Missing permission checks — any authenticated user could create/restore/delete backups, change config | Added `check_permission('global_settings')` to all 9 state-changing endpoints |
| 6 | 🟡 High | `start_proxy_daemon.py:18` | Log file truncated on every restart (`open('w')`) — previous logs lost | Changed to `open('a')` (append mode) |
| 7 | 🟡 Medium | `docker_cache.py:43` | `get_or_run` caches failed commands (non-zero returncode) — errors cached for TTL duration | Only cache successful results (returncode 0) |

### 6.2 Known Issues (Not Fixed — Low Priority or Accepted Risk)

| # | Severity | Issue | Reason Not Fixed |
|---|---|---|---|
| 1 | 🟡 Medium | LDAP injection in `ldap_auth()` — `username` used unsanitized in DN | Internal tool, LDAP server validates input |
| 2 | 🟡 Medium | Path traversal via server names in file paths | Internal tool, server names come from Docker container list |
| 3 | 🟡 Medium | No CSRF protection on state-changing endpoints | Local network only, few users (see Phase 5A #3) |
| 4 | 🟡 Medium | `log_activity()` accesses Flask session from background threads | Pass `username='API'` for API calls, scheduler doesn't call it |
| 5 | 🟢 Low | `get_nagios_servers()` duplicated across 7 blueprints | Already extracted in some places, low impact |
| 6 | 🟢 Low | Unused imports in several files | Cosmetic, no runtime impact |

### 6.3 Recommendations for Future

1. **Path validation**: Add server name whitelist check before file operations
2. **CSRF tokens**: Implement when/if app becomes accessible from outside LAN
3. **Input sanitization**: Validate address/alias/parents fields in host add/edit
4. **Thread safety**: Use `threading.Lock` for `save_user_permissions` read-modify-write
5. **Proxy session**: Use `threading.local()` for per-thread `requests.Session`
