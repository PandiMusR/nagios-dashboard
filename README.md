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
  - [Stage History](#stage-history)
  - [API](#api)
- [Stage Tracking System](#stage-tracking-system)
- [Configuration Files](#configuration-files)
- [Permission System](#permission-system)
- [Security](#security)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

---

## Overview

This dashboard sits in front of multiple Nagios instances (each running in a Docker container) and provides:

- **Centralized login** via LDAP
- **Live monitoring views** across all Nagios servers by category
- **Host management** (add/edit/delete hosts) without touching config files manually
- **Stage tracking** for down hosts with optional notes per stage
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

```
Browser
  │
  ▼
Flask App (app.py) — port configurable via APP_PORT (default: 80)
  ├── Blueprints     → 12 modules (auth, dashboard, servers, users, monitoring, api, ...)
  ├── Services       → 11 modules (LDAP, encryption, stages, uptime kuma, nextcloud, active users, scheduler, docker cache, stage history, config)
  ├── Utils          → 3 modules (permissions, port check)
  ├── LDAP Auth      → OpenLDAP container (port 1389)
  ├── Docker CLI     → Nagios containers (nagios-ldap:latest)
  ├── Docker Cache   → In-memory cache for Docker CLI (TTL 15s)
  ├── Nagios API     → http://localhost:<port>/nagios/cgi-bin/...
  ├── Stage Tracker  → config/host_stages.json (with notes)
  ├── Stage History  → config/stage_history/ (persistent JSONL audit log)
  └── Uptime Kuma    → Socket.IO client

Per-container Proxy (proxy.py) — port 1000 + <nagios_port>
  └── Forwards requests to Nagios container with Basic Auth injection

Nagios Containers (Docker)
  └── /svr/<container_name>/etc/objects/localhost.cfg  ← host config
```

Each Nagios server is a Docker container built from the local `nagios-ldap:latest` image. The dashboard communicates with each container's Nagios CGI API over HTTP.

---

## Requirements

- **Python** 3.8+
- **Docker** (running, with access to `docker` CLI)
- **OpenLDAP** Docker container (`osixia/openldap`) — auto-created on first run

### Python Dependencies

```
Flask==3.0.0
ldap3==2.9.1
requests==2.31.0
waitress==2.1.2
python-socketio==5.9.0
python-engineio==4.7.1
websocket-client==1.6.2
cryptography>=41.0.0    # Fernet encryption for session + creds at rest
```

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

The application auto-detects its root directory via `APP_ROOT` in `services/config.py` — no hardcoded paths to change when relocating the project.

---

## Features

### Dashboard

The main overview page showing all your Nagios servers at a glance.

- **Per-server stats**: hosts up/down, services OK/warning/critical
- **CPU & memory usage** of each container
- **Live auto-refresh** with configurable interval

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
| Proxy | Each server gets a proxy on port `1000 + <nagios_port>` |

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

Live monitoring views, organized by category (e.g., Prioritas, BHome, OPD).

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

**Stage Notes:**
Every stage can have an optional note. Notes are displayed below the stage badge in the monitoring table. When opening the stage modal for a host with an existing note, it's pre-filled automatically.

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
- **Uptime Kuma** — URL, username, password, enable/disable
- **API Key** — generate/copy API key for external integrations
- **Activity Log** — view last 500 lines of the activity log (from all monthly files), or clear it
- **Backup & Restore** — full config backup as `.tar.gz`, upload/download/restore

---

### Uptime Kuma Integration

When adding a host in Host Manager, you can check **"Monitor in Uptime Kuma"** to automatically create a PING monitor for that host in your Uptime Kuma instance.

Setup in **Global Settings → Uptime Kuma**:
- URL (e.g., `http://localhost:3001`)
- Username and Password
- Enable the integration

The **Monitoring Intens** submenu shows all your Uptime Kuma monitors with:
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

### Stage History

Persistent audit log of all stage changes, stored in `config/stage_history/` as monthly JSONL files.

Access via **Monitoring → History** button or directly at `/stage-history`.

Features:
- Filter by Host, Container, Limit
- Newest entries first
- Shows: Timestamp, Host, Container, Stage Change (from → to), User, Note
- Entries are written for all stage changes: manual, batch, and auto-reset
- Data is append-only and never deleted

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
- **Notes**: Every stage can have an optional note. Notes are saved in `host_stages.json` only — they are NOT sent to Nagios (except for Resolved, where the note is used as the ACK comment)
- **Non-Resolved stages**: Only update the dashboard's `host_stages.json` — Nagios is NOT touched
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

Stages are stored in `config/host_stages.json`:

```json
{
  "Testung__Test-ack1": {
    "stage": "escalated",
    "updated_at": "2026-05-27T14:15:00",
    "updated_by": "admin",
    "note": "Waiting for field engineer",
    "host_up_since": null
  }
}
```

Key format: `{container_name}__{hostname}`

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
| `host_stages.json` | Current stage per DOWN host with notes (thread-safe locking) |
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
The LDAP admin password is read from the `LDAP_ADMIN_PASSWORD` environment variable. Falls back to `'admin'` if not set (backward compatible).

### API Key Authentication
External API access requires an API key passed via `X-API-Key` header or `?api_key=YOUR_KEY` query param. Keys are generated from **Global Settings → API Key** and stored in `global_config.json`.

### Thread Safety
Host stage tracking uses `threading.Lock()` with `host_stages_transaction()` context manager for atomic read-modify-write cycles. The `save_host_stages()` function also acquires the lock independently for standalone saves. Docker CLI results are cached in-memory with 15-second TTL to reduce overhead.

### Activity Log Audit
All `log_activity()` calls have been audited — no passwords, tokens, or credentials are logged.

---

## Project Structure

```
nagiosDashboard/
├── app.py                       # App factory + config + register blueprints (~70 lines)
├── proxy.py                     # Per-Nagios HTTP proxy server
├── start_proxy.sh               # Helper to launch proxy.py
├── start_proxy_daemon.py        # Daemonizes proxy.py
├── migrate_encrypt_creds.py     # Idempotent migration: encrypts plaintext creds JSON
├── deploy_from_dev.sh           # Production deployment script (SCP from dev server)
├── full_backup.sh               # Full backup script (app + config + Docker + LDAP)
├── add_ldap_user.py             # Utility: add user to LDAP manually
├── clean_mappings.py            # Utility: clean server mappings
├── requirements.txt
├── .gitignore
├── README.md
├── USER_GUIDE.md                # End-user guide (Bahasa Indonesia)
│
├── services/                    # Service modules
│   ├── config.py                # Centralized constants (APP_ROOT auto-detect, LDAP, paths, stages)
│   ├── encryption.py            # Fernet encrypt/decrypt (session + JSON at-rest)
│   ├── ldap_service.py          # LDAP connection, auth, log_activity, read_activity_logs
│   ├── stage_service.py         # Host stage tracking (load/save/transaction)
│   ├── stage_history.py         # Persistent stage change audit log (JSONL)
│   ├── uptime_kuma.py           # Socket.IO interactions with Uptime Kuma
│   ├── nextcloud.py             # WebDAV upload to Nextcloud
│   ├── active_users.py          # In-memory active session tracker
│   ├── scheduler.py             # Per-category CR Verification auto-reset scheduler
│   └── docker_cache.py          # In-memory Docker CLI cache (TTL 15s)
│
├── utils/                       # Utility modules
│   ├── permissions.py           # Permission check/load/save
│   └── port_check.py            # Port availability checking
│
├── blueprints/                  # Flask Blueprints (route modules)
│   ├── auth.py                  # Login, logout, setup, health, active-users, stage-history, activity-logs
│   ├── dashboard.py             # Dashboard + stats (parallel fetch)
│   ├── servers.py               # Server CRUD, proxy management, batch ops
│   ├── users.py                 # User CRUD, permissions
│   ├── monitoring.py            # Monitoring data, stages, batch set stage, export CSV
│   ├── host_manager.py          # Host CRUD, backup/restore
│   ├── monitoring_settings.py   # Category/server mapping, alarm settings, CR auto-reset config
│   ├── global_settings.py       # Config, backup, logs, API key management
│   ├── nagios_proxy.py          # Nagios CGI reverse proxy
│   ├── monitoring_intens.py     # Uptime Kuma monitors page
│   └── api.py                   # REST API endpoints (hosts, servers, monitoring, stage history)
│
├── config/                      # Runtime data (gitignored — not versioned)
│
├── create-nagios/               # Docker image build for Nagios containers
│   ├── Dockerfile
│   ├── build.sh
│   ├── nagios.conf
│   └── cgi.cfg
│
├── static/
│   └── assets/
│       └── img/                 # Application icons and images
│
└── templates/                   # Jinja2 HTML templates
    ├── base.html                # Layout: navbar, sidebar (with Audit menu), dark mode
    ├── login.html
    ├── setup.html               # First-time admin account creation
    ├── dashboard.html
    ├── servers.html
    ├── host_manager.html
    ├── monitoring.html          # Live monitoring + stage system + notes + export CSV
    ├── monitoring_intens.html   # Uptime Kuma monitors
    ├── monitoring_settings.html # Includes CR Auto-Reset per-category config
    ├── users.html
    ├── user_permissions.html    # Includes CR View Only toggle
    ├── global_settings.html     # Includes API Key management
    ├── active_users.html        # Active users page (admin only)
    ├── activity_logs.html       # User activity logs (standalone page)
    └── stage_history.html       # Stage change history with filters
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

Check that `config/host_stages.json` is writable by the app user:

```bash
ls -la config/host_stages.json
```

### Monitoring page shows no data

1. Verify the Nagios server is mapped to the category in **Monitoring Settings**
2. Check that the Nagios container is running: `docker ps`
3. Verify the proxy is running for that server in the **Servers** page

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
