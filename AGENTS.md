# AGENTS.md — AI Agent Context

This file provides comprehensive context for AI agents working on the Nagios Dashboard project. Read this file first before making any changes.

---

## Project Overview

**Nagios Dashboard** is a Flask-based web application that serves as a centralized management and monitoring dashboard for multiple Nagios server instances running in Docker containers. It uses LDAP for authentication. **Settings** (categories, mappings, permissions) stay in gitignored JSON. **Host stages** and the **Nagios CGI snapshot** live in SQLite WAL (`config/host_stages.db`, `config/nagios_snapshot.db`). Production is an Alpine Linux LXC with a **~2 GB RAM** budget (no swap).

**Repository:** https://github.com/PandiMusR/nagios-dashboard  
**Production path:** `/svr/dashboard-nagios` (on prod server `103.73.74.98:2325`, user `rif`)  
**Dev path:** `/root/apps/nagiosDashboard` (on dev VPS `194.233.73.24:5000`)  
**Production OS:** Alpine Linux (OpenRC init system, not systemd)  
**Prod SSH:** `ssh -p 2325 rif@103.73.74.98` (authorized key configured)  
**Docker sudo:** `echo "<pass>" | sudo -S docker ...` (rif user needs sudo for docker)

---

## Technology Stack

| Layer | Technology | Version |
|---|---|---|
| Language | Python | 3.12+ |
| Web Framework | Flask | 3.0.0 |
| WSGI Server | Waitress | 2.1.2 |
| Auth | LDAP (OpenLDAP via `ldap3`) | 2.9.1 |
| CSRF Protection | Flask-WTF | 1.3.0 |
| Container Runtime | Docker CLI | — |
| Encryption | Fernet (AES-128-CBC via `cryptography`) | ≥41.0.0 |
| HTTP Client | `requests` (poller / ACK) | ≥2.32.0 |
| Async HTTP | `aiohttp` (iframe multiplexer only) | ≥3.10.0 |
| Snapshot / stages | SQLite WAL | stdlib |
| Init | OpenRC | `dashboard-nagios`, `nagios-poller`, `nagios-proxy` |
| Socket.IO | `python-socketio` | 5.9.0 |
| Frontend | Jinja2 + Bootstrap 5.3 + vanilla JS | — |
| Font | Inter (Google Fonts) | — |
| Icons | Font Awesome 6.4 | — |
| Linting | ruff | 0.15+ |

---

## Directory Structure

```
nagiosDashboard/
├── app.py                    # App factory. Registers blueprints, inits encryption, starts CR scheduler.
├── proxy.py                  # UNUSED leftover. Do not spawn per-container proxies.
├── start_proxy_daemon.py     # Controls the nagios-proxy multiplexer (OpenRC / start-stop)
├── start_proxy.sh            # Shell helper for the multiplexer
├── migrate_encrypt_creds.py  # Idempotent: encrypts plaintext creds JSON files
├── migrate_stages_to_db.py   # One-off: host_stages.json → host_stages.db
├── deploy_from_dev.sh        # Production deployment script (SCP from dev → prod)
├── full_backup.sh            # Full backup script (app + config + Docker + LDAP)
├── requirements.txt
├── .cursorrules              # Persistent AI session directives (architecture constraints)
├── .gitignore
├── README.md / USER_GUIDE.md
│
├── services/                 # Backend service modules
│   ├── config.py             # ** CENTRAL CONFIG ** — APP_ROOT, LDAP, paths, stage definitions
│   ├── nagios_poller.py      # OpenRC nagios-poller — CGI fetch → nagios_snapshot.db
│   ├── nagios-poller.initd
│   ├── poller_db.py          # Snapshot SQLite helpers
│   ├── async_proxy.py        # OpenRC nagios-proxy — ONE aiohttp multiplexer (port+1000)
│   ├── nagios-proxy.initd
│   ├── proxy_control.py      # start/stop/reload multiplexer
│   ├── encryption.py         # Fernet encrypt/decrypt
│   ├── ldap_service.py       # LDAP connection, auth, log_activity
│   ├── stage_db.py           # host_stages.db WAL, per-row UPSERT/DELETE
│   ├── stage_service.py      # Façade over stage_db (no JSON rewrite)
│   ├── stage_history.py      # Persistent stage change audit log (monthly JSONL)
│   ├── active_users.py       # In-memory active session tracker
│   ├── scheduler.py          # CR Verification auto-reset (background thread)
│   ├── docker_cache.py       # Docker name/port list cache (TTL 15s) — not docker stats
│   ├── shared_helpers.py     # get_nagios_servers / get_monitoring_categories
│   ├── uptime_kuma.py        # Socket.IO client for Uptime Kuma
│   └── nextcloud.py          # WebDAV upload to Nextcloud share
│
├── utils/
│   ├── permissions.py
│   └── port_check.py
│
├── blueprints/
│   ├── auth.py               # /, /login, /logout, /setup, /health, Audit pages
│   ├── dashboard.py          # /dashboard/stats ← SELECT snapshot (no docker stats, no live CGI)
│   ├── servers.py            # Server CRUD; reload multiplexer on port change
│   ├── users.py
│   ├── monitoring.py         # /monitoring/<page>/data ← SELECT snapshot
│   ├── host_manager.py
│   ├── monitoring_settings.py
│   ├── global_settings.py
│   ├── nagios_proxy.py       # Flask iframe helper routes (not the multiplexer process)
│   ├── monitoring_intens.py  # Uptime Kuma monitors page (NOT Intensive ping — that is HOLD)
│   └── api.py
│
├── config/                   # GITIGNORED
│   ├── *.json                # Settings, mappings, encrypted creds
│   ├── host_stages.db        # Stage workflow (SQLite WAL)
│   ├── nagios_snapshot.db    # Poller CGI snapshot + container_health
│   ├── secret_key
│   ├── activity_logs/ / stage_history/ / backups/
│
├── create-nagios/            # Docker image build (manios/nagios:4.4.14 + LDAP)
├── static/ / templates/
├── AGENTS.md / IMPROVEMENT_PLAN.md / TRENDS_DUMMY_GUIDE.md
└── create-nagios/README.md
```

**Intensive Monitoring** (`blueprints/intensive.py`, `intensive_worker.py`, `intensive_db.py`) is **ON HOLD**. Deploy strips those files (`INTENSIVE_HOLD_EXCLUDE`). Do not re-enable.

---

## Runtime architecture (Phases 1–3, deployed)

Flask/Waitress (8 threads) is a **thin HTTP layer**. It must not fan out live Nagios CGI or `docker stats` on a browser request. Production RAM is ~2 GB; the old 14× `proxy.py` farm used ~530 MB RSS. The multiplexer is ~40 MB; the poller is ~50 MB.

| OpenRC service | Process | Role |
|---|---|---|
| `dashboard-nagios` | `app.py` / Waitress | UI, LDAP, set-stage, Host Manager, ACK on resolve only |
| `nagios-poller` | `services/nagios_poller.py` | CGI poll ~30s → UPSERT `nagios_snapshot.db`; stage auto-detect; circuit breaker |
| `nagios-proxy` | `services/async_proxy.py` | One asyncio process; bind `0.0.0.0:(nagios_port+1000)` per container; Basic Auth from `nagios_creds_*.json` |

Iframe URL: `http://<host>:<proxy_port>/` (`templates/nagios_view.html`). SIGTERM must wake the asyncio wait so OpenRC stop does not hang (`retry="TERM/5/KILL/2"`).

Poller credentials: `config/nagios_creds_<container>.json` (not the logged-in LDAP password).

---

## Core Business Logic

### Authentication Flow
1. User submits credentials → `ldap_auth()` binds to LDAP with user DN
2. On success: session stores `username`, encrypted `password` (Fernet), `role`, `permissions`
3. Role detection: if all main permissions enabled OR member of `nagiosadmins` LDAP group → admin
4. `@app.before_request` updates `active_users` tracker on every authenticated request

### Stage Tracking System
When a host goes DOWN, it enters a stage workflow managed entirely by the dashboard:

| Stage | Code | Description |
|---|---|---|
| New / Unacknowledged | `new` | Default for new DOWN hosts |
| CR Verification | `cs` | Customer Relation team checking |
| Escalated / Pending | `escalated` | Waiting on third party |
| Watchlist / Flapping | `watchlist` | Unstable host, being watched |
| Resolved | `resolved` | ACK to Nagios, removes from list |

**Key behaviors:**
- Non-resolved stages only update `host_stages.db` (per-row UPSERT) — Nagios is NOT touched
- Resolved sends ACK command to Nagios CGI and deletes the stage row
- Flapping retention: Watchlist stage preserved for 30 minutes if host recovers
- CR Auto-Reset: background scheduler resets `cs` → `new` at configurable hours
- Stage history: every stage change recorded in `config/stage_history/` (JSONL, monthly files), including:
  - Manual stage changes by users (set-stage, batch-set-stage)
  - CR Auto-Reset by scheduler (`cs` → `new`)
  - **Auto-detect events by system:** host first DOWN (`up` → `new`), host recovered (`<stage>` → `up`),
    DOWN again while flapping (`up` → `<stage>`), watchlist retention (30min expiry)
- Storage: SQLite WAL via `services/stage_db.py` (façade `stage_service.py`). No `load_host_stages` / whole-file rewrite. Legacy JSON was migrated by `migrate_stages_to_db.py`.

### Monitoring Data Flow
1. **Background:** `nagios-poller` fetches CGI (`statusjson.cgi`) per container, UPSERTs `nagios_snapshot.db`, records fetch errors / circuit-breaker, reconciles stages
2. Browser requests `/monitoring/<category>/data`
3. Flask loads `monitoring_server_mappings.json` for the category
4. Flask **SELECT**s hosts/services from the snapshot (milliseconds). No `requests.get` CGI and no `ThreadPoolExecutor` fan-out on this path
5. CR View Only filter applied if user has `cr_view_only` permission
6. JSON response with host list, stage info, and incomplete/error metadata from `container_health`

`/dashboard/stats` is the same snapshot read — **no** live Docker CPU/memory stats.

### Permission System
Stored in `config/user_permissions.json` per user:
```json
{
  "dashboard": true,
  "monitoring": true,
  "servers": false,
  "users": false,
  "host_manager": false,
  "monitoring_settings": false,
  "global_settings": false,
  "user_permissions": false,
  "cr_view_only": false,
  "nagios_<server>": true/false,
  "monitoring_<category>": true/false
}
```
Admin bypasses all checks. Admin = all main permissions enabled OR `nagiosadmins` LDAP group member.

### Encryption
- **Session passwords:** Fernet-encrypted before storing in Flask session
- **Credentials at rest:** `user_passwords.json` and `nagios_creds_*.json` encrypted with `__ENC__` prefix
- **Secret key:** Persistent at `config/secret_key`, auto-generated on first run
- **Fernet key:** Derived from SHA-256 hash of secret key

---

## Key Patterns and Conventions

### Path Handling
- `services/config.py` defines `APP_ROOT` via `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- All config paths derived from `APP_ROOT` — no hardcoded absolute paths in Python files
- Docker volume base (`/svr/<server>/`) is still hardcoded — this is intentional (see IMPROVEMENT_PLAN.md)
- Shell scripts (`deploy_from_dev.sh`, `full_backup.sh`) have hardcoded `PROD_PATH` — manually edited per environment

### Helper Functions
- `get_nagios_servers()` — centralized in `services/shared_helpers.py` with Docker CLI cache (8/8 blueprints migrated)
- `get_monitoring_categories()` — centralized in `services/shared_helpers.py` with JSON config cache (TTL 30s)
- Shared helpers module provides TTL-based JSON caching and thread-safe Docker operations
- All blueprint files import from `services.shared_helpers`, eliminating 16 duplicate copies

### Thread Safety / I/O rules
- Host stages: SQLite WAL + per-row UPSERT/DELETE (`stage_db.py`). Do not rewrite a JSON dict of all hosts.
- `DockerCache` (`threading.Lock`, TTL 15s) is for **container name/port lists** used by Servers/Host Manager — not `docker stats` on the dashboard.
- `ActiveUsersTracker` protected by `threading.Lock` with background cleanup thread
- `scheduler.py` has `_config_lock` for `global_config.json` writes
- **Never** add synchronous Nagios CGI or `docker stats` to the Flask request-response cycle. Read `nagios_snapshot.db`.
- **Never** spawn multiple `proxy.py` processes. One `async_proxy.py` multiplexer only.

### Error Handling
- All bare `except:` blocks replaced with specific exception types (47 total, fixed)
- JSON reads: `except (json.JSONDecodeError, OSError):`
- LDAP operations: `except Exception:` → `logger.warning()`
- subprocess/Docker: `except (subprocess.CalledProcessError, OSError):`
- Error responses use generic messages, no `str(e)` leak

### CSRF Protection
- Flask-WTF global protection with 4 exempts: `api_bp`, `auth_bp`, `monitoring_bp`, `nagios_proxy_bp`
- Meta tag approach: `<meta name="csrf-token" content="{{ csrf_token() }}">` in base.html head
- AJAX: `csrfFetch()` reads from meta tag, no DOM search needed
- Form POST: `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` inside `<form>`
- Dynamic forms (JS-created): read token from meta tag
- No standalone `{{ csrf_token() }}` outside HTML attributes (prevents raw text leak)
- `WTF_CSRF_TIME_LIMIT = None` (internal dashboard, no token expiry)

### Permission System
- Dual-mode: `audit` (log-only, default) → `enforce` (403 block)
- Mode stored in `monitoring_config.json` → `permission_check_mode`
- `check_permission()` in `utils/permissions.py` with JSONL audit logging
- Admin bypass: all main permissions enabled OR `nagiosadmins` LDAP group

---

## Recent Changes (as of 2026-08-29)

### Architecture Phases 1–3 (2026-08) — Production
- **Phase 1:** `host_stages.json` → SQLite WAL (`host_stages.db`), per-row ops, `migrate_stages_to_db.py`
- **Phase 2:** `nagios-poller` OpenRC + `nagios_snapshot.db`. Monitoring `/data` and dashboard stats are snapshot SELECTs. Waitress no longer fans out live CGI.
- **Phase 3:** Single `async_proxy.py` multiplexer (`nagios-proxy` OpenRC) replaces 14× `proxy.py`. Bind `0.0.0.0`, SIGTERM wakes asyncio stop (commit `ce98d25`). Dashboard cards no longer show Docker CPU/mem.
- RAM: multiplexer ~40 MB vs ~530 MB for the old proxy farm — required on the 2 GB LXC.

### Settings UI redesign + theme (2026-07-21)
- **Theme Batch A/B** on `main` and prod (`theme_deploy_20260721_025201`)
- **`{% block extra_css %}`** in `base.html` `<head>` for page CSS (avoid body-only stylesheet links)
- **`/monitoring-settings`**: modern redesign (hero, sticky tabs, category cards, mapping chips, alarm accordion + CSS toggles); full-width content; Waitress restart required after class-namespace redesigns
  - Commits: `8e2062d` → `3d8e22e` → `33df9f2` → `d5ede70` → `173072a`
  - Prod: `ms_ui_deploy_20260721_033712` (UI only; config PRE==POST)
- **`/global-settings`**: same UI pattern; **Activity Logs panel removed** (link to **Audit → Activity Logs**); backup JS classes preserved
  - Commit: `72c9950`
  - Prod: `gs_ui_deploy_20260721_034854` (UI only; config PRE==POST)
- UI-only prod deploy: backup target files, SCP templates/css/js only, never `config/`, MD5 verify local==prod + config unchanged

### Security Audit: Phase 1-4 (2026-07-12)
Comprehensive security audit covering P0-P3 vulnerabilities.

**Phase 1 (P0) — Critical Security:**
- CSRF protection via Flask-WTF with meta tag approach for AJAX
- CSRF exempts: `api_bp`, `auth_bp`, `monitoring_bp`, `nagios_proxy_bp`
- `WTF_CSRF_TIME_LIMIT = None` (internal dashboard, no expiry)
- LDAP admin password via env var (`_require_env()` in config.py)
- Removed hardcoded `nagiosadmin:nagiosadmin` fallback
- 60+ `check_permission()` calls across 7 blueprints
- Password encryption at rest (`__ENC__` marker, Fernet)
- Permission audit mode: `audit` (log-only) → `enforce` (403 block)

**Phase 2 (P1) — High Priority:**
- `tar.extractall(filter='data')` path traversal fix
- Sound file upload whitelist (`.wav`, `.mp3`, `.ogg`, `.m4a`, `.aac`)
- `secure_filename()` for plugin upload
- Container name validation before `rm -rf`
- Uptime Kuma username from config (not hardcoded `'admin'`)

**Phase 3 (P2) — Code Quality:**
- Debug `print()` removed from production paths
- `str(e)` replaced with generic error messages
- Silent `except: pass` → `logger.warning()`
- LDAP injection fix: `escape_filter_chars()` on search filter
- PROXY_PORT_OFFSET extracted to `services/config.py`

**Phase 4 (P3) — Cleanup:**
- `requests>=2.32.0` (was 2.31.0)
- `.env.example` created
- `*_old.html` templates removed
- `pyproject.toml` with ruff config

### CSRF Implementation Details
- `<meta name="csrf-token" content="{{ csrf_token() }}">` in `<head>` (base.html)
- `csrfFetch()` JS function reads from meta tag for AJAX calls
- Form POST: `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` inside `<form>`
- Dynamic forms (JS-created): read token from meta tag via `document.querySelector`
- No standalone `{{ csrf_token() }}` outside HTML attributes (prevents raw text leak)

### Monitoring Categories Fix (2026-07-12)
- `get_monitoring_categories()` in `shared_helpers.py` was extracting ALL top-level keys from `monitoring_config.json`
- Non-category keys (`refresh_interval`, `category_settings`, `alarm_settings`) appeared as fake categories
- Fixed: only extract from `category_settings` and `alarm_settings` sub-dicts

### API: ONU Host Auto-Parse (2026-07-03)
- `POST /api/hosts/add` and `POST /api/hosts/batch-add` now auto-parse host_name in ONU format
- **Input format:** `<Customer ID> - <ID NE> - <site name>` (3 parts separated by ` - `)
- **Auto-transform:** Rearranges to `<ID NE> - <site name> - <Customer ID>` for Nagios host_name
- **Auto-service:** Adds `check_status_onu` service with ID NE as argument (if no explicit `service_plugin`)
- **Response:** Includes `original_host_name` field when transformation occurs
- **Not server-specific:** Works for any Nagios server, no hardcoded container names
- Helper function: `_parse_onu_host_name()` in `blueprints/api.py`
- If host_name doesn't match 3-part format, behavior is unchanged (backwards compatible)

### Navigation Redesign (2026-06-28)
- Added **"Audit"** top-level sidebar menu with two sub-menus:
  - **Stage History** (`/stage-history`) — persistent audit log of stage changes
  - **Activity Logs** (`/activity-logs`) — new standalone page for user activity logs
- Auto-submit on limit dropdown change in both pages

### Activity Logs Page
- New route `GET /activity-logs` in `blueprints/auth.py`
- New template `templates/activity_logs.html`
- Standalone page with limit selector, refresh, clear logs (admin only)
- **Canonical UI for activity logs** — do not re-embed a full log viewer on Global Settings

### Path Refactoring
- All hardcoded `/svr/dashboard-nagios` paths replaced with `APP_ROOT` auto-detection
- `services/config.py` auto-detects `APP_ROOT` from `__file__` location
- `async_proxy.py`, `nagios_poller.py`, `start_proxy_daemon.py`, `migrate_encrypt_creds.py` use `__file__` / `APP_ROOT`
- `blueprints/servers.py` and `blueprints/monitoring_settings.py` import `APP_ROOT` from config

### Git Repository
- Initialized git repo with comprehensive `.gitignore`
- Pushed to https://github.com/PandiMusR/nagios-dashboard
- Remote uses SSH (`git@github.com:PandiMusR/nagios-dashboard.git`)
- Old templates (`*_old.html`), internal dev docs (`CHANGE_PASSWORD_FEATURE.md`), runtime config excluded from tracking

---

## Deployment Workflow

### Development → Production
1. Developer makes changes on dev VPS (`/root/apps/nagiosDashboard/`)
2. On prod server, run: `cd /svr/dashboard-nagios && ./deploy_from_dev.sh`
3. Script SCPs files from dev → prod, backs up, verifies, restarts

### Deploy Script Steps
1. Backup current files + module directories
2. Pull files from dev server via SCP (SSH ControlMaster for single password prompt)
3. Clean `__pycache__`
4. Stop OpenRC `dashboard-nagios`
5. Install Python dependencies
6. Run creds encryption migration (idempotent)
7. Restart the **single** `nagios-proxy` multiplexer (`start_proxy_daemon.py restart`) — not 14× `proxy.py`
8. Verify app imports (auto-rollback on failure)
8b. Migrate stages JSON → SQLite if needed (`migrate_stages_to_db.py`)
9. Start `dashboard-nagios` (auto-rollback on failure)
10. Health check (`GET /health`)

After poller code changes, restart `nagios-poller` explicitly (`rc-service nagios-poller restart`). After `async_proxy.py` / initd changes, copy initd if needed and `rc-service nagios-proxy restart`.

### Files Deployed
**Individual files** (`FILES_TO_UPDATE`): see `deploy_from_dev.sh` (app, templates, CSS/JS, `README.md`, `USER_GUIDE.md`, `migrate_*.py`, `start_proxy_*`).

**Module directories** (`MODULE_DIRS`): `services/`, `utils/`, `blueprints/` (Intensive HOLD files stripped after SCP).

### Adding New Files to Deploy
If you create a new file that needs to be deployed:
- **Template:** Add to `FILES_TO_UPDATE` array in `deploy_from_dev.sh`
- **Python module:** If in `services/`, `utils/`, or `blueprints/`, it's auto-deployed via `MODULE_DIRS`
- **Standalone script:** Add to `FILES_TO_UPDATE` manually

---

## Production Access

### SSH

```bash
ssh -p 2325 rif@103.73.74.98
```

- **Host:** `103.73.74.98`
- **Port:** `2325`
- **User:** `rif`
- **Auth:** SSH authorized key (passwordless)
- **OS:** Alpine Linux (OpenRC)

### Docker (requires sudo)

User `rif` tidak punya akses Docker langsung. Semua perintah Docker harus pakai sudo:

```bash
echo "<password>" | sudo -S docker ps
echo "<password>" | sudo -S docker exec <container> <command>
echo "<password>" | sudo -S docker restart <container>
echo "<password>" | sudo -S docker logs <container>
```

### Remote Command via SSH

```bash
# Contoh: cek status container
ssh -p 2325 rif@103.73.74.98 "echo '<password>' | sudo -S docker ps --filter 'ancestor=nagios-ldap:latest' --format '{{.Names}}'"

# Contoh: exec command di dalam container
ssh -p 2325 rif@103.73.74.98 "echo '<password>' | sudo -S docker exec Adiarsa cat /opt/nagios/var/status.dat"

# Contoh: jalankan Python script di dalam container
ssh -p 2325 rif@103.73.74.98 "echo '<password>' | sudo -S docker exec Adiarsa python3 -c 'print(\"hello\")'"
```

### File Locations on Production

| Path | Description |
|---|---|
| `/svr/dashboard-nagios/` | Dashboard app root |
| `/svr/<server>/etc/` | Nagios config (mounted to `/opt/nagios/etc/` in container) |
| `/svr/<server>/plugin/` | Nagios plugins (mounted to `/opt/nagios/libexec/` in container) |

### Nagios Container Internals

| Path (inside container) | Description |
|---|---|
| `/opt/nagios/etc/objects/localhost.cfg` | Host + service definitions |
| `/opt/nagios/etc/objects/commands.cfg` | Command definitions |
| `/opt/nagios/var/nagios.log` | Current log file |
| `/opt/nagios/var/archives/` | Rotated log archives (used by Trends) |
| `/opt/nagios/var/status.dat` | Current host/service status |
| `/opt/nagios/var/retention.dat` | Persistent status across restarts |

### Modifying Files Inside Containers

Alpine Linux containers use BusyBox `sed` yang berbeda dari GNU sed. **Gunakan Python** untuk modifikasi file:

```bash
# Salah (BusyBox sed escaping berbeda)
ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker exec Adiarsa sed -i 's/old/new/' /opt/nagios/var/status.dat"

# Benar (pakai Python)
ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker exec Adiarsa python3 -c '
with open(\"/opt/nagios/var/status.dat\") as f: lines = f.readlines()
lines[123] = \"new_value\n\"
with open(\"/opt/nagios/var/status.dat\", \"w\") as f: f.writelines(lines)
'"
```

### Known Container Names (as of 2026-07-03)

```
LaurensiaEnergiCorp_SPPBE, BackupLink-USB-LTE, TIF, Adiarsa,
Wifi-Public, OPD, Kelurahan, Kecamatan, TanjungMekar,
Tamelang-Cilamaya, Klari, Niaga, Bhome
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_PORT` | `80` | Flask app listen port |
| `LDAP_ADMIN_PASSWORD` | `admin` | LDAP admin bind password |

---

## Known Issues and Technical Debt

See `IMPROVEMENT_PLAN.md` for the living backlog. Current highlights:

1. **Docker volume paths hardcoded:** `/svr/<server>/` — intentional for this topology
2. **`monitoring_config.json`:** may contain host-local sound file paths after upload
3. **Intensive Monitoring:** HOLD — code stripped on Prod deploy; do not re-enable
4. **UI polish residual:** intens/edit_config tokens, shared form primitives, a11y depth

Done (2026-08): stages SQLite, CGI snapshot poller, iframe multiplexer, dashboard without docker stats. Historical plan: `MODERNIZATION_ROADMAP.md`.

---

## Important Notes

- **Do NOT add comments** to code unless explicitly asked
- **Do NOT commit** unless explicitly asked
- **Production uses OpenRC**, not systemd (`rc-service`, not `systemctl`). Three services: `dashboard-nagios`, `nagios-poller`, `nagios-proxy`
- **2 GB LXC:** keep process count and RSS minimal. No extra proxy farm, no Node toolchain, no Redis/Postgres
- **Never** live CGI / `docker stats` in Flask request handlers — read the SQLite snapshot
- **Never** spawn `proxy.py` per container — `async_proxy.py` only
- **Intensive Monitoring is HOLD** — do not restore or deploy that worker
- **Config directory is gitignored** — credentials and instance-specific data (includes `*.db`)
- **`IMPROVEMENT_PLAN.md`** — compact backlog only (not a session log dump)
- **Session passwords** are Fernet-encrypted — never log or expose them
- **Activity Logs UI** is **Audit → Activity Logs** only (not Global Settings)
- **Page CSS** load via `{% block extra_css %}` in `base.html` head + `?v=` after redesigns
- **UI-only prod deploy** never copies `config/`; always MD5 PRE/POST config + local==prod UI
- **Sound files** uploaded per-deployment via Monitoring Settings UI
- **Nagios Trends** come from log archives + status/retention timestamps. Demo injection: see `TRENDS_DUMMY_GUIDE.md` (always backup first). Alpine BusyBox sed is fragile — use Python inside containers.
- **Container paths:** archives `/opt/nagios/var/archives/`, status `/opt/nagios/var/status.dat`, retention `/opt/nagios/var/retention.dat`
- **Venv note:** broken shebang → `rm -rf venv && python3 -m venv venv && pip install -r requirements.txt`
- **Dev Waitress:** restart after major template class renames (stale Jinja)
