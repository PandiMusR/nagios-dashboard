# Nagios Dashboard — Comprehensive Audit Report

## Executive Summary

**Health Score: 6.5/10**

Nagios Dashboard is a well-structured Flask monolith (~6,100 LOC) that manages multiple Nagios server containers via Docker CLI. The codebase shows clear evidence of iterative improvement — bare except blocks have been cleaned up, shared helpers consolidated, and encryption at rest is properly implemented. However, the project suffers from several critical security gaps that would be unacceptable in a public-facing deployment: hardcoded default LDAP admin password, plaintext storage of Nextcloud and Uptime Kuma credentials in global_config.json, no CSRF protection, and multiple command injection vectors via unsanitized user input passed to subprocess calls.

The application also has zero test coverage and no CI/CD pipeline. The most critical issue is that many POST endpoints (`/monitoring-settings/edit-category`, `/monitoring-settings/delete/<category>`, `/servers/batch-start`, `/servers/batch-restart`, `/servers/batch-delete`, `/monitoring-settings/map-server`, `/monitoring-settings/unmap-server`, `/monitoring-settings/update-config`) check only authentication (`'username' not in session`) but do NOT call `check_permission()`, meaning any authenticated user — including low-privilege accounts — can perform admin-level operations.

---

## Phase 1: Project Overview

### Tech Stack

| Layer | Technology | Version | Notes |
|---|---|---|---|
| Language | Python | 3.8+ | Uses `from __future__ import annotations` |
| Web Framework | Flask | 3.0.0 | Blueprint-based modular architecture |
| WSGI Server | Waitress | 2.1.2 | 8 threads; also used for proxy processes |
| Auth | LDAP (ldap3) | 2.9.1 | OpenLDAP via osixia/openldap Docker image |
| HTTP Client | requests | 2.31.0 | For Nagios CGI API calls |
| Container Runtime | Docker CLI | — | Via subprocess, no Docker SDK |
| Encryption | Fernet (cryptography) | >=41.0.0 | AES-128-CBC for session + at-rest |
| Socket.IO | python-socketio | 5.9.0 | Uptime Kuma integration |
| Frontend | Jinja2 + Bootstrap 5.3 + vanilla JS | — | No frontend framework |
| Data Storage | Flat JSON files | — | No database |

### Directory Structure

```
nagiosDashboard/
├── app.py                    # Entry point — app factory, blueprint registration, scheduler start
├── proxy.py                  # Per-container Nagios reverse proxy (separate process)
├── start_proxy_daemon.py     # Daemonizes proxy.py
├── requirements.txt
├── .gitignore
│
├── blueprints/               # 11 Flask blueprints
│   ├── auth.py               # /health, /, /login, /logout, /setup, /change-password, /active-users, /stage-history, /activity-logs
│   ├── dashboard.py          # /dashboard, /dashboard/stats (parallel fetch)
│   ├── servers.py            # /servers CRUD, proxy mgmt, plugin mgmt, batch ops (670 LOC — largest file)
│   ├── users.py              # /users CRUD, /user-permissions
│   ├── monitoring.py         # /monitoring/<page>, stage system, batch set stage, export CSV (600 LOC)
│   ├── host_manager.py       # /host-manager CRUD, backup/restore, batch add (665 LOC)
│   ├── monitoring_settings.py# /monitoring-settings — categories, mappings, alarms, CR auto-reset
│   ├── global_settings.py    # /global-settings — domain, Nextcloud, Uptime Kuma, API key, backup, logs
│   ├── nagios_proxy.py       # /nagios/*, /proxy/* — reverse proxy to containers
│   ├── monitoring_intens.py  # /monitoring-intens — Uptime Kuma monitors
│   └── api.py                # REST API: /api/hosts/*, /api/servers, /api/monitoring, /api/stage-history
│
├── services/                 # Backend service modules
│   ├── config.py             # APP_ROOT auto-detect, LDAP config, stage constants
│   ├── encryption.py         # Fernet encrypt/decrypt (session + at-rest)
│   ├── ldap_service.py       # LDAP connection, auth, activity logging
│   ├── stage_service.py      # Host stage tracking with threading.Lock
│   ├── stage_history.py      # Persistent stage change audit log (JSONL)
│   ├── active_users.py       # In-memory session tracker (5min idle timeout)
│   ├── scheduler.py          # Per-category CR Verification auto-reset (30s loop)
│   ├── docker_cache.py       # In-memory Docker CLI cache (TTL 15s)
│   ├── shared_helpers.py     # Centralized get_nagios_servers/get_monitoring_categories with TTL cache
│   ├── uptime_kuma.py        # Socket.IO client for Uptime Kuma
│   └── nextcloud.py          # WebDAV upload to Nextcloud share
│
├── utils/
│   ├── permissions.py        # Permission check/load/save, encrypted user password storage
│   └── port_check.py         # Port availability checking (Docker + netstat/ss)
│
├── config/                   # Runtime data (GITIGNORED)
│   ├── global_config.json    # Nextcloud, Uptime Kuma, domain, API key, CR reset tracking
│   ├── monitoring_config.json# Refresh interval, alarm settings, CR auto-reset
│   ├── monitoring_categories.json
│   ├── monitoring_server_mappings.json
│   ├── user_permissions.json
│   ├── user_passwords.json   # Encrypted (__ENC__)
│   ├── nagios_creds_*.json   # Encrypted (__ENC__)
│   ├── host_stages.json
│   ├── secret_key
│   ├── activity_logs/
│   ├── stage_history/
│   └── backups/
│
├── create-nagios/            # Docker image build for Nagios containers
│   ├── Dockerfile
│   ├── build.sh
│   ├── nagios.conf
│   ├── cgi.cfg
│   └── docker-compose.yml
│
├── templates/                # 18 Jinja2 templates
│   ├── base.html, login.html, setup.html, dashboard.html
│   ├── servers.html, host_manager.html, monitoring.html
│   ├── monitoring_intens.html, monitoring_settings.html
│   ├── users.html, user_permissions.html, global_settings.html
│   ├── active_users.html, activity_logs.html, stage_history.html
│   ├── edit_config.html, nagios_view.html
│   └── *_old.html (deprecated)
│
├── static/assets/
│   ├── img/icon.png
│   └── sound/                # Alarm sound files (gitignored)
│
├── deploy_from_dev.sh        # SCP deployment dev→prod
├── full_backup.sh
├── migrate_encrypt_creds.py
├── add_ldap_user.py
├── clean_mappings.py
├── README.md, USER_GUIDE.md, AGENTS.md, IMPROVEMENT_PLAN.md
└── TRENDS_DUMMY_GUIDE.md
```

### Architecture

**Pattern:** Modular monolith (Flask Blueprints + service layer)

```
┌──────────┐
│  Browser (Jinja2 + Bootstrap 5 + JS)     │
└──────────┬───────────┬───────────┘
           │ HTTP              │ AJAX/SSE
           ▼                   ▼
┌──────────┐
│  Flask App (Waitress :80)                │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ auth_bp  │dash_bp   │ mon_bp   │
│  │ users_bp │servers_bp│ │ host_bp  │
│  │ api_bp   │proxy_bp  │ settings │
│ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       │  Service Layer (services/)       │
│       │  encryption | ldap | stage      │
│       │  scheduler | docker_cache       │
│       └──────┬───────────┬──────────────┘
│              │           │
│   ┌──────────▼──┐ ┌────▼─────────────┐
│   │ LDAP Server  │  │ Docker CLI       │
│   │ (osixia/open │  │ docker ps/exec/  │
│   │  ldap :1389) │  │ restart/stop     │
│   └──────────────┘ └──────┬───────────┘
│                            │
│                   ┌────────▼──────────┐
│                   │ Nagios Containers  │
│                   │ (manios/nagios)    │
│                   │ CGI: statusjson    │
│                   └────────────┘
```

### Data Flow: Nagios → Dashboard UI

1. Browser requests `/monitoring/<category>/data`
2. `monitoring.py:_fetch_monitoring_hosts()` loads `monitoring_server_mappings.json` to find containers for category
3. Gets running containers via Docker CLI (cached 15s via `docker_cache`)
4. Parallel fetch from all containers via `ThreadPoolExecutor` (max 10 workers)
5. Each container queried via Nagios CGI API:
   - `statusjson.cgi?query=hostlist&details=true` — host status
   - `objectjson.cgi?details=true&query=hostlist` — IP mapping
   - `statusjson.cgi?query=servicelist&details=true` — service data (optional)
6. Stage reconciliation: auto-create "New" for new DOWN hosts, cleanup UP hosts (30min flapping retention)
7. CR View Only filter applied if user has `cr_view_only` permission
8. JSON response with host list, stage info, and metadata

**Integration method:** HTTP requests to Nagios CGI API (`statusjson.cgi`, `objectjson.cgi`, `cmd.cgi`) with Basic Auth headers derived from user's LDAP credentials (decrypted from session).

---

## Phase 2: Security Findings

| Severity | File:Line | Issue | Recommendation |
|---|---|---|---|
| CRITICAL | `services/config.py:19` | LDAP admin password hardcoded as `'admin'` default: `LDAP_ADMIN_PASSWORD = os.environ.get('LDAP_ADMIN_PASSWORD', 'admin')` | Require env var, refuse to start if not set. Also used in `ldap_service.py:37` and `create-nagios/nagios.conf:20,34`. |
| CRITICAL | `blueprints/servers.py:155-171` | `/servers/batch-start` checks auth but NOT `check_permission('servers')` — any authenticated user can start/stop/restart/delete any Nagios container | Add `check_permission('servers')` guard. |
| CRITICAL | `blueprints/servers.py:218-234` | `/servers/batch-restart` — same issue, no permission check | Add `check_permission('servers')`. |
| CRITICAL | `blueprints/servers.py:237-262` | `/servers/batch-delete` — same issue, no permission check. Deletes containers AND runs `rm -rf /svr/{server}` | Add `check_permission('servers')`. |
| CRITICAL | `blueprints/servers.py:400-414` | `/servers/delete/<name>` — no `check_permission('servers')` call, executes `rm -rf /svr/{name}` | Add permission check. |
| CRITICAL | `blueprints/servers.py:417-429` | `/servers/restart/<name>` — no permission check | Add permission check. |
| CRITICAL | `blueprints/servers.py:432-444` | `/servers/stop/<name>` — no permission check | Add permission check. |
| CRITICAL | `blueprints/servers.py:447-484` | `/servers/edit-config/<name>` — no permission check; writes arbitrary content to Nagios config file | Add permission check. |
| CRITICAL | `blueprints/servers.py:487-507` | `/servers/plugins/<name>` — no permission check | Add permission check. |
| CRITICAL | `blueprints/servers.py:510-536` | `/servers/plugins/upload` — no permission check; writes files to disk with `0o755` permissions | Add permission check. |
| CRITICAL | `blueprints/servers.py:539-554` | `/servers/plugins/<name>/<filename>` DELETE — no permission check | Add permission check. |
| CRITICAL | `blueprints/servers.py:557-569` | `/servers/start/<name>` — no permission check | Add permission check. |
| CRITICAL | `blueprints/servers.py:572-620` | `/proxy/start/<name>` — no permission check | Add permission check. |
| CRITICAL | `blueprints/servers.py:623-639` | `/proxy/stop/<name>` — no permission check | Add permission check. |
| CRITICAL | `blueprints/servers.py:642-670` | `/proxy/restart/<name>` — no permission check | Add permission check. |
| CRITICAL | `blueprints/monitoring_settings.py:47-76` | `/monitoring-settings/edit-category` — no permission check | Add `check_permission('monitoring_settings')`. |
| CRITICAL | `blueprints/monitoring_settings.py:140-159` | `/monitoring-settings/delete/<category>` — no permission check | Add permission check. |
| CRITICAL | `blueprints/monitoring_settings.py:162-195` | `/monitoring-settings/map-server` — no permission check | Add permission check. |
| CRITICAL | `blueprints/monitoring_settings.py:198-263` | `/monitoring-settings/update-config` — no permission check; handles sound file uploads | Add `check_permission('monitoring_settings')`. |
| CRITICAL | `blueprints/monitoring_settings.py:346-371` | `/monitoring-settings/unmap-server` — no permission check | Add `check_permission('monitoring_settings')`. |
| CRITICAL | `blueprints/host_manager.py:32-65` | `/host-manager/backup` — no `check_permission('host_manager')` | Add permission check. |
| CRITICAL | `blueprints/host_manager.py:68-91` | `/host-manager/backups/<server>` — no permission check | Add permission check. |
| CRITICAL | `blueprints/host_manager.py:94-117` | `/host-manager/restore` — no permission check | Add permission check. |
| CRITICAL | `blueprints/host_manager.py:120-134` | `/host-manager/delete-backup` — no permission check | Add permission check. |
| CRITICAL | `blueprints/host_manager.py:137-217` | `/host-manager/host-status/<server>` — no permission check | Add permission check. |
| CRITICAL | `blueprints/monitoring.py:385-427` | `/monitoring/acknowledge` — no `check_permission('monitoring')` | Add permission check. |
| CRITICAL | `blueprints/global_settings.py:347-354` | `/global-settings/logs` — no `check_permission('global_settings')`; any user can read all activity logs | Add permission check. |
| CRITICAL | `blueprints/global_settings.py:180-191` | `/global-settings/download-backup/<name>` — checks auth but permission check is only for `global_settings` not `global_settings` (actually present here, but backup contains all server configs) | Verify permission is sufficient; consider admin-only. |
| CRITICAL | `proxy.py:67` | Hardcoded fallback credentials: `{'username': 'nagiosadmin', 'password': 'nagiosadmin'}` — if creds file missing, proxy authenticates with default Nagios admin creds | Return 401 instead of falling back to default credentials. |
| CRITICAL | `blueprints/host_manager.py:165-166` | Same hardcoded fallback: `username = 'nagiosadmin'; password = 'nagiosadmin'` | Return error instead of default credentials. |
| HIGH | `blueprints/global_settings.py:262` | Nextcloud password stored in plaintext in `global_config.json` — not encrypted with `save_encrypted_json` | Use `save_encrypted_json` for entire global_config or at minimum password fields. |
| HIGH | `blueprints/global_settings.py:333` | Uptime Kuma password stored in plaintext in `global_config.json` | Same — encrypt at rest. |
| HIGH | `blueprints/monitoring_intens.py:79` | Uptime Kuma login uses `'username': 'admin'` hardcoded instead of configured username | Use `config['username']` instead of hardcoded `'admin'`. |
| HIGH | `blueprints/global_settings.py:161` | `tar.extractall('/tmp/restore_temp')` — path traversal vulnerability. A malicious backup file with `../../etc/passwd` entries could overwrite system files | Use `tar.extractall(filter='data')` (Python 3.12+) or validate member paths. |
| HIGH | `create-nagios/nagios.conf:20,34` | `AuthLDAPBindPassword "admin"` hardcoded in Apache config — visible in repo, deployed to every container | Use environment variable or Docker secret. |
| HIGH | Entire app | No CSRF protection on any POST forms. All state-changing operations (delete server, add host, change password, etc.) are vulnerable to CSRF | Add Flask-WTF CSRFProtect or implement per-session CSRF tokens. |
| HIGH | `blueprints/monitoring_settings.py:239-247` | Sound file upload: filename extension taken from user input without validation. Could upload `.php`, `.sh`, or other executable files | Whitelist allowed extensions (`.wav`, `.mp3`, `.ogg`). |
| MEDIUM | `blueprints/servers.py:526` | Plugin upload: `plugin_file.filename` used directly in `os.path.join()` — path traversal via filename could write to arbitrary location | Use `werkzeug.utils.secure_filename()`. |
| MEDIUM | `blueprints/servers.py:456-459` | Config editor writes arbitrary user content to Nagios config file without sanitization — could inject arbitrary Nagios directives | Validate config syntax before saving (already runs `nagios -v` but only AFTER write+restart). |
| MEDIUM | `services/ldap_service.py:173` | LDAP search filter built with string interpolation: `f'(member={user_dn})'` — `user_dn` contains username, potential LDAP injection if username contains special characters | Escape DN components using `ldap3.utils.conv.escape_filter_chars()`. |
| MEDIUM | `blueprints/servers.py:256` | `rm -rf f'/svr/{server}'` — `server` comes from user input. Although validated in `add_server`, batch-delete does not validate container name format | Validate `server` against running container list before deleting. |
| MEDIUM | `blueprints/monitoring.py:171` | `_stages_lock` held during `load_host_stages()` but stage mutations happen outside lock in `_fetch_monitoring_hosts()` — potential race condition between monitoring data fetch and set-stage | Use `host_stages_transaction()` for all stage reads+writes. |
| LOW | `requirements.txt:3` | `requests==2.31.0` has known CVE-2024-35195 (Session verify bypass) | Upgrade to `requests>=2.32.0`. |
| LOW | `requirements.txt` | No pinned version for `cryptography>=41.0.0` — could pull in incompatible version | Pin to exact version. |
| LOW | `.gitignore` | `config/*.json` excludes JSON files but `config/secret_key` is also excluded — confirmed safe. Config directory properly gitignored. | No action needed. |

---

## Phase 3: Code Quality Findings

| Category | File:Line | Issue | Recommendation |
|---|---|---|---|
| Dead Code | `blueprints/monitoring.py:22-82` | `get_nagios_servers()` and `get_monitoring_categories()` are local duplicate implementations despite `services/shared_helpers.py` existing with the same functions | Remove local copies, import from `shared_helpers` (the `monitoring()` route at line 93 already uses local versions; other routes in same file use shared_helpers). |
| Dead Code | `templates/*_old.html` (6 files) | Deprecated old templates tracked in git but excluded by `.gitignore` pattern `templates/*_old.html` — however they may still be in repo from before gitignore was added | Remove from repo with `git rm`. |
| Dead Code | `TRENDS_DUMMY_GUIDE.md` | Guide for faking historical Nagios data — not a production feature, should be in separate docs repo or removed | Remove or move to separate internal docs. |
| Code Smell | `blueprints/monitoring.py:140-303` | `_fetch_monitoring_hosts()` is 163 lines long with deeply nested conditionals (5+ levels). Cyclomatic complexity is very high — handles stage transitions, flapping retention, UP/DOWN logic, permission filtering all in one function. | Break into smaller functions: `_process_up_host()`, `_process_down_host()`, `_apply_stage_transitions()`. |
| Code Smell | `blueprints/servers.py` (670 LOC) | God file with server CRUD, batch operations, proxy management, plugin management, config editing, port checking. 22 route handlers in one file. | Split into `servers_crud.py`, `servers_proxy.py`, `servers_plugins.py`. |
| Code Smell | `blueprints/host_manager.py` (665 LOC) | Second god file — host CRUD, batch add, backup/restore, status. Has duplicated host definition building logic (lines 313-335 duplicate `api.py:66-104`). | Extract `_build_host_definition()` to shared utility. |
| Code Smell | `blueprints/host_manager.py:313-335` & `blueprints/api.py:66-104` | Host definition string building is duplicated — `host_manager.py` and `api.py` both build the same `define host{...}` + `define service{...}` string | Extract shared function in `services/` or `utils/`. |
| Code Smell | `blueprints/monitoring.py:22-82` & `services/shared_helpers.py:37-56` | `get_monitoring_categories()` implemented twice with different logic. The monitoring.py version reads 3 config files with detailed parsing; shared_helpers version reads 3 config files with simpler logic. They could return different results. | Consolidate to single implementation in shared_helpers. |
| Code Smell | `blueprints/global_settings.py:26-52` & `blueprints/monitoring_settings.py:26-42` | Identical config-loading boilerplate (load JSON, catch exceptions) repeated across 8+ locations | Extract `_load_json_file(path, default)` utility. |
| Code Smell | `blueprints/dashboard.py:22` | `print(f"DEBUG - Session: role={session.get('role')}, permissions={session.get('permissions')}")` — debug print left in production code, logs session data to stdout on every dashboard load | Remove or convert to proper logging with DEBUG level. |
| Error Handling | `blueprints/dashboard.py:154-155` | `except Exception: continue` in ThreadPoolExecutor future results — silently swallows all errors from container fetch. Failed containers produce no error feedback. | Log the exception, include failed container names in response. |
| Error Handling | `blueprints/dashboard.py:158-159` | Top-level catch returns `str(e)` to client — leaks internal error details | Return generic error message, log details server-side. |
| Error Handling | `blueprints/servers.py:167` | `batch_start_servers()` catches `Exception` but doesn't check `check_permission('servers')` — combined with the security issue (see above). Error message returns `str(e)` to client. | Return generic error, log details. |
| Error Handling | `services/ldap_service.py:72-73,77-78,82-83` | Three bare `except Exception: pass` blocks in `setup_ldap_structure()` — silently swallow LDAP errors when creating OUs and groups | Log errors, distinguish between "already exists" and actual failures. |
| Error Handling | `blueprints/auth.py:107-108,112-113,116-118` | Three bare `except Exception: pass` blocks in `setup()` route — same pattern | Same — log or handle specifically. |
| Consistency | `services/config.py:7` | `APP_PORT` defaults to `'5000'` but AGENTS.md says default is `80`. Dev uses 5000, prod uses 80. | Document discrepancy or align. |
| Consistency | Multiple files | Mix of f-string and `.format()` style. Some files use `f'{CONFIG_DIR}/...'` (e.g. `ldap_service.py:13`), others use `os.path.join()` (e.g. `encryption.py:12`). | Standardize on `os.path.join()` for path construction. |
| Consistency | `blueprints/servers.py:39` | `proxy_port = 1000 + int(port)` — magic number 1000 used for proxy port calculation. Same pattern repeated at lines 94, 185, 207, 330, 369, 582, 633, 652. | Extract constant `PROXY_PORT_OFFSET = 1000`. |
| Documentation | Project-wide | No API documentation. REST API in `blueprints/api.py` has good docstrings but no OpenAPI/Swagger spec. | Generate API docs with `flask-smorest` or hand-write API reference. |
| Documentation | `IMPROVEMENT_PLAN.md` | Referenced in AGENTS.md but not read during this audit. May contain outdated items. | Review and update during next sprint planning. |

---

## Phase 4: Architecture Review

### Scalability

- **Docker CLI bottleneck:** Every request that needs container info calls `subprocess.run(['docker', ...])`. DockerCache (15s TTL) mitigates this, but cache misses still spawn subprocesses. Under load with many concurrent users, this will be slow.
- **JSON file I/O:** `host_stages.json` is read+written on every monitoring data fetch. With many hosts, the file grows and the write-under-lock pattern becomes a contention point. The `threading.Lock` prevents corruption but serializes access.
- **No connection pooling:** Each Nagios CGI API call creates a new `requests.get()` — no session reuse. `proxy.py` uses `requests.Session()` but the main app does not.
- **Thread limit:** Waitress runs `threads=8`. If all 8 threads are blocked on Docker CLI calls (which can take up to 10s each), the app becomes unresponsive.
- **Will handle ~20 containers** with current architecture. Beyond that, Docker CLI subprocess overhead and JSON file I/O will cause noticeable latency.

### Maintainability

- **Good:** Blueprint-based modular architecture makes it easy to locate route handlers. Service layer is properly separated. `shared_helpers.py` consolidation is a positive step.
- **Good:** `AGENTS.md` is excellent — comprehensive, well-structured, serves as effective onboarding documentation for both AI agents and developers.
- **Bad:** Three god files (`servers.py` 670 LOC, `host_manager.py` 665 LOC, `monitoring.py` 600 LOC) are hard to maintain and test. Route handlers in these files average 30-50 lines each with significant duplication.
- **Bad:** Duplicated logic for host definition building, config loading, and container listing across multiple blueprints.
- **Bad:** Permission checks are inconsistently applied — some routes use `check_permission()`, some check `session.get('role') == 'admin'`, and many check only `'username' not in session`. This is the most dangerous maintainability issue because it's easy to add a new route without the correct permission check.

### Configuration Management

- **Good:** `services/config.py` centralizes all config paths and stage constants. `APP_ROOT` is auto-detected.
- **Good:** `config/` directory is properly gitignored. Runtime data (credentials, stages, logs) is separated from source code.
- **Bad:** No `.env.example` file. Environment variables (`APP_PORT`, `LDAP_ADMIN_PASSWORD`) are not documented outside of `services/config.py`.
- **Bad:** `global_config.json` mixes plaintext secrets (Nextcloud password, Uptime Kuma password) with non-sensitive config (domain, API key, CR reset tracking). Should be separated or all encrypted.
- **Bad:** `monitoring_config.json` contains hardcoded sound file paths — if the app is relocated, these paths break.

### Testing

- **Zero test coverage.** No `tests/` directory, no `conftest.py`, no test files anywhere in the project.
- No testing framework in `requirements.txt` (no `pytest`, `unittest` extensions, etc.).
- No CI/CD pipeline. No `.github/workflows/`, no `.gitlab-ci.yml`, no `Jenkinsfile`. Deployment is manual via `deploy_from_dev.sh`.
- No type checking. Although `from __future__ import annotations` is used (allowing type hints), there's no `mypy.ini`, `pyright` config, or `pyproject.toml` with type settings. Type hints exist but are never verified.
- No linting. No `.flake8`, `pylintrc`, `ruff.toml`, or `pyproject.toml` with linting config. Code style is inconsistent (import grouping, line length varies).

---

## Priority Action Items

Sorted by severity — fix top-down:

1. **[CRITICAL] Add `check_permission()` to all unprotected endpoints.** At minimum 25+ routes in `servers.py`, `host_manager.py`, and `monitoring_settings.py` check only authentication but not authorization. Any authenticated user can currently delete containers, overwrite configs, and manage hosts. This is the single highest-priority fix.

2. **[CRITICAL] Remove hardcoded LDAP admin password `'admin'`.** Change `services/config.py:19` to require `LDAP_ADMIN_PASSWORD` env var without a default. Update `create-nagios/nagios.conf` to use Docker secrets or env vars instead of `AuthLDAPBindPassword "admin"`.

3. **[CRITICAL] Remove hardcoded fallback credentials `nagiosadmin:nagiosadmin`.** In `proxy.py:67` and `blueprints/host_manager.py:165-166`. Return 401/error instead of falling back to default credentials.

4. **[HIGH] Encrypt Nextcloud and Uptime Kuma passwords at rest.** `blueprints/global_settings.py:262,333` currently store in plaintext in `global_config.json`. Use `save_encrypted_json` or encrypt just the password fields.

5. **[HIGH] Fix path traversal in `tar.extractall()`.** `blueprints/global_settings.py:161` — use `filter='data'` or validate member paths before extraction.

6. **[HIGH] Add CSRF protection.** Install Flask-WTF, enable `CSRFProtect` globally, add CSRF tokens to all forms.

7. **[HIGH] Fix hardcoded Uptime Kuma username `'admin'`.** `blueprints/monitoring_intens.py:79` — use `config['username']` instead.

8. **[HIGH] Validate file uploads.** Sound files (`monitoring_settings.py:239`) and plugins (`servers.py:526`) — whitelist extensions, use `secure_filename()`.

9. **[MEDIUM] Fix race condition in monitoring stage tracking.** `blueprints/monitoring.py:171` — use `host_stages_transaction()` for all stage reads+writes.

10. **[MEDIUM] Escape LDAP filter inputs.** `services/ldap_service.py:173` — use `ldap3.utils.conv.escape_filter_chars()`.

11. **[MEDIUM] Remove debug print statement.** `blueprints/dashboard.py:22` — logs session data to stdout on every request.

12. **[MEDIUM] Remove dead code.** Local duplicate `get_nagios_servers()`/`get_monitoring_categories()` in `monitoring.py:22-82`, old templates, `TRENDS_DUMMY_GUIDE.md`.

13. **[LOW] Add test coverage.** Start with `services/encryption.py`, `services/stage_service.py`, `utils/permissions.py`. Add integration tests for API endpoints in `blueprints/api.py`.

14. **[LOW] Extract duplicated host definition building logic.** Consolidate `blueprints/host_manager.py:313-335` and `blueprints/api.py:66-104` into a shared utility function.

15. **[LOW] Add `.env.example` file.** Document `APP_PORT` and `LDAP_ADMIN_PASSWORD` environment variables.
