# AGENTS.md — AI Agent Context

This file provides comprehensive context for AI agents working on the Nagios Dashboard project. Read this file first before making any changes.

---

## Project Overview

**Nagios Dashboard** is a Flask-based web application that serves as a centralized management and monitoring dashboard for multiple Nagios server instances running in Docker containers. It uses LDAP for authentication and stores configuration in flat JSON files (no database).

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
| Language | Python | 3.8+ |
| Web Framework | Flask | 3.0.0 |
| WSGI Server | Waitress | 2.1.2 |
| Auth | LDAP (OpenLDAP via `ldap3`) | 2.9.1 |
| Container Runtime | Docker CLI | — |
| Encryption | Fernet (AES-128-CBC via `cryptography`) | ≥41.0.0 |
| HTTP Client | `requests` | 2.31.0 |
| Socket.IO | `python-socketio` | 5.9.0 |
| Frontend | Jinja2 + Bootstrap 5.3 + vanilla JS | — |
| Font | Inter (Google Fonts) | — |
| Icons | Font Awesome 6.4 | — |

---

## Directory Structure

```
nagiosDashboard/
├── app.py                    # App factory (72 lines). Registers blueprints, inits encryption, starts scheduler.
├── proxy.py                  # Per-Nagios HTTP reverse proxy. Run as separate process per container.
├── start_proxy_daemon.py     # Daemonizes proxy.py (subprocess with start_new_session=True)
├── start_proxy.sh            # Shell helper to launch proxy.py (alternative to daemon)
├── migrate_encrypt_creds.py  # Idempotent migration: encrypts plaintext creds JSON files
├── deploy_from_dev.sh        # Production deployment script (SCP from dev → prod)
├── full_backup.sh            # Full backup script (app + config + Docker + LDAP)
├── add_ldap_user.py          # Utility: manually add user to LDAP
├── clean_mappings.py         # Utility: clean server mappings
├── requirements.txt          # Python dependencies
├── .gitignore                # Excludes config/, venv/, logs, sound files, old templates
├── README.md                 # Main documentation (user-facing)
├── USER_GUIDE.md             # End-user guide in Bahasa Indonesia
│
├── services/                 # Backend service modules
│   ├── config.py             # ** CENTRAL CONFIG ** — APP_ROOT (auto-detect), LDAP, paths, stage definitions
│   ├── encryption.py         # Fernet encrypt/decrypt for session values and JSON at-rest
│   ├── ldap_service.py       # LDAP connection, auth, log_activity, read_activity_logs, check_ldap_server
│   ├── stage_service.py      # Host stage tracking: load/save/transaction with threading.Lock
│   ├── stage_history.py      # Persistent stage change audit log (monthly JSONL files)
│   ├── active_users.py       # In-memory active session tracker (5min idle timeout, background cleanup)
│   ├── scheduler.py          # Per-category CR Verification auto-reset (background thread, 30s loop)
│   ├── docker_cache.py       # In-memory Docker CLI cache (TTL 15s, thread-safe)
│   ├── uptime_kuma.py        # Socket.IO client for Uptime Kuma (add/remove monitors)
│   └── nextcloud.py          # WebDAV upload to Nextcloud share
│
├── utils/                    # Utility modules
│   ├── permissions.py        # Permission check/load/save, encrypted user password storage
│   └── port_check.py         # Port availability checking (Docker + netstat/ss)
│
├── blueprints/               # Flask Blueprints (route modules)
│   ├── auth.py               # /, /login, /logout, /setup, /health, /active-users, /stage-history, /activity-logs
│   ├── dashboard.py          # /dashboard, /dashboard/stats (parallel fetch with ThreadPoolExecutor)
│   ├── servers.py            # /servers CRUD, proxy management, plugin management, batch ops
│   ├── users.py              # /users CRUD, /user-permissions
│   ├── monitoring.py         # /monitoring/<page>, stage system, batch set stage, export CSV
│   ├── host_manager.py       # /host-manager CRUD, backup/restore, batch add
│   ├── monitoring_settings.py# /monitoring-settings — categories, server mappings, alarms, CR auto-reset config
│   ├── global_settings.py    # /global-settings — domain, Nextcloud, Uptime Kuma, API key, backup, logs
│   ├── nagios_proxy.py       # /nagios/*, /proxy/* — reverse proxy to Nagios containers
│   ├── monitoring_intens.py  # /monitoring-intens — Uptime Kuma monitors page
│   └── api.py                # REST API: /api/hosts/*, /api/servers, /api/monitoring, /api/stage-history (ONU auto-parse)
│
├── config/                   # Runtime data (GITIGNORED — not versioned)
│   ├── global_config.json    # Nextcloud, Uptime Kuma, domain, API key, CR last reset tracking
│   ├── monitoring_config.json# Refresh interval, alarm settings, CR auto-reset per category
│   ├── monitoring_categories.json       # List of monitoring category names
│   ├── monitoring_server_mappings.json  # Maps categories → Nagios containers
│   ├── user_permissions.json            # Per-user permission sets
│   ├── user_passwords.json              # Encrypted (__ENC__) — user LDAP passwords for htpasswd sync
│   ├── nagios_creds_<server>.json       # Encrypted (__ENC__) — per-server Nagios credentials
│   ├── host_stages.json                 # Current stage per DOWN host with notes (thread-safe)
│   ├── secret_key                       # Persistent Flask secret key (auto-generated on first run)
│   ├── activity_log.txt                 # Legacy activity log (pre-rotation)
│   ├── activity_logs/                   # Monthly activity logs (activity_log_YYYY_MM.txt)
│   ├── stage_history/                   # Monthly stage history (stage_history_YYYY_MM.jsonl)
│   └── backups/                         # Config backup archives (auto-cleanup: keep latest 3)
│
├── create-nagios/            # Docker image build for Nagios containers
│   ├── Dockerfile            # Based on manios/nagios:4.4.14 + Apache LDAP module
│   ├── build.sh              # Creates container with volume mounts at /svr/<name>/
│   ├── nagios.conf           # Apache config with LDAP auth (proxied gateway IP)
│   ├── cgi.cfg               # Nagios CGI config (all commands allowed for all users)
│   └── docker-compose.yml    # Alternative Docker Compose setup
│
├── static/
│   └── assets/
│       └── img/              # Application icon (icon.png)
│
└── templates/                # Jinja2 HTML templates
    ├── base.html             # Layout: navbar, sidebar (with Audit submenu), dark mode scaffolding
    ├── login.html            # Login page
    ├── setup.html            # First-time admin account creation
    ├── dashboard.html        # Main dashboard with server cards
    ├── servers.html          # Server management page
    ├── host_manager.html     # Host CRUD page
    ├── monitoring.html       # Live monitoring + stage system + notes + batch ops + export CSV
    ├── monitoring_intens.html# Uptime Kuma monitors page
    ├── monitoring_settings.html # Category/server mapping, alarms, CR auto-reset config
    ├── users.html            # User management page
    ├── user_permissions.html # Permission management with CR View Only toggle
    ├── global_settings.html  # Global config, backup, API key, activity logs
    ├── active_users.html     # Active users page (admin only, hidden)
    ├── activity_logs.html    # Standalone activity logs page (under Audit menu)
    ├── stage_history.html    # Stage change history with filters (under Audit menu)
    ├── edit_config.html      # Raw Nagios config editor
    └── nagios_view.html      # Embedded Nagios UI via proxy
```

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
- Non-resolved stages only update `host_stages.json` — Nagios is NOT touched
- Resolved sends ACK command to Nagios CGI and removes stage entry
- Flapping retention: Watchlist stage preserved for 30 minutes if host recovers
- CR Auto-Reset: background scheduler resets `cs` → `new` at configurable hours
- Stage history: every change recorded in `config/stage_history/` (JSONL, monthly files)
- Thread safety: `host_stages_transaction()` context manager with `threading.Lock`

### Monitoring Data Flow
1. Browser requests `/monitoring/<category>/data`
2. Server loads `monitoring_server_mappings.json` to find containers for category
3. Parallel fetch from all containers via `ThreadPoolExecutor` (max 10 workers)
4. Each container queried via Nagios CGI API: `statusjson.cgi?query=hostlist&details=true`
5. Stage reconciliation: auto-create "New" for new DOWN hosts, cleanup UP hosts
6. CR View Only filter applied if user has `cr_view_only` permission
7. JSON response with host list, stage info, and metadata

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
- `get_nagios_servers()` — duplicated in 7 blueprints (returns running Nagios container names)
- `get_monitoring_categories()` — duplicated in 7 blueprints (returns deduplicated category list from config files)
- `_get_nagios_servers()` / `_get_monitoring_categories()` — private versions in `auth.py`
- These are low-priority refactoring candidates (see IMPROVEMENT_PLAN.md section 6.2)

### Thread Safety
- `host_stages.json` protected by `threading.Lock` via `host_stages_transaction()` context manager
- `DockerCache` protected by `threading.Lock`
- `ActiveUsersTracker` protected by `threading.Lock` with background cleanup thread
- `scheduler.py` has `_config_lock` for `global_config.json` writes

### Error Handling
- All bare `except:` blocks replaced with specific exception types (47 total, fixed)
- JSON reads: `except (json.JSONDecodeError, OSError):`
- LDAP operations: `except Exception:`
- subprocess/Docker: `except (subprocess.CalledProcessError, OSError):`

---

## Recent Changes (as of 2026-07-03)

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

### Path Refactoring
- All hardcoded `/svr/dashboard-nagios` paths replaced with `APP_ROOT` auto-detection
- `services/config.py` auto-detects `APP_ROOT` from `__file__` location
- `proxy.py`, `start_proxy_daemon.py`, `migrate_encrypt_creds.py`, `clean_mappings.py` use `__file__`
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
4. Stop OpenRC service
5. Install Python dependencies
6. Run creds encryption migration (idempotent)
7. Restart proxy daemons for running Nagios containers
8. Verify app imports (auto-rollback on failure)
9. Start service (auto-rollback on failure)
10. Health check (`GET /health`)

### Files Deployed
**Individual files** (`FILES_TO_UPDATE`): `app.py`, `proxy.py`, `templates/base.html`, `templates/monitoring.html`, `templates/user_permissions.html`, `templates/active_users.html`, `templates/global_settings.html`, `templates/monitoring_settings.html`, `templates/stage_history.html`, `templates/activity_logs.html`, `requirements.txt`, `migrate_encrypt_creds.py`, `README.md`, `USER_GUIDE.md`

**Module directories** (`MODULE_DIRS`): `services/`, `utils/`, `blueprints/`

### Adding New Files to Deploy
If you create a new file that needs to be deployed:
- **Template:** Add to `FILES_TO_UPDATE` array in `deploy_from_dev.sh`
- **Python module:** If in `services/`, `utils/`, or `blueprints/`, it's auto-deployed via `MODULE_DIRS`
- **Standalone script:** Add to `FILES_TO_UPDATE` manually

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_PORT` | `80` | Flask app listen port |
| `LDAP_ADMIN_PASSWORD` | `admin` | LDAP admin bind password |

---

## Known Issues and Technical Debt

See `IMPROVEMENT_PLAN.md` for full details. Key items:

1. **Duplicated helpers:** `get_nagios_servers()` and `get_monitoring_categories()` copy-pasted across 7 blueprints
2. **No database:** File-based JSON storage — fragile under concurrent writes
3. **No CSRF protection:** Hold (local network only)
4. **Docker volume paths hardcoded:** `/svr/<server>/` — intentional, not planned to change
5. **LDAP injection:** `username` used unsanitized in DN — accepted risk for internal tool
6. **`monitoring_config.json`:** Contains hardcoded sound file paths — needs migration script if relocated

---

## Important Notes

- **Do NOT add comments** to code unless explicitly asked
- **Do NOT commit** unless explicitly asked
- **Production uses OpenRC**, not systemd (`rc-service`, not `systemctl`)
- **Config directory is gitignored** — contains credentials and instance-specific data
- **`IMPROVEMENT_PLAN.md`** is tracked in git — contains development roadmap and QA review results
- **Session passwords** are Fernet-encrypted — never log or expose them
- **All `log_activity()` calls** have been audited — no credentials logged
- **Dark mode** scaffolding exists in `base.html` but button is disabled (needs color refinement)
- **Sound files** are uploaded per-deployment via Monitoring Settings UI
- **Nagios Trends** are built from log archives (`/opt/nagios/var/archives/`), not config files. To fake historical data for demos, inject `CURRENT HOST STATE` entries into archive logs + update `last_state_change`/`last_hard_state_change` in `status.dat` and `retention.dat` via Python script inside container. Always backup before modifying.
- **Nagios container internals:** Archives at `/opt/nagios/var/archives/`, status at `/opt/nagios/var/status.dat`, retention at `/opt/nagios/var/retention.dat`. Alpine Linux containers use BusyBox sed — use Python for file modifications.
- **Venv note:** If venv pip has broken shebang (points to non-existent path), recreate with `rm -rf venv && python3 -m venv venv` then `pip install -r requirements.txt`
