# Nagios Dashboard — Developer reference

Hard runtime constraints live in `.cursorrules`. Feature overview and setup: `README.md`. Operator guide: `USER_GUIDE.md`.

This file is the single developer/architecture reference (former `AGENTS.md`, improvement backlog, and shipped Phases 1–3).

---

## Runtime architecture

Production is an Alpine Linux LXC (~2 GB RAM, no swap, OpenRC). Flask/Waitress is a **thin HTTP layer**. It must not fan out live Nagios CGI or `docker stats` on a browser request.

| OpenRC service | Process | Role |
|---|---|---|
| `dashboard-nagios` | `app.py` / Waitress (8 threads) | UI, LDAP, set-stage, Host Manager, ACK on resolve only |
| `nagios-poller` | `services/nagios_poller.py` | CGI poll ~30s → UPSERT `nagios_snapshot.db`; stage auto-detect; circuit breaker |
| `nagios-proxy` | `services/async_proxy.py` | One asyncio process; bind `0.0.0.0:(nagios_port+1000)` per container |

Iframe URL: `http://<host>:<proxy_port>/`. SIGTERM must wake the asyncio wait so OpenRC stop does not hang.

Poller credentials: `config/nagios_creds_<container>.json` (not the logged-in LDAP password).

`proxy.py` is unused leftover. Do not spawn per-container proxies. Extra processes, Redis, Postgres, and Node toolchains are out of scope.

**Intensive Monitoring is on HOLD.** `blueprints/intensive.py`, `intensive_worker.py`, and `intensive_db.py` are stripped on Prod (`INTENSIVE_HOLD_EXCLUDE` in `deploy_from_dev.sh`). Do not re-enable. Uptime Kuma (`monitoring_intens.py`) is a different page.

---

## Paths

| | Dev | Production |
|---|---|---|
| Host | `194.233.73.24` | `103.73.74.98` |
| SSH | port 21212 | `ssh -p 2326 rif@103.73.74.98` (or `root@` for deploy) |
| App | `/root/apps/nagiosDashboard` | `/svr/dashboard-nagios` |
| Git | `git@github.com:PandiMusR/nagios-dashboard.git` | no git — SCP via `deploy_from_dev.sh` |

`APP_ROOT` is derived from `services/config.py`. Docker volume base `/svr/<server>/` is hardcoded on purpose.

---

## Stack

Python 3.12, Flask 3, Waitress, ldap3, Flask-WTF, Fernet, `requests` (poller/ACK), aiohttp (multiplexer only), SQLite WAL, Jinja2 + Bootstrap + vanilla JS. No Node, no SPA build.

Settings stay in gitignored JSON. Stages and CGI snapshot are SQLite:

- `config/host_stages.db` — per-row UPSERT/DELETE (`stage_db.py`), plus `stage_comments`
- `config/nagios_snapshot.db` — poller snapshot + `container_health`

---

## Stage comments

Per-host comment thread in `stage_comments` (schema migration v2). Flask session user + server timestamp on Set Stage. Latest text is denormalized on `host_stages.note` for table/CSV.

- Opening Stage fetches `GET /monitoring/stage-info`
- Empty comment still changes stage (Resolved still requires text)
- `delete_stage` also deletes `stage_comments` (host recovered / resolved → clean slate next DOWN)
- Host rename: relocate comments **before** `delete_stage`
- CR auto-reset (`services/scheduler.py`) appends user `system (auto-reset)`, stage `new`, text `Auto-reset from CR Verification due to timeout`

After poller code changes: `rc-service nagios-poller restart`. After scheduler/UI: restart `dashboard-nagios`.

---

## Deploy

Run **on Prod**: `cd /svr/dashboard-nagios && ./deploy_from_dev.sh`

Never copy `config/` in a UI deploy. After poller changes, restart `nagios-poller` explicitly. After `async_proxy.py` / initd: `rc-service nagios-proxy restart`.

---

## Conventions

- No live CGI / `docker stats` in Flask request handlers — read the snapshot
- Stages: per-row ops only — never load-mutate-dump all hosts
- Incomplete CGI: store errors on `container_health`; never treat a failed fetch as all UP
- Do not commit unless asked; do not add code comments unless asked
- Page CSS via `{% block extra_css %}` in `base.html` head
- Activity Logs UI is **Audit → Activity Logs** only
- Session passwords are Fernet-encrypted — never log them

---

## Open backlog

| ID | Item | Notes |
|---|---|---|
| R2 | Pre-save Nagios `nagios -v` | Optional |
| A2 | Shared JSON/host-definition helpers | Low urgency |
| A3 | `/svr/<server>/` hardcoded | Intentional |
| U1–U5 | UI polish / a11y residuals | Optional |
| S1–S2 | Extra `send_file` sanitization; `/health` auth | Hold — internal tool |

Shipped (do not reopen): CSRF + perms + encryption; theme + settings UI; stages SQLite; CGI snapshot poller; single iframe multiplexer; dashboard without docker stats.

---

## History (git has the old plans)

- **2026-07:** Security Phases 1–4; settings UI redesign
- **2026-08:** Phase 1 stages JSON → SQLite; Phase 2 `nagios-poller`; Phase 3 multiplexer (replaced 14× `proxy.py`)
- **2026-09:** `stage_comments` thread; wipe on recovery; CR auto-reset comments

Former standalone files (`IMPROVEMENT_PLAN.md`, `MODERNIZATION_ROADMAP.md`, `TECH_STACK_AUDIT.md`, `INTENSIVE_MONITORING_PLAN.md`) were merged here and removed. Demo-only Nagios trends injection remains `TRENDS_DUMMY_GUIDE.md`.
