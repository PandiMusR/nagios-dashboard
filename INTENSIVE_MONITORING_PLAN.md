# Intensive Monitoring — HOLD Plan

**Status: ON HOLD as of 2026-08-21 (still HOLD after architecture Phases 1–3).** Do not deploy this feature to Production until the hold is explicitly lifted.

The feature must stay disabled in `app.py` and the sidebar. Do not start `intensive_worker.py` on Prod. Do not install the OpenRC unit. `deploy_from_dev.sh` strips Intensive files (`INTENSIVE_HOLD_EXCLUDE`). Do not restore them.

---

## Why this exists

Native high-frequency ping (10–30s) for priority hosts, with latency/loss history in SQLite, Chart.js UI, and Telegram alerts. Nagios is too heavy for this interval; Uptime Kuma was rejected as an extra app on the 2 GB Prod LXC.

Worker language: **Python asyncio**, standalone process (same pattern as `nagios-poller` / `async_proxy.py`). Not inside Waitress.

---

## What is built (Intensive feature Phases 1–3) — tested on Dev, not Production

### Phase 1 — Config + SQLite

| Item | Location |
|---|---|
| Host template JSON | `config/intensive_hosts.json` (gitignored) |
| SQLite helper | `services/intensive_db.py` |
| DB file | `config/ping_history.db` (WAL, gitignored) |
| Paths | `INTENSIVE_HOSTS_PATH`, `PING_HISTORY_DB_PATH` in `services/config.py` |

- Table `ping_results`: `ts`, `host_id`, `host_name`, `address`, `status`, `latency_ms`, `packet_loss_pct`, packet counts
- `insert_ping_result()`, `purge_old_records(retention_days)`
- Dev JSON uses dummy targets (`8.8.8.8`, `1.1.1.1`, `127.0.0.1`, `192.0.2.1`) and **`dev_mode` + `mock_alerts`: true**

### Phase 2 — Worker

| Item | Location |
|---|---|
| Worker | `intensive_worker.py` (project root) |

- Independent of Flask; does **not** import `services.config` (avoids `LDAP_ADMIN_PASSWORD` abort)
- `asyncio.create_subprocess_exec` + system `ping`
- Flavor detect: iputils (`-W`) vs BusyBox (`-w`)
- Parser covers both summaries (up / down / partial loss)
- Writes SQLite; 3× consecutive DOWN alert rule (in memory)
- CLI: `--ping ADDRESS`, `--once`, default loop
- Supervisor reloads `intensive_hosts.json` every 10s (add/remove without worker restart)

**Dev check:** `--ping` / `--once` populated SQLite correctly.

### Phase 3 — Flask + Chart.js

| Item | Location |
|---|---|
| Blueprint | `blueprints/intensive.py` |
| Page | `templates/intensive.html` |
| CSS / JS | `static/css/intensive.css`, `static/js/intensive.js` |

- `GET /intensive` — page (permission: `monitoring`)
- `GET /api/intensive/data?host=&range=1h\|24h\|7d` — Chart.js series + stats
- Empty DB: overlay “Belum ada data ping…”
- Downsample max 800 points; auto-refresh 20s
- Sidebar item was **Monitoring → Intensive Monitors** (removed while on HOLD)
- Old `/monitoring-intens` (Uptime Kuma) restored as the Intens link while this feature is held

**Dev check:** Flask restarted; chart rendered SQLite data.

---

## Phase 4 — code exists, NOT verified, do not deploy

The following was written on Dev after Phase 3 but was **not** production-tested. Treat as incomplete.

### 4a. Real Telegram alerts (`intensive_worker.py`)

**Done in code, untested against a real bot:**

- Reads `telegram_enabled`, `telegram_bot_token`, `telegram_chat_id` from `config/global_config.json` (token may be `__ENC__`)
- Fallback: `telegram` block in `intensive_hosts.json`
- If `mock_alerts` **or** `dev_mode` is true → log `[ALERT mock]` only, **never** call Telegram
- Sends after 3 consecutive DOWN; one recovery message; then re-arms

**Still to do:**

1. Keep Dev `mock_alerts: true` and `dev_mode: true` forever on this machine
2. On Prod only: `mock_alerts: false`, `dev_mode: false`, fill telegram fields in **Prod** `global_config.json` (never copy Dev JSON)
3. Manual test: force a dummy DOWN host on Dev with mock on; confirm no HTTP to `api.telegram.org`
4. Prod test with a test chat, then the real ops chat

### 4b. Manage Hosts UI

**Done in code, lightly unit-tested (add/delete JSON), UI not soak-tested:**

- Modal on `/intensive`: add name + IP/hostname + interval (10–300s), delete row
- `POST /api/intensive/hosts` and `DELETE /api/intensive/hosts/<id>` (CSRF via `csrfFetch`)
- Atomic JSON write in `services/intensive_db.py`

**Still to do:**

1. Click-test modal after HOLD is lifted (add, delete, chart dropdown updates)
2. Confirm running worker picks up new hosts within ~10s
3. Confirm delete does not wipe SQLite history (by design)

### 4c. OpenRC on Prod

**Template only:** `services/intensive-worker.initd`

Hardcoded Prod path `/svr/dashboard-nagios`. **Do not enable on Dev.**

**Still to do (Prod, after HOLD):**

```bash
sudo cp /svr/dashboard-nagios/services/intensive-worker.initd /etc/init.d/intensive-worker
sudo chmod +x /etc/init.d/intensive-worker
sudo rc-update add intensive-worker default
sudo rc-service intensive-worker start
```

Log: `/var/log/intensive-worker.log`

Do **not** run the worker on the 2 GB Prod LXC until RAM headroom is rechecked (existing OOM history). Prefer confirming RSS of one asyncio process (~30–50 MB) on Dev first.

### 4d. Deploy hygiene (when lifting HOLD)

`deploy_from_dev.sh` `FILES_TO_UPDATE` currently lists intensive UI/worker/initd. Those entries were removed during HOLD so a Prod deploy of the monitoring bugfix cannot copy the unfinished UI. Restore them when the feature is approved:

- `templates/intensive.html`
- `static/css/intensive.css`
- `static/js/intensive.js`
- `intensive_worker.py`

`blueprints/intensive.py` and `services/intensive_db.py` still live under `MODULE_DIRS` (`blueprints/`, `services/`). That is OK while `app.py` does not register the blueprint. After HOLD, re-enable registration and the sidebar link.

---

## How it is disabled (HOLD)

1. `app.py` — `intensive_bp` import/register commented out
2. `templates/base.html` — Intensive Monitors menu removed; Monitoring Intens points at `/monitoring-intens` again
3. `blueprints/monitoring_intens.py` — Kuma page restored (no redirect to `/intensive`)
4. Intensive paths removed from `FILES_TO_UPDATE` in `deploy_from_dev.sh`

Files stay on disk in the Dev repo. Do not delete them.

---

## Dev vs Prod (do not mix)

| | Dev | Prod |
|---|---|---|
| App | `/root/apps/nagiosDashboard` port 5000 | `/svr/dashboard-nagios` OpenRC |
| Intensive JSON / SQLite | local `config/` | local `config/` (never SCP) |
| Alerts | `mock_alerts: true` | only after explicit enable |
| Worker | manual `python3 intensive_worker.py` | OpenRC, later |
| Telegram | must not fire | Prod `global_config.json` only |

---

## Resume checklist

- [ ] Monitoring “ghost DOWN host” bug understood and fixed
- [ ] HOLD lifted by owner
- [ ] Re-register `intensive_bp` in `app.py`
- [ ] Restore sidebar item
- [ ] Restore `FILES_TO_UPDATE` entries
- [ ] Finish Phase 4 tests above
- [ ] Restart Waitress on Dev; do not deploy intensive to Prod until that list is done
