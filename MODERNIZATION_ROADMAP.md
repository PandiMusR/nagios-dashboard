# Nagios Dashboard — Modernization Roadmap

**Date:** 2026-08-21  
**Audience:** execution plan after `TECH_STACK_AUDIT.md`  
**Status:** planning only — no application code in this document  

This roadmap is ordered by **operational risk**, not by UI attractiveness. Phase 1 and Phase 2 exist because of the Gamas mass-outage: Waitress threads blocked on live CGI, failed fetches looked like “all UP”, and `host_stages.json` could lose writes under overlapping polls. Phase 3 is cleanup after the UI is reading a cheap, honest cache.

---

## Constraints (non-negotiable)

| Constraint | Implication |
|---|---|
| Prod Alpine LXC, **~2 GB RAM**, no swap, existing OOM history | One extra Python process is allowed; a Node toolchain, Redis, or Postgres is not |
| Waitress **8 threads**, one process | Do **not** put the CGI loop inside Flask. Browser requests must not fan out to 14 containers |
| **No Node.js** on Dev or Prod | No Vite/Webpack/React/Vue SFC build. CDN Alpine.js is optional; vanilla JS modules are the default |
| Prod has **no git**; deploy is SCP via `deploy_from_dev.sh` | Every new file must be listed (or live under `services/` / `blueprints/`). Never copy `config/` |
| Intensive Monitoring is **ON HOLD** | Do not start `intensive_worker.py` on Prod. The poller is a **new** worker. Reuse the *pattern*, not the Intensive feature |
| LDAP session CGI auth | Today `/monitoring/<cat>/data` Basic-Auths Nagios with the **logged-in user’s** password. A background poller **cannot** do that. It must use `config/nagios_creds_<container>.json` (already used by `proxy.py` / Host Manager) |

**RAM budget for Phase 2:** target **one** new process (`nagios-poller`) in the same weight class as a single `proxy.py` (~30 MB), not 14 of them. Do not enable Intensive + poller on Prod until RSS is measured.

---

## Proven pattern to copy

The Intensive stack (HOLD, Dev-only) already proved the shape we want:

| Piece | Intensive (HOLD) | This roadmap |
|---|---|---|
| Process | `intensive_worker.py` outside Waitress | `nagios_poller.py` outside Waitress |
| DB | `config/ping_history.db`, WAL, `busy_timeout` | `config/dashboard.db` (new), same pragmas |
| Flask | HTTP reads SQLite; no ping in the request | HTTP reads snapshot + stages; **no CGI in the request** |
| Supervisor | OpenRC `intensive-worker.initd` | OpenRC `nagios-poller.initd` |
| Config | JSON host list, reload without restart | Docker cache + mappings JSON/SQLite, reload each cycle |

Keep `ping_history.db` as time-series for Intensive later. **Do not** dump CGI snapshots into that file.

---

## Goal architecture (after Phase 2)

```
Browsers (30s poll)          Operators (set-stage)
        │                            │
        ▼                            ▼
┌───────────────────────────────────────────┐
│ Flask / Waitress (8 threads)              │
│  GET  /monitoring/<cat>/data  → SQLite    │
│  GET  /dashboard/stats        → SQLite    │
│  POST /set-stage              → SQLite    │
│  CR scheduler thread          → SQLite    │
└──────────────────┬────────────────────────┘
                   │ WAL reads/writes
                   ▼
         config/dashboard.db
                   ▲
                   │ WAL writes (snapshot + auto stage reconcile)
┌──────────────────┴────────────────────────┐
│ nagios_poller.py  (OpenRC, 1 process)     │
│  requests.Session → localhost CGI ports   │
│  nagios_creds_*.json (service account)    │
│  per-container timeout + circuit breaker  │
└───────────────────────────────────────────┘
                   │
                   ▼
         Nagios containers (~14)
```

**Gamas invariant (must hold in every phase):** a missing or failed CGI result is an **error**, never an empty host list. The UI must show `incomplete` + container names. Alarms must not fire “recovered” on fetch failure.

---

## Phase 0 — Guardrails (before writing migration code)

Do this on Dev in hours, not as a “project”.

1. **Baseline Gamas simulation** (already sketched): `MONITORING_CGI_TIMEOUT=0.001`, restart Waitress, confirm banner + no fake UP alarms. Record the JSON shape `{hosts, total_down, errors, incomplete}`.
2. **Inventory writers of `host_stages.json`:** `monitoring.py` (reconcile + set-stage + batch), `scheduler.py` (CR reset), `api.py` (delete host). All must go through `services/stage_service.py` after Phase 1 — no direct file I/O.
3. **Inventory CGI callers that Phase 2 must absorb or explicitly leave live:**
   - **Must move:** `blueprints/monitoring.py` category fetch, `blueprints/dashboard.py` `/dashboard/stats`
   - **May stay live (single container, operator-driven):** `host_manager.py` status peek, `nagios_proxy` iframe
4. **Confirm Prod `nagios_creds_*.json` exist** for every mapped container and decrypt with the Prod `secret_key`. Poller auth depends on this. If a container has no creds file, poller records `errors[]` for that name — same as “not running”.
5. **Do not Prod-deploy** the current CGI-timeout banner work until Dev confirms it. Phase 1–2 sit on top of that honesty contract.

**Exit:** a one-page checklist in the deploy notes: writers, CGI callers, creds present.

---

## Phase 1: State management — `host_stages.json` → SQLite WAL

**Why first:** overlapping Waitress polls load a dict, mutate it during 15s CGI, then rewrite the whole JSON. Last writer wins. CR auto-reset and a `/data` refresh can drop a `cs` / note. SQLite per-row `UPDATE` removes that class of bug **before** we add a second process that also writes stages.

**Out of scope for 1a:** permissions, mappings, `global_config.json`. Those are 1b after stages are proven. They write rarely; stages write on every poll.

### 1.1 Target schema (`config/dashboard.db`)

Reuse Intensive pragmas: `journal_mode=WAL`, `busy_timeout=5000`, `synchronous=NORMAL`, `check_same_thread=False`, `row_factory=sqlite3.Row`.

**Table `host_stages`** (one row per container+host):

| Column | Source today |
|---|---|
| `container` TEXT NOT NULL | key prefix before `__` |
| `hostname` TEXT NOT NULL | key suffix after `__` |
| `stage` TEXT NOT NULL | `new` / `cs` / `escalated` / `watchlist` |
| `updated_at` TEXT | ISO timestamp |
| `updated_by` TEXT | user or `system` |
| `note` TEXT | optional |
| `host_up_since` TEXT | flapping window; NULL if DOWN |
| PRIMARY KEY `(container, hostname)` | replaces `container__hostname` string key |

Index: `idx_host_stages_stage` on `stage` (CR reset, `cr_view_only` filter).

**Do not** move `stage_history/` JSONL in this phase. Append-only monthly files are already the right audit shape. Keep `append_stage_history()` as-is.

**Meta table `schema_migrations`:** integer version. First boot runs v1. Required so Dev/Prod do not guess.

### 1.2 Compatibility shim (seamless cutover)

Keep **`services/stage_service.py` as the only public API** for one full Dev cycle:

| Function | After 1.2 | After 1.3 |
|---|---|---|
| `get_stage_key()` | unchanged | unchanged |
| `load_host_stages()` | SELECT all → same `dict` shape callers expect | still available for debug / API dump |
| `save_host_stages(dict)` | rewrite-all via UPSERT + delete missing keys | **deprecated**; callers must stop |
| `host_stages_transaction()` | `BEGIN` … yield dict … `COMMIT` (still rewrite-all, but atomic) | replaced by row APIs |

**Callers that must not change in 1.2:** `scheduler.py`, `api.py`, set-stage / batch-set-stage in `monitoring.py`. If they still compile against the same functions, the UI workflow (`new` → `cs` → `escalated` / `watchlist` → `resolved` + Nagios ACK) is unchanged.

**New module:** `services/stage_db.py` (connect, schema, migrate). `stage_service.py` becomes a façade. Mirror `services/intensive_db.py` style so the team is not learning a second DB library.

### 1.3 One-shot JSON import (no dual-write forever)

On `init_db()`:

1. If `host_stages` table is **non-empty** → do nothing (already migrated).
2. If empty and `config/host_stages.json` exists and parses → INSERT rows. Parse key with `rsplit('__', 1)` (host names may contain `_` but the separator is `__`).
3. If JSON is missing or `JSONDecodeError` → start empty. **Do not** treat corrupt JSON as `{}` *and then* overwrite a good DB. Log loudly; leave DB empty; page `/health` should surface `host_stages: migrate_failed`.
4. After successful import: rename `host_stages.json` → `host_stages.json.migrated` (same directory, gitignored). Keep the file for one Prod backup cycle. **Stop writing JSON.**

**Rollback:** copy `.migrated` back to `host_stages.json`, drop or rename `dashboard.db`, revert the façade to file I/O, restart Waitress. Practice this on Dev once.

**Backup:** extend `full_backup.sh` / settings backup to include `dashboard.db` (and `-wal` / `-shm` if present). SQLite backup API (`VACUUM INTO` or `backup()`) is preferred over copying a live file while the poller runs — required before Phase 2.

### 1.4 Close the race (the actual fix)

JSON migration alone is not enough if `monitoring.py` still does:

```
load entire dict → CGI for 15s → save entire dict
```

After the façade works, change **reconcile** to row operations **inside the same request** (Phase 1.4) so two overlapping `/data` calls cannot clobber notes:

| Event | SQL |
|---|---|
| First DOWN | `INSERT OR IGNORE` then read row (preserve existing `cs` / note) |
| Recovered (not watchlist) | `DELETE` |
| Watchlist UP | `UPDATE host_up_since` if NULL |
| Watchlist expiry | `DELETE` if `host_up_since` older than 30 min |
| ACK in Nagios | `DELETE` (same as today) |
| Operator set-stage | `UPDATE` one row; Resolved → DELETE + CGI ACK |
| CR scheduler | `UPDATE stage='new' WHERE stage='cs' AND container IN (...)` |

`INSERT OR IGNORE` / `UPDATE ... WHERE container=? AND hostname=?` is how two Waitress threads coexist. Never “load all, mutate, dump all” on the polling path again.

**Flapping rule must stay bit-identical:** Watchlist + `host_up_since` + 30 minutes (`STAGE_RETAIN_MINUTES`). Write a Dev fixture: DOWN → watchlist → UP (keep row) → DOWN within 30 min (clear `host_up_since`, keep stage) → UP for 31 min (delete). Compare `stage_history` JSONL before/after.

### 1.5 `/health` and deploy

- Health check: `PRAGMA integrity_check` + row count, not “file exists”.
- `deploy_from_dev.sh`: `services/stage_db.py` ships via `MODULE_DIRS`. DB file is **created on Prod first start**, not copied from Dev.
- Waitress restart required. Poller does not exist yet.

### 1.6 Phase 1b (after 1a is on Prod and quiet)

Same DB, later tables, **not** blocking Phase 2:

- `user_permissions` (JSON blob per user **or** normalized flags). Writers: users UI only. Add a lock or SQLite so two admins cannot tear `user_permissions.json`.
- `monitoring_categories` + `monitoring_server_mappings` (small, currently unlocked).

Leave encrypted `nagios_creds_*.json` and `user_passwords.json` as files (Fernet + `__ENC__` already works). Leave `monitoring_config.json` / `global_config.json` as files until they grow contention (scheduler already locks `cr_last_reset` only).

### Phase 1 acceptance

- [ ] Dev: import existing `host_stages.json`; counts match; a known `cs` host with a note survives restart.
- [ ] Dev: two overlapping `curl` to `/monitoring/<cat>/data` cannot drop a note (force delay in reconcile if needed to prove it).
- [ ] Dev: set-stage, batch-set-stage, Resolved ACK, CR auto-reset, API host delete — all still work.
- [ ] Dev: corrupt JSON does not wipe a populated DB.
- [ ] Rollback drill documented and executed once.
- [ ] Prod: DB created locally; config PRE/POST still excludes copying `config/` from Dev.

**Do not start Phase 2 until 1.4 row APIs are in use.** A poller that still dump-writes a dict reintroduces the race across **processes** (Lock is in-process only).

---

## Phase 2: Background poller + snapshot (fix the CGI bottleneck)

**Why second:** after Gamas, every browser poll can occupy a Waitress thread for up to `CGI_TIMEOUT` × containers (statusjson + objectjson sequential per container, pool size 10). Empty/`[]` on timeout was treated as “no DOWN hosts”. Moving fetch off the request path makes `/data` a SQLite read (~milliseconds) and makes failure a **stored error**, not a dropped list.

**Depends on:** Phase 1.4 (stages in SQLite with row updates). Poller will call the same reconcile functions.

### 2.1 Process boundaries

| Process | Owns | Must not do |
|---|---|---|
| Waitress | HTTP, LDAP session, set-stage, ACK CGI **on resolve only**, CR scheduler | Live `statusjson` for monitoring/dashboard |
| `nagios_poller.py` | Periodic CGI, snapshot write, auto-detect stage reconcile (`up`↔`new`, watchlist timer) | Flask, LDAP bind, Telegram, Intensive ping |
| `proxy.py` × N | Nagios UI iframe Basic Auth | Unchanged in this phase (RAM follow-up, not Gamas) |

Poller **must not** `import services.config` if that import still `_require_env('LDAP_ADMIN_PASSWORD')` and aborts — Intensive worker already avoided this. Either lazy-load LDAP config or give the poller a thin path module (`APP_ROOT`, creds glob, mappings path).

**OpenRC:** `services/nagios-poller.initd` modeled on `intensive-worker.initd`:

- `command` = venv or `/usr/bin/python3` + `/svr/dashboard-nagios/nagios_poller.py`
- `directory` = app root, `pidfile` under `/run`, logs under `/var/log/nagios-poller.log`
- `depend() { need net; after docker; }` — CGI is useless if containers are down; still start (write `not running` errors)
- **Dev:** run in foreground / tmux. **Prod:** OpenRC only after Dev soak.
- Add to `FILES_TO_UPDATE` / document install (`cp` initd, `rc-update add`). Do not auto-start from Flask.

### 2.2 Auth model (blocking design choice)

Stop using the operator’s LDAP password for status fetches.

- Poller reads `nagios_creds_<container>.json` (decrypt `__ENC__` with Prod `secret_key`).
- `cgi.cfg` already allows commands for authenticated CGI users; statusjson is read-only.
- If creds missing/wrong: record fetch error for that container; **do not** skip snapshot update for others.
- Flask monitoring endpoints no longer need the session password for GET `/data`. Session remains for UI auth + Resolved ACK (ACK still uses the acting user or stored creds — pick **one** in implementation and document; stored creds is more reliable during Gamas when the operator’s bind is irrelevant).

### 2.3 Snapshot schema (same `dashboard.db`)

**`cgi_hosts`** — last **successful** picture per container+host (DOWN and UP that we care about). Recommendation: store **all hosts** or **DOWN + hosts that still have a stage row** (needed for recover/flap). Storing only DOWN makes “recovered” undetectable when the next fetch fails. Prefer:

- Full hostlist from `statusjson?query=hostlist&details=true` (filter in SQL for the UI).
- Optional later: CGI status filter if payload is huge — spike on Dev first; do not assume `result_limit=100` in `cgi.cfg` applies (that is HTML `status.cgi`).

Columns (minimum): `container`, `hostname`, `status_code`, `plugin_output`, `last_check_ms`, `last_state_change_ms`, `acknowledged`, `address`, `updated_at`. PK `(container, hostname)`.

**`cgi_fetch_state`** — one row per container:

| Column | Purpose |
|---|---|
| `container` PK | |
| `last_attempt_at` | always updated |
| `last_success_at` | unchanged on failure (**stale snapshot is valid**) |
| `last_error` | human string for UI banner |
| `consecutive_failures` | circuit breaker |
| `host_count` | sanity |
| `duration_ms` | observe CGI cost |

**Gamas rule:** on timeout/HTTP error, **UPDATE `cgi_fetch_state` only**. Do **not** `DELETE FROM cgi_hosts WHERE container=?`. UI joins stages to **stale hosts** + `errors[]` from fetch_state. `incomplete: true` if any mapped container `last_error` is set **or** `last_success_at` older than 2× poll interval.

### 2.4 Poll loop (copy Intensive, not Waitress)

Interval: reuse `monitoring_config.json` → `refresh_interval` (today ~20–30s). Reload mappings + docker ps each cycle (DockerCache TTL 15s is fine inside the poller).

Per cycle:

1. Resolve mapped containers + localhost ports (same `docker ps` format as now).
2. Mapped but not running → `last_error = not running` (already in monitoring.py).
3. Parallel fetch with **`requests.Session`** (audit R3), `max_workers ≤ 10`, timeout from `MONITORING_CGI_TIMEOUT` (default 15s).
4. **Circuit breaker:** if `consecutive_failures >= 3`, skip live CGI for that container for `min(60, 15 * failures)` seconds but keep serving stale snapshot + error. Prevents 8 Waitress-equivalent hangs from piling on a dead Adiarsa. (Poller has its own threads; still do this so one box cannot stall the whole cycle.)
5. On success: replace that container’s `cgi_hosts` in **one transaction** (`DELETE` container rows + `INSERT`, or `UPSERT` + delete vanished names).
6. **Reconcile stages** using Phase 1.4 row APIs — **once per cycle**, not per browser. Same rules as `_process_monitoring_data` today (UP cleanup, watchlist 30 min, ACK drop, first DOWN → `new` + JSONL history).
7. Objectjson IP map: cache per container until process restart or hash change; do not block statusjson on objectjson failure if addresses are already known (today **both** must succeed — tighten this so a hosts.cfg parse blip does not blank the category).

**Dashboard:** `/dashboard/stats` must read `cgi_hosts` + `cgi_fetch_state`, not a second live CGI with `timeout=5`. Align error behavior with monitoring (`errors[]`, not silent `None`).

### 2.5 Flask after the cut

`GET /monitoring/<page>/data`:

1. Auth + permission (unchanged).
2. Map category → containers (JSON or Phase 1b).
3. `SELECT` from `cgi_hosts` WHERE container IN (...) AND (DOWN **or** still in `host_stages`).
4. JOIN `host_stages` (LEFT JOIN; missing stage should not happen if poller reconcile is healthy — if it does, treat as `new` in the **response only**, and let the next poller cycle insert).
5. Attach `errors` from `cgi_fetch_state`.
6. `cr_view_only` filter in SQL or in Python (same as today).
7. **No** `ThreadPoolExecutor`, **no** `requests.get` on this path.

If the poller is down: `cgi_fetch_state` goes stale → `incomplete: true` + banner “poller snapshot older than Xs” (threshold = 2× interval). Better than a green empty table.

**Set-stage / ACK:** stay in Flask. Write SQLite immediately so the next UI poll (even before the next CGI cycle) shows `cs`. Do not wait for the poller.

### 2.6 RAM / CPU

- One poller process; thread pool only during fetch; idle otherwise.
- No Chrome, no Socket.IO, no Chart.js in the worker.
- Do not spawn per-container subprocesses.
- Measure RSS on Dev with 14 fake/slow endpoints before Prod.
- **Proxy farm (14× Waitress) is out of Phase 2.** Track as Phase 2-follow-up: multiplex or Flask-side iframe creds. Do not block Gamas fix on it.

### 2.7 Dev test plan (Gamas)

1. Healthy: UI matches live CGI (spot-check one category vs `statusjson` curl).
2. Kill one container / `iptables` drop its port: banner names it; **other** containers still list DOWN hosts; stages for the dead container **remain**.
3. `MONITORING_CGI_TIMEOUT=0.001` on the **poller** (not Flask): Flask `/data` stays fast; `incomplete` true; no UP toasts.
4. Stop poller: Flask still serves last snapshot + stale warning.
5. Restart poller: snapshot refreshes; no duplicate `up→new` history storms (reconcile must be idempotent).
6. Soak: 2 operators + 30s polling + CR scheduler for ≥1 hour on Dev; watch `dashboard.db` size and poller logs.

### Phase 2 acceptance

- [ ] `/monitoring/<cat>/data` p99 well under 1s on Dev with CGI timeouts simulated.
- [ ] Waitress thread dump during Gamas sim is not blocked in `requests.get`.
- [ ] Dashboard cards use the same snapshot + errors.
- [ ] OpenRC unit documented; Dev soak; Prod install is a **separate** explicit step.
- [ ] `deploy_from_dev.sh` includes `nagios_poller.py` + initd; DB still not copied.
- [ ] Intensive HOLD unchanged.

---

## Phase 3: Frontend cleanup & discipline (no SPA)

**Why last:** after Phase 2 the JSON payload is stable (`hosts`, `errors`, `incomplete`). Cleaning `innerHTML` and extracting scripts does not fight a moving backend. A Vue/React rewrite still does not fit Alpine 2 GB / no Node.

**Principle:** modular vanilla JS first; Alpine.js (CDN) only where it removes boilerplate (modals, toggles, settings forms). The monitoring table stays vanilla — Alpine does not buy much for a polled, filtered, checkboxed table.

### 3.1 Extract and split (Monitoring, then Host Manager)

Today: ~750 lines inline in `templates/monitoring.html` plus a small `static/js/monitoring.js` for the error banner.

Steps:

1. Move all monitoring script into `static/js/monitoring.js` (cache-bust `?v=YYYYMMDD` like settings CSS). Template keeps only `data-*` config (`refresh_interval`, `page`, `cr_view_only`).
2. Split by responsibility (still no bundler — multiple `<script src>` or one file with IIFE sections):
   - `poll.js` — fetch, countdown, **refuse `detectChanges` when `incomplete`**
   - `table.js` — filter/sort/render
   - `stages.js` — set-stage, batch, resolved ACK (`csrfFetch`)
   - `alarms.js` — sound + toasts
   - `escape.js` — **one** `escapeHtml` used for host name, plugin output, notes
3. Repeat for Host Manager inline script when Monitoring is done.

**CSRF:** re-enable CSRF on `monitoring_bp`; all stage POSTs go through `csrfFetch`. Do this in 3.1 while touching those fetch calls. `api_bp` / `nagios_proxy_bp` stay exempt.

### 3.2 Stop treating the table as a disposable string

Do **not** rewrite `tbody.innerHTML` from scratch every 30s if it can be avoided.

Pragmatic order:

1. **Preserve operator state across polls:** selected checkboxes, sort column, server filter, open modal, scroll position. Cheap win: keyed rows (`data-key="container__host"`), update text cells in place; insert/remove only changed keys. During Gamas (hundreds of DOWN rows) this also avoids losing a half-clicked ACK.
2. **Empty vs error:** keep the Phase-0 banner component; never show “No hosts with issues” when `incomplete` and `hosts.length === 0`.
3. **Shared alert/modal CSS** in `base.css` or `static/css/components.css` (backlog U4). Settings pages already have `ms-*` / `gs-*`; monitoring should consume the same tokens, not more hex.

`extra_css` in `<head>` for every page that still links CSS in `{% block content %}`.

### 3.3 Lightweight reactivity — where it is allowed

| Area | Tool | Reason |
|---|---|---|
| Monitoring table + alarms | Modular vanilla | Polling + selection + audio; you already own the logic |
| Dashboard cards | Vanilla (same poll helper as monitoring) | Same snapshot API |
| Settings toggles, mapping chips, password modal | **Alpine.js 3 CDN** *optional* | Declarative `x-show` / `x-model` beats 40 lines of classList |
| Users / Host Manager forms | Stay Jinja POST **or** Alpine for client validation only | No HTMX unless you enjoy two request models |

**Alpine rules if introduced:**

- Load from CDN in `base.html` **only on pages that need it** (`{% block extra_js %}`), not globally, to keep login cheap.
- No Alpine build step, no npm.
- Do not wrap the monitoring `<table>` in Alpine `x-for` in the first pass — migrating 750 lines into Alpine `x-for` is a hidden rewrite. Vanilla keyed DOM is enough.
- HTMX is **not** recommended for the polling pages (fragments + JSON poll = two sources of truth). Optional later for “save mapping, swap chip list”.

### 3.4 Dashboard alignment

`static/js/dashboard.js` should consume `{ errors, incomplete }` the same way as monitoring. Card refresh must not look “all green” when stats are stale.

### 3.5 What Phase 3 explicitly will not do

- No React, Vue SPA, Next, TypeScript, npm, or bundler.
- No WebSocket live push (poller interval is enough; Socket.IO already hurt Intens/Kuma).
- No Intensive UI work until HOLD is lifted.
- No visual redesign of settings (already done 2026-07-21) except token reuse.

### Phase 3 acceptance

- [ ] `templates/monitoring.html` has no business JS (markup + `data-*` only).
- [ ] XSS: plugin_output / host names escaped.
- [ ] Checkbox + filter survive a poll.
- [ ] CSRF token required on set-stage (Dev: request without token → 400).
- [ ] No Node in CI or Prod.
- [ ] Waitress restart after template/JS class moves (stale Jinja/CDN cache).

---

## Sequencing, staffing, and deploy gates

```
Phase 0  guardrails          Dev, hours
Phase 1a SQLite façade       Dev → Prod  (JSON gone, dict API)
Phase 1.4 row APIs           Dev → Prod  (race actually gone)
Phase 2  poller + snapshot   Dev soak → explicit Prod OpenRC
Phase 1b perms/mappings      anytime after 1a, not on Gamas critical path
Phase 3  frontend            overlapping late Phase 2 on Dev
```

**Never skip 1.4 before 2.** A poller + JSON dump is worse than today (two processes, no `threading.Lock`).

**Prod gates**

| Ship | Required proof |
|---|---|
| Phase 1 | Rollback drill; note-preserving soak; health check |
| Phase 2 | Gamas sim (timeout + one dead container); RSS; poller crash still serves stale + banner |
| Phase 3 | UI-only deploy rules (MD5, never `config/`) still apply |

**Docs to update when a phase ships:** `AGENTS.md` (storage + poller), `README.md` (host_stages path), `deploy_from_dev.sh` file lists, `IMPROVEMENT_PLAN.md` (R1/R3/A1). Do not treat this roadmap as a session log — tick acceptance checkboxes here or shorten IMPROVEMENT_PLAN when done.

---

## Risks and decisions already made

| Topic | Decision |
|---|---|
| Database | SQLite WAL in `config/dashboard.db`. Not Postgres, not Redis |
| Intensive DB | Separate `ping_history.db`. HOLD remains |
| Framework | No SPA. Alpine CDN optional in Phase 3 |
| CGI auth for reads | Service creds files, not user session |
| Reconcile owner after Phase 2 | Poller (auto-detect). Flask (operator + CR scheduler) |
| Failed CGI | Stale snapshot + error. Never empty-as-UP |
| 14× proxy.py RAM | Follow-up, not Phase 2 blocker |
| Dual-write JSON+SQLite | Import once, then JSON `.migrated`. No long dual-write |

---

## Related documents

| Doc | Role |
|---|---|
| `TECH_STACK_AUDIT.md` | Why this order |
| `INTENSIVE_MONITORING_PLAN.md` | Worker/SQLite/OpenRC pattern; **HOLD** |
| `IMPROVEMENT_PLAN.md` | Backlog R1, R3, A1, U4 |
| `AGENTS.md` | Paths, Prod SSH, deploy |

---

*Roadmap only — no application code was modified to produce this file.*
