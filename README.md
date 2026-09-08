# Nagios Dashboard

A web-based management dashboard for multi-server Nagios deployments. Built with Flask and LDAP authentication, it lets you manage multiple Nagios monitoring instances, their hosts, and user access — all from a single interface.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [First-Time Setup](#first-time-setup)
- [Running the App](#running-the-app)
- [Features](#features)
  - [Dashboard](#dashboard)
  - [Servers](#servers)
  - [Host Manager](#host-manager)
  - [Monitoring](#monitoring)
  - [Users & Permissions](#users--permissions)
  - [Monitoring Settings](#monitoring-settings)
  - [Global Settings](#global-settings)
  - [Uptime Kuma Integration](#uptime-kuma-integration)
  - [Active Users](#active-users)
  - [Audit](#audit)
  - [API](#api)
- [Stage Tracking System](#stage-tracking-system)
- [Configuration Files](#configuration-files)
- [Permission System](#permission-system)
- [Security](#security)
- [Project Structure](#project-structure)
- [Development](#development)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

---

## Overview

This dashboard sits in front of multiple Nagios instances (each running in a Docker container) and provides:

- **Centralized login** via LDAP
- **Monitoring views** across all Nagios servers by category (SQLite snapshot, ~30s poller)
- **Host management** (add/edit/delete hosts) without touching config files manually
- **Stage tracking** for down hosts with a per-host comment thread
- **Batch stage changes** for multiple hosts at once
- **CR View Only** permission for Customer Relation team access
- **User & permission management** with fine-grained access control
- **Backup & restore** of Nagios configurations
- **Uptime Kuma integration** for additional monitoring
- **Active users tracking** (admin only)
- **CR auto-reset scheduler** (per-category, configurable from dashboard)
- **Stage history** (persistent audit log of all stage changes)
- **Monthly activity log rotation** (kept forever)
- **REST API** for external integrations (add/delete hosts, query monitoring data)
- **Export CSV** from monitoring page (respects all active filters)

---

## Architecture

Production runs on an Alpine Linux LXC with a **~2 GB RAM** budget (no swap). Flask/Waitress must stay a thin HTTP layer: it **never** fans out live Nagios CGI or `docker stats` on a browser request.

```
Browser (Jinja2 + vanilla JS, 30s poll)
  │
  ▼
Flask / Waitress (8 threads) — APP_PORT (default 80)
  ├── /monitoring/<cat>/data  → SELECT nagios_snapshot.db  (milliseconds)
  ├── /dashboard/stats        → SELECT nagios_snapshot.db  (no docker stats)
  ├── set-stage / ACK         → SQLite host_stages.db + Nagios cmd.cgi on resolve only
  └── iframe /nagios/<name>   → http://<host>:<nagios_port + 1000>/

nagios-poller  (OpenRC)     nagios-proxy  (OpenRC)
  services/nagios_poller.py   services/async_proxy.py
  • CGI fetch ~every 30s      • ONE asyncio/aiohttp process
  • UPSERT snapshot SQLite    • binds 0.0.0.0:(port+1000) for every container
  • reconcile host stages     • injects Basic Auth from nagios_creds_*.json
  • record fetch errors       • ~40 MB RSS total (not 14× Waitress)

SQLite WAL
  config/nagios_snapshot.db   host + service snapshot + container_health
  config/host_stages.db       per-row stages / notes (not host_stages.json)

Nagios containers (Docker, nagios-ldap:latest)
  localhost:<nagios_port>/nagios/cgi-bin/...
```

| Process | OpenRC service | Role |
|---|---|---|
| Flask (`app.py`) | `dashboard-nagios` | UI, LDAP, set-stage, Host Manager writes |
| Background poller | `nagios-poller` | Live CGI → snapshot DB; stage auto-detect |
| Iframe multiplexer | `nagios-proxy` | Single reverse proxy with Basic Auth injection |

The legacy file `proxy.py` is unused. Do not spawn per-container proxy processes.

Each Nagios server is a Docker container. Host config lives at `/svr/<container_name>/etc/objects/localhost.cfg`.

---

## Requirements

- **Python** 3.12+
- **Docker** (running, with access to `docker` CLI)
- **OpenLDAP** Docker container (`osixia/openldap`) — auto-created on first run
- **Production:** Alpine Linux + OpenRC (not systemd), ~2 GB RAM LXC

### Python Dependencies

See `requirements.txt`. Notable packages: Flask 3, Waitress, ldap3, Flask-WTF, cryptography, requests, **aiohttp** (iframe multiplexer).

---

## Installation

```bash
# 1. Clone the repository
git clone <repository-url>
cd nagiosDashboard

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Build the Nagios Docker image (required before creating any server)
cd create-nagios
./build.sh
cd ..
```

---

## First-Time Setup

On first launch, if no users exist in LDAP, the app redirects to `/setup` automatically.

1. Open the app in your browser
2. You'll be redirected to the **Setup** page
3. Fill in your admin account details and submit
4. You'll be redirected to the login page — log in with the account you just created

> The first account created is always an **Admin** and is added to the `nagiosadmins` LDAP group automatically.

---

## Running the App

```bash
# Activate virtual environment
source venv/bin/activate

# Run in development mode
python app.py

# Or run in background (production-style)
nohup python app.py > app.log 2>&1 &
```

The app runs on `http://0.0.0.0:{APP_PORT}` by default. Port is configured in `services/config.py` via `APP_PORT` (default: 80). Can be overridden with environment variable: `APP_PORT=5000 python app.py`.

On **production** (Alpine OpenRC), three services must run:

```bash
rc-service dashboard-nagios status
rc-service nagios-poller status
rc-service nagios-proxy status
```

Without `nagios-poller`, monitoring/dashboard cards stay empty or stale. Without `nagios-proxy`, native Nagios iframes fail to connect.

The application auto-detects its root directory via `APP_ROOT` in `services/config.py` — no hardcoded paths to change when relocating the project.

---

## Features

### Dashboard

The main overview page showing all your Nagios servers at a glance.

- **Per-server stats** from the SQLite snapshot: hosts up/down/unreachable, services OK/warning/critical/unknown
- **Auto-refresh** (~30s) — Fast SELECT, not live CGI or `docker stats`
- Incomplete snapshot (poller fetch error) shows a warning banner on the card

---

### Servers

Manage the lifecycle of your Nagios Docker containers.

| Action | Description |
|---|---|
| Add Server | Creates a new Nagios container on a specified port |
| Start / Stop / Restart | Control individual or multiple containers |
| Delete | Removes container and associated config |
| Edit Config | Raw editor for the Nagios Apache config |
| Check Config | Validates Nagios config inside the container |
| Manage Plugins | Upload/delete check plugins per server |
| Proxy | One `async_proxy.py` multiplexer binds `1000 + <nagios_port>` per container |

> **Port rules**: Ports must be between 1000–65535. The proxy port is automatically set to `port + 1000`.

---

### Host Manager

Add, edit, and delete hosts from Nagios `localhost.cfg` files — without SSH or manual file editing.

**Adding a host:**
1. Select the target Nagios server
2. Fill in hostname, IP address, and parent host (if any)
3. Optionally add a service check
4. Optionally register the host in Uptime Kuma for ping monitoring
5. Submit — the host is added and Nagios reloads automatically

**Batch Add:**
Upload a list of hosts in one go. Hosts are parsed and added sequentially.

**Backup & Restore:**
Every `localhost.cfg` can be backed up with a timestamp. Backups can be restored or downloaded. Optionally synced to Nextcloud.

---

### Monitoring

Monitoring views, organized by category (e.g., Prioritas, BHome, OPD). Data is read from the poller snapshot (not a live CGI fan-out from the browser request).

Each category shows all hosts that are currently **DOWN** or **UNREACHABLE** from the mapped Nagios servers.

**Columns:**
- Server, Host, IP Address, Status, **Stage** (with notes), Duration, Last Check, Detail

**Filters:**
- **Server** — filter by Nagios server
- **Status Info** — filter by status detail (LOS, DyingGasp, PING, etc.)
- **Stage** — filter by stage (New, CR Verification, Escalated, Watchlist)
- **Detail** — free-text search across host name, IP, detail, stage note, container

**Auto-refresh:**
The page refreshes automatically on a configurable interval (set in Monitoring Settings). Audible alarm can be enabled for DOWN or UP events.

**Row Selection:**
Click anywhere on a table row to select/deselect the host checkbox. The Stage button click does not trigger row selection.

**View Only Mode:**
Click **View Only** in the top-right of the monitoring header to enter a clean fullscreen table — useful for display screens in NOC/operations rooms. The Stage column (with notes) is included here as well.

**Export CSV:**
Click **Export CSV** to download the currently filtered data as a CSV file. The export respects all active filters (Server, Status Info, Stage, Detail text search). What you see is what you get.

**Stage comments:**
Each host has a permanent thread for the current incident. Opening **Stage** loads comment history; a new note is appended (user + timestamp + stage). Comments are optional except for **Resolved**. When the host recovers (UP) or is resolved, the thread is deleted so the next DOWN starts clean. CR auto-reset appends a `system (auto-reset)` comment.

**Batch Set Stage:**
Select multiple hosts via checkboxes, then click **Batch Set Stage** to change their stage at once. An optional note can be applied to all selected hosts. For Resolved stage, ACK is sent to Nagios per host.

**Stage History:**
Click **History** in the monitoring header to view a persistent audit log of all stage changes. Filter by host, container, or limit. Newest entries appear first.

---

### Users & Permissions

#### User Management

- **Add users** to LDAP directly from the dashboard
- **Edit** display name and password
- **Delete** users (removes from LDAP and all permission records)

#### Permission Management

Each user has a permission set stored in `config/user_permissions.json`. Admins can grant or revoke access per user.

| Permission | Controls Access To |
|---|---|
| `dashboard` | Dashboard page |
| `monitoring` | Monitoring views |
| `servers` | Server management |
| `users` | User management |
| `host_manager` | Host manager |
| `monitoring_settings` | Monitoring category settings |
| `global_settings` | Global settings and logs |
| `user_permissions` | Permission management page |
| `cr_view_only` | Restrict monitoring to CR Verification stage only |
| `nagios_<server>` | Specific Nagios server in monitoring |
| `monitoring_<category>` | Specific monitoring category tab |

> **Admin role** bypasses all permission checks. A user is considered Admin if all main permissions are enabled OR if they are in the `nagiosadmins` LDAP group without custom permissions.

> **CR View Only** — when enabled, the user can only see hosts with "CR Verification" stage in the monitoring view. Designed for the Customer Relation team.

---

### Monitoring Settings

- **Refresh Interval** — auto-refresh interval for monitoring page (seconds)
- **Alarm Settings** — per-category: enable alarm on DOWN/UP, upload custom sound files
- **CR Auto-Reset** — per-category: configure reset hours, interval (days), and grace period (hours). Hosts in "CR Verification" are automatically reset to "New" at the configured schedule. Grace period protects recently-assigned hosts from being reset.
- **Category Management** — add/edit/delete monitoring categories, configure status information source
- **Server Mapping** — map Nagios servers to monitoring categories

---

### Global Settings

- **Domain settings** — base domain for proxy URLs
- **Nextcloud** — configure WebDAV share for backup uploads
- **Backup & Restore** — full config backup as `.tar.gz`, upload/download/restore
- **Uptime Kuma** — URL, username, password, enable/disable
- **API Key** — generate/copy API key for external integrations
- **Activity Logs** — not embedded here; use **Audit → Activity Logs** (`/activity-logs`). Global Settings only links out to that page.

---

### Uptime Kuma Integration

When adding a host in Host Manager, you can check **"Monitor in Uptime Kuma"** to automatically create a PING monitor for that host in your Uptime Kuma instance.

Setup in **Global Settings → Uptime Kuma**:
- URL (e.g., `http://localhost:3001`)
- Username and Password
- Enable the integration

The **Monitoring Intens** submenu (Uptime Kuma list — native Intensive ping is **HOLD**/disabled) shows monitors with:
- Real-time UP/DOWN status
- Heartbeat charts
- 24-hour uptime percentage
- Response time

---

### Active Users

Admin-only page at `/active-users` (hidden — no button, access via URL directly).

Shows currently active users with:
- Username, Role, IP Address
- Login time, Last active time, Idle time

Auto-refreshes every 30 seconds. Users idle > 5 minutes are automatically removed. Auto-refresh requests on the monitoring page count as activity, so users viewing the monitoring dashboard stay marked as active.

---

### Audit

The **Audit** menu in the sidebar provides two sub-pages for tracking system activity:

#### Stage History

Persistent audit log of all stage changes, stored in `config/stage_history/` as monthly JSONL files.

Access via **Audit → Stage History** in the sidebar or directly at `/stage-history`.

Features:
- Filter by Host, Container, Limit (auto-submit on change)
- Newest entries first
- Shows: Timestamp, Host, Container, Stage Change (from → to), User, Note
- Entries are written for all stage changes: manual, batch, and auto-reset
- Data is append-only and never deleted

#### Activity Logs

Standalone page for viewing user activity logs across the system.

Access via **Audit → Activity Logs** in the sidebar or directly at `/activity-logs`.

Features:
- Limit selector (100/250/500/1000 lines, auto-submit on change)
- Monospace log viewer with scrollbar
- Refresh and Clear Logs buttons (clear is admin only)
- Monthly log rotation — logs are split into `config/activity_logs/activity_log_YYYY_MM.txt`
- Logs are kept forever (no auto-cleanup)

---

### API

REST API for external integrations. Auth via `X-API-Key` header or `?api_key=YOUR_KEY` query param.

Generate API key in **Global Settings → API Key**.

| Endpoint | Method | Description |
|---|---|---|
| `/api/hosts/add` | POST | Add a host to a Nagios server |
| `/api/hosts/batch-add` | POST | Add multiple hosts at once |
| `/api/hosts/delete` | DELETE | Delete a host |
| `/api/hosts` | GET | List hosts on a server |
| `/api/servers` | GET | List all running servers |
| `/api/monitoring` | GET | Get monitoring data (DOWN hosts) |
| `/api/stage-history` | GET | Query stage change history |

**Example:**
```bash
# Add host
curl -X POST http://server/api/hosts/add \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"server":"BhomeTest","host_name":"switch-1","address":"192.168.1.100"}'

# Query stage history
curl -H "X-API-Key: YOUR_KEY" "http://server/api/stage-history?host=switch-1&limit=50"
```

---

## Stage Tracking System

When a host goes DOWN, it enters a **stage workflow** managed entirely by the dashboard (no changes to Nagios itself).

### Stages

| Stage | Description |
|---|---|
| 🔴 **New / Unacknowledged** | Alert just came in, no action taken yet |
| 🔵 **CR Verification** | Customer Relation team is checking the issue |
| 🟠 **Escalated / Pending** | Waiting on a third party (field engineer, ISP, etc.) |
| 🟣 **Watchlist / Flapping** | Host is unstable, being watched for recurring issues |
| ✅ **Resolved** | Issue resolved — triggers actual ACK to Nagios and removes from list |

### How It Works

- **Auto-assign**: When a host first goes DOWN, it's automatically set to **New**
- **Set Stage**: Click the **Stage** button on any row to open the stage selector. Click anywhere on the row to select/deselect for batch operations.
- **Notes**: Optional comment appended to the host thread in `host_stages.db` (`stage_comments`). Not sent to Nagios except Resolved (ACK comment). History is wiped when the host recovers or is resolved.
- **Non-Resolved stages**: Only update `host_stages.db` — Nagios is NOT touched
- **Resolved**: Sends an ACK command to Nagios (requires a note) and the host disappears from the monitoring list
- **Host recovers by itself**: The host disappears automatically (Nagios reports UP) — no ACK needed
- **Batch Set Stage**: Select multiple hosts and change their stage at once with an optional shared note
- **Stage History**: Every stage change (manual, batch, auto-reset) is recorded in `config/stage_history/` for audit

### CR Verification Auto-Reset

Per-category auto-reset: hosts with "CR Verification" stage are automatically reset to "New" at configured hours and intervals.

Configuration in **Monitoring Settings → CR Auto-Reset** (per category):
- **Reset Hours** — when to reset (24h format, e.g., `15` or `03,15`)
- **Interval** — how often (1 = daily, 4 = every 4 days, 0 = disabled)
- **Grace Period** — skip hosts set to CR Verification within X hours (prevents resetting recently-assigned hosts)

Changes take effect within 30 seconds (no restart needed).

### Flapping Retention (30 minutes)

If a host comes back UP but you had already set a stage (e.g., "Watchlist"), the stage is **preserved for 30 minutes**. If the host goes DOWN again within that window, it resumes from its previous stage instead of starting over as "New". After 30 minutes of staying UP, the stage entry is cleaned up automatically.

### Storage

Stages are stored in SQLite WAL at `config/host_stages.db` (one row per container + hostname). Writers use per-row UPSERT/DELETE — never rewrite the whole table. A one-off migrator (`migrate_stages_to_db.py`) imported legacy `host_stages.json` (renamed to `host_stages.json.migrated`).

---

## Configuration Files

All runtime config files live in `config/` (not versioned):

| File | Purpose |
|---|---|
| `global_config.json` | Nextcloud, Uptime Kuma, domain settings, API key, CR last reset tracking |
| `monitoring_config.json` | Refresh interval, alarm settings, CR auto-reset per category |
| `monitoring_categories.json` | List of monitoring category names |
| `monitoring_server_mappings.json` | Maps categories → Nagios containers |
| `user_permissions.json` | Per-user permission sets |
| `user_passwords.json` | **Encrypted** (`__ENC__` marker) — user LDAP passwords for htpasswd sync |
| `host_stages.db` | Current stage per DOWN host with notes (SQLite WAL, per-row ops) |
| `nagios_snapshot.db` | Poller CGI snapshot + `container_health` (SQLite WAL) |
| `nagios_creds_<server>.json` | **Encrypted** (`__ENC__` marker) — per-server Nagios credentials |
| `secret_key` | Persistent Flask secret key (auto-generated on first run) |
| `activity_log.txt` | Legacy activity log (pre-rotation, still readable) |
| `activity_logs/` | Monthly activity logs (`activity_log_YYYY_MM.txt`, kept forever) |
| `stage_history/` | Monthly stage history (`stage_history_YYYY_MM.jsonl`, kept forever) |
| `backups/` | Config backup archives (auto-cleanup: keep latest 3) |

---

## Permission System

### Role Detection

| Condition | Role |
|---|---|
| All main permissions enabled | Admin |
| Member of `nagiosadmins` LDAP group (no custom permissions) | Admin |
| Any other case | User |

### Default Permissions (new users)

```json
{
  "dashboard": true,
  "monitoring": true,
  "nagios": false,
  "servers": false,
  "users": false,
  "host_manager": false,
  "monitoring_settings": false,
  "global_settings": false,
  "user_permissions": false,
  "cr_view_only": false
}
```

---

## Security

### Session Password Encryption
User LDAP passwords are encrypted in the Flask session using Fernet (AES-128-CBC). The encryption key is derived from a persistent secret key stored at `config/secret_key`. If the secret key file is deleted, all existing sessions become invalid (users must re-login).

### Credentials at Rest
All credential files (`user_passwords.json`, `nagios_creds_*.json`) are encrypted with Fernet. Encrypted values are prefixed with `__ENC__` to distinguish from legacy plaintext. The migration script `migrate_encrypt_creds.py` handles encryption of existing plaintext files (idempotent, auto-backup before encrypting).

### LDAP Admin Password
The LDAP admin password is read from the `LDAP_ADMIN_PASSWORD` environment variable. The app exits with a clear error message if not set (see `services/config.py` → `_require_env()`).

### CSRF Protection
All form submissions and AJAX POST requests are protected with Flask-WTF CSRF tokens. Four blueprints are exempt: `api` (API key auth), `auth` (login/setup — no session), `monitoring` (AJAX stage management), `nagios_proxy` (reverse proxy). The CSRF token is injected via a `<meta>` tag in the page head for JavaScript access, and via hidden `<input>` fields inside forms. Token time limit is disabled (`WTF_CSRF_TIME_LIMIT = None`) for this internal dashboard.

### API Key Authentication
External API access requires an API key passed via `X-API-Key` header or `?api_key=YOUR_KEY` query param. Keys are generated from **Global Settings → API Key** and stored in `global_config.json`.

### Thread Safety
Host stages use SQLite WAL and per-row UPSERT/DELETE (`services/stage_db.py`). Docker CLI name/port lists are cached in-memory (TTL 15s). Flask request handlers must not call live Nagios CGI or `docker stats`.

### Activity Log Audit
All `log_activity()` calls have been audited — no passwords, tokens, or credentials are logged.

---

## Project Structure

```
nagiosDashboard/
├── app.py                       # App factory + register blueprints + CR scheduler
├── proxy.py                     # UNUSED leftover — do not spawn; multiplexer is async_proxy.py
├── start_proxy.sh / start_proxy_daemon.py  # Control nagios-proxy OpenRC / multiplexer
├── migrate_encrypt_creds.py     # Idempotent: encrypt plaintext creds JSON
├── migrate_stages_to_db.py      # One-off: host_stages.json → host_stages.db
├── deploy_from_dev.sh           # Production deployment (SCP from dev)
├── requirements.txt
├── .cursorrules                 # Persistent AI session directives
├── README.md / USER_GUIDE.md / DEVELOPMENT.md
│   └── AGENTS.md            # pointer → DEVELOPMENT.md (.cursorrules)
│
├── services/
│   ├── config.py                # APP_ROOT, LDAP, paths, stage codes
│   ├── nagios_poller.py         # OpenRC nagios-poller — CGI → snapshot SQLite
│   ├── nagios-poller.initd
│   ├── poller_db.py             # nagios_snapshot.db helpers
│   ├── async_proxy.py           # OpenRC nagios-proxy — ONE aiohttp multiplexer
│   ├── nagios-proxy.initd
│   ├── proxy_control.py         # start/stop/reload multiplexer
│   ├── stage_db.py / stage_service.py  # host_stages.db (WAL, per-row UPSERT)
│   ├── stage_history.py         # Monthly JSONL audit log
│   ├── scheduler.py             # CR Verification auto-reset
│   ├── docker_cache.py          # Docker name/port list cache (TTL 15s)
│   └── …                        # LDAP, encryption, shared_helpers, Uptime Kuma, Nextcloud
│
├── blueprints/
│   ├── dashboard.py             # /dashboard/stats ← SELECT snapshot (no docker stats)
│   ├── monitoring.py            # /monitoring/<cat>/data ← SELECT snapshot
│   ├── servers.py               # Container CRUD; reload multiplexer on port change
│   ├── nagios_proxy.py          # Flask iframe helper routes (not the multiplexer)
│   └── …                        # auth, users, host_manager, settings, api
│
├── config/                      # gitignored — JSON settings + SQLite DBs
└── templates/                   # Jinja2 + vanilla JS (no SPA build)
```

---

## Development

### Project Layout

- **Dev server:** `/root/apps/nagiosDashboard/` (VPS, SSH port 21212)
- **Prod server:** `/svr/dashboard-nagios/` (Alpine Linux, OpenRC)
- **Git:** `git@github.com:PandiMusR/nagios-dashboard.git` (branch: `main`)

### Making Changes

1. Edit files on the dev server
2. Test locally: `python app.py` (Dev default port 5000 via `APP_PORT`)
3. Commit, then deploy from Prod: `./deploy_from_dev.sh`

Developer architecture, backlog, and conventions: **`DEVELOPMENT.md`**. AI session rules: `.cursorrules`.

### Path Auto-Detection

The app auto-detects its root directory via `APP_ROOT` in `services/config.py`. No hardcoded paths need to change when relocating the project — `os.path.dirname(os.path.abspath(__file__))` handles it automatically.

---

## Deployment

### Production Deploy

```bash
# Run on production server
cd /svr/dashboard-nagios
./deploy_from_dev.sh
```

The deploy script:
1. Backs up current files + module directories
2. Pulls new files from dev server via SCP (SSH ControlMaster for single password prompt)
3. Cleans `__pycache__`
4. Stops OpenRC `dashboard-nagios`
5. Installs Python dependencies
6. Runs creds encryption migration (idempotent)
7. Restarts the **single** `nagios-proxy` multiplexer (`start_proxy_daemon.py restart` — not 14× `proxy.py`)
8. Verifies app imports (auto-rollback on failure)
8b. Migrates `host_stages.json` → SQLite if needed (`migrate_stages_to_db.py`)
9. Starts `dashboard-nagios` (auto-rollback on failure)
10. Health check (`GET /health`)

`nagios-poller` is a separate OpenRC service. After poller code changes, restart it explicitly:

```bash
rc-service nagios-poller restart
rc-service nagios-proxy status
```

### Rollback

Backup is created at `config/backups/deploy_backup_<timestamp>/` before each deploy. Auto-rollback triggers if:
- SCP fails for any file or module directory
- App module import verification fails
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

## Troubleshooting

### App won't start

```bash
# Make sure you're using the virtual environment
source venv/bin/activate
python app.py
```

### LDAP connection error

```bash
# Check if the LDAP container is running
docker ps | grep ldap-server

# Restart it if stopped
docker start ldap-server

# Test the connection manually
docker exec ldap-server ldapsearch -x \
  -H ldap://localhost:389 \
  -D "cn=admin,dc=bnet,dc=id" \
  -w admin \
  -b "dc=bnet,dc=id"
```

### User can't log in to Nagios directly

The dashboard syncs passwords to each Nagios container's `htpasswd.users` file. If sync is out of date:

```bash
# Manually add user to a container's htpasswd
docker exec <container_name> htpasswd -b \
  /opt/nagios/etc/htpasswd.users <username> <password>
```

### Host not appearing after add

```bash
# Check if Nagios config is valid inside the container
docker exec <container_name> /opt/nagios/bin/nagios -v \
  /opt/nagios/etc/nagios.cfg

# Check container logs
docker logs <container_name> --tail 50
```

### Stage not updating

Stages live in SQLite WAL (`config/host_stages.db`), not JSON. Check the file is writable and the poller is running:

```bash
ls -la config/host_stages.db
rc-service nagios-poller status
```

### Monitoring page or dashboard shows no / stale data

1. Confirm `nagios-poller` is started: `rc-service nagios-poller status`
2. Verify category → server mapping in **Monitoring Settings**
3. Check that the Nagios container is running: `docker ps`
4. Incomplete snapshot shows a warning on the dashboard card (poller CGI error), not a fake “all UP”

Flask does **not** fetch live CGI on `/monitoring/.../data` or `/dashboard/stats`. If the poller is down, the UI only shows the last snapshot.

### Native Nagios iframe fails to connect

1. Confirm `nagios-proxy` is started: `rc-service nagios-proxy status`
2. Ports are `nagios_port + 1000` bound on `0.0.0.0` (one process, many sockets)
3. Logs: `/tmp/nagios-proxy.log` or `/var/log/nagios-proxy.log`
4. Do not start `proxy.py` per container — that path is retired

### Active users not showing

Active users are tracked in-memory. If the service restarts, the tracker resets. Users are also removed after 5 minutes of inactivity. Auto-refresh on the monitoring page counts as activity.

### CR Auto-Reset not working

1. Check the configured hours in **Monitoring Settings → CR Auto-Reset** (per category)
2. Verify the app is running (scheduler starts with the app)
3. Check console logs for `[Auto-Reset]` messages
4. Verify grace period isn't skipping all hosts

### Stage history not showing entries

1. Check that `config/stage_history/` directory exists
2. Verify the JSONL files have content: `wc -l config/stage_history/*.jsonl`
3. Check console logs for `[StageHistory]` error messages
