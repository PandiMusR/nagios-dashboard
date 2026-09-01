# Nagios Dashboard — Architectural & Tech Stack Audit

**Date:** 2026-08-21  
**Status (2026-08-29):** Historical snapshot **before** Phases 1–3. Live CGI in Waitress, `host_stages.json`, and 14× `proxy.py` described below are **retired**. Current architecture: `README.md`, `AGENTS.md`, `.cursorrules`. Intensive Monitoring remains **on HOLD**.

**Scope:** Dev tree `/root/apps/nagiosDashboard` (Flask 3 + Waitress, Jinja2, vanilla JS) as of 2026-08-21.  
**Constraint:** Internal ops dashboard, two environments (Dev VPS vs Alpine LXC Prod, ~2 GB RAM, no git on Prod, SCP deploy).  
**Not in this audit:** code changes. Intensive Monitoring is **on HOLD** (`INTENSIVE_MONITORING_PLAN.md`); it is treated as a prototype, not a production subsystem.

---

## Executive snapshot

| Layer | Current | Industry fit for *this* product | Debt level |
|---|---|---|---|
| Frontend | Jinja2 layouts + per-page CSS + vanilla JS (`innerHTML`, polling) | Fine for an internal tool; **not** current SPA practice | High (structure), medium (UX) |
| Backend | Flask blueprints, mixed SSR + JSON | Normal Flask; APIs are inconsistent | Medium |
| State | Gitignored JSON files + in-process `threading.Lock` | Weak for concurrent writers | **High** |
| Nagios I/O | Blocking `requests` + `ThreadPoolExecutor` (max 10) | Works at ~14 containers; fragile under outage | High (reliability) |
| Auth | LDAP + Flask session + Fernet | Appropriate | Low–medium (CSRF exemptions) |
| Deploy | SCP + OpenRC, config never copied | Matches topology | Medium (script vs git) |

**Bottom line:** The stack is the right *size* for an internal Nagios front door. A Vue/React rewrite would not fix the two real risks (JSON races, CGI silent/slow fetches). A revamp should **harden the data and fetch layers first**, then **modernize the UI incrementally** without introducing a Node build on Prod.

---

## 1. Frontend architecture

### How it is structured today

**Layout**

- One shell: `templates/base.html` (navbar, sidebar, CSRF meta, dark-mode FOWT, Bootstrap 5.3 CDN, Font Awesome, Inter).
- ~18 page templates extending `base.html`.
- Newer settings pages (`monitoring_settings.html`, `global_settings.html`) use `{% block extra_css %}` in `<head>` and `ms-*` / `gs-*` class namespaces.
- Older pages still `<link>` CSS **inside** `{% block content %}` (body), which caused FOWT/stale-cache issues after class-namespace redesigns.

**CSS**

- Design tokens live in `static/css/base.css` (`:root` + `[data-theme="dark"]`).
- **One CSS file per page**, largely duplicated (`.section-card`, `.btn-primary`, `.modal`, `.form-group` copied across `stage_history.css`, `host_manager.css`, `users.css`, …).
- Residual hex / border-as-text on low-traffic pages (`edit_config`, `monitoring_intens`) — already on `IMPROVEMENT_PLAN.md` U1–U4.

**JavaScript**

- **No jQuery, Vue, React, Alpine, or HTMX.**
- Shared helpers in `static/js/app.js` (theme, sidebar, `csrfFetch`, password modal).
- Some pages have a paired file (`dashboard.js`, `servers.js`, `global_settings.js`).
- The most important page — **Monitoring** — still has **~750 lines of JS inlined in `templates/monitoring.html`**, plus a small new `static/js/monitoring.js` for fetch-error banners.
- **Host Manager** similarly inlines a large script in the template.
- Chart.js is used only on the held Intensive page (`cdn.jsdelivr.net`).

**Dynamic data / DOM**

| Pattern | Where |
|---|---|
| Jinja SSR (empty shell + server lists in sidebar) | Almost every page |
| `fetch` JSON → `innerHTML` string templates | Dashboard, Monitoring, Host Manager, Intens, backups |
| Classic form POST + redirect + flash | Settings, users, many mutations |
| `csrfFetch` JSON POST/DELETE | Servers, intensive hosts, some settings |
| Polling (`setInterval` ~20–30s) | Dashboard `/dashboard/stats`, Monitoring `/monitoring/<page>/data` |

Host names and plugin output are interpolated into HTML strings **without a consistent escape helper** (Monitoring toast/table, dashboard cards). That is XSS-adjacent if Nagios `plugin_output` or host names ever contain markup.

### Pain points

1. **Two frontend eras** in one app: “modern settings” vs “legacy monitoring/host_manager”.
2. **No component model.** A modal is copy-pasted CSS + markup + open/close JS on each page.
3. **State lives in closures and globals** (`allHosts`, `previousHosts`, `countdown`) — easy to get UP/DOWN alarm logic wrong (already happened conceptually when a failed CGI fetch looked like “all recovered”).
4. **Polling + full table rewrite** every 30s: loses nothing if coded carefully, but destroys focus, checkbox selection, and is O(n) DOM churn. Fine at tens of DOWN hosts; painful at hundreds during a mass outage.
5. **CSRF split brain:** `csrfFetch` exists, but `monitoring_bp` is **CSRF-exempt**, so stage-change POSTs skip the token path the rest of the app uses.
6. **No frontend test, bundler, or TypeScript.** Acceptable for this shop; it does mean refactors are manual and regressions are click-tested.
7. **CDN runtime dependency** (Bootstrap, FA, Google Fonts, Chart.js). Offline/air-gap Prod is not a design goal today, but a font/CDN outage degrades the UI.

This is **not** “wrong” for 2020 internal tools. It is **unscalable as a product UI** if you add more live widgets (charts, intensive ping, multi-category walls) without a state layer.

### Framework recommendation (for *this* dashboard)

| Option | Verdict |
|---|---|
| **Stay vanilla + discipline** | Viable if you extract JS, add a tiny `escapeHtml`, and one shared modal/button CSS. Lowest Prod risk. |
| **Alpine.js** | Good for settings forms, toggles, modals. Weak payoff for the 30s polling table (you would still `fetch` JSON). |
| **HTMX** | Excellent for “POST then swap a fragment” (users, mappings, host add). Awkward for a filtered, sorted, checkboxed table that polls. Mixing HTMX fragments + vanilla polling is two mental models. |
| **Vue 3 (islands, not a SPA)** | Best *framework* fit if you rewrite **Monitoring + Dashboard** as two Vue apps mounted on Jinja shells. Keep settings in Jinja. Needs a build step **or** Vue CDN (no SFC). |
| **React / Next / full SPA** | **Poor fit.** Auth is LDAP session cookies; Prod has no Node toolchain; 2 GB LXC; one/two developers; value is Nagios integration not a design system. Cost dominates benefit for 12–24 months. |

**Recommendation:** do **not** start the revamp with React. Prefer:

1. Short term: vanilla cleanup (extract Monitoring/Host Manager JS, `extra_css` everywhere, shared primitives).
2. Medium: **Vue 3 islands** only on the two polling pages *or* stay vanilla if the team is small.
3. Use HTMX/Alpine only if you want settings pages to stop being full-page POSTs — optional, not blocking.

Frequent polling does **not** require a full SPA. It requires: (a) a fetch that can fail loudly, (b) a render function that does not treat `[]` as “all UP”, (c) optionally a virtualized table if DOWN counts hit hundreds. You already started (a)+(b) in `monitoring.py` + `monitoring.js`.

---

## 2. Backend & API design (Flask)

### Blueprint map (12 modules, 11 registered)

| Blueprint | Role | HTTP style |
|---|---|---|
| `auth` | Login, setup, health, audit pages | SSR + JSON; **CSRF exempt** |
| `dashboard` | Home + `/dashboard/stats` | SSR shell + JSON poll |
| `monitoring` | Category views, stage, ACK, CSV | SSR shell + JSON poll + JSON POST; **CSRF exempt** |
| `servers` | Container CRUD, plugins, proxy | Mixed form/JSON |
| `host_manager` | `localhost.cfg` CRUD, backup | Mixed |
| `users` | LDAP users | SSR + JSON |
| `monitoring_settings` | Categories, mappings, alarms | Form POST |
| `global_settings` | Domain, Nextcloud, Kuma, API key | Form POST |
| `nagios_proxy` | Reverse proxy into containers | Pass-through; **CSRF exempt** |
| `monitoring_intens` | Uptime Kuma UI | JSON via Socket.IO client |
| `api` | External host add/delete | API key; **CSRF exempt** |
| `intensive` | Native ping UI (HOLD) | JSON + CSRF |

This is a **sensible feature split**, not over-fragmented. Pain is *inside* modules, not the number 11:

- `monitoring.py` still defines **local** `get_nagios_servers()` / `get_monitoring_categories()` instead of `services.shared_helpers` (other blueprints already migrated).
- `host_manager.py` is a large God-module (cfg parse + Docker + Nextcloud + Kuma).
- `api.py` duplicates host-definition building that Host Manager also does (`IMPROVEMENT_PLAN` A2).
- CSRF exemptions on `monitoring_bp` and `auth_bp` are convenience debt. Stage mutations should use the same `csrfFetch` as servers.

### SSR vs JSON (hybrid)

The app is a **classic hybrid**, not a JSON API with a SPA:

```
Browser loads Jinja page (session, sidebar, CSRF meta)
    → JS polls /monitoring/<cat>/data or /dashboard/stats
    → mutations via form POST *or* fetch JSON
```

That is a standard Flask pattern and is **not inherently bad**. The inconsistency is:

| Good | Friction |
|---|---|
| Settings pages are forms; easy to reason about | Two mutation styles on one page (Monitoring: JSON stage vs old ACK form) |
| Polling endpoints return JSON | Error shapes differ (`error` string vs `errors[]` vs flash) |
| External `api_bp` is key-auth | Browser JSON APIs share no versioning, no OpenAPI, no pagination |

There is **no** application-wide JSON envelope (`{ok, data, errors}`). Monitoring just gained `errors` / `incomplete`; dashboard stats still drop a whole server on CGI failure (`None`).

**Efficiency of 11 blueprints:** keep them. If you restructure, split *files* (e.g. `monitoring/fetch.py`, `monitoring/stages.py`) rather than inventing a new web framework. A single “API v1” blueprint for all XHR would help the frontend revamp more than merging blueprints.

---

## 3. Data layer & state management

### What lives in JSON (`config/`, gitignored)

| File | Role | Writers | Lock? |
|---|---|---|---|
| `host_stages.json` | DOWN-host workflow | Monitoring fetch, set-stage, scheduler, API | `threading.Lock` |
| `monitoring_server_mappings.json` | Category → containers | Settings UI | **No** |
| `monitoring_config.json` | Alarms, CR reset, permission mode | Settings + scheduler (`_config_lock` only on `cr_last_reset` in global) | Partial |
| `monitoring_categories.json` | Category list | Settings | **No** |
| `user_permissions.json` | ACL | Users/permissions UI | **No** |
| `global_config.json` | Telegram/Kuma/Nextcloud/API key | Global settings + scheduler | Partial |
| `user_passwords.json` | Encrypted LDAP copies | Users | Encrypted helpers |
| `nagios_creds_*.json` | Per-container CGI basic auth | Proxy / servers | Per-file, no app lock |
| `ping_history.db` | Intensive RTT/loss (HOLD) | Worker process | SQLite WAL |

Plus monthly **JSONL** append logs (`stage_history/`, `activity_logs/`) — those are the healthiest file pattern you have (append-only, no rewrite of the whole document).

### Concurrency with Waitress (8 threads)

Waitress is **threaded, one process**. `threading.Lock` **does** serialize writers *inside that process*. It does **not**:

- Protect against the **OpenRC + proxy daemons + intensive worker** as other processes.
- Protect **read-modify-write windows** that copy a dict, mutate it unlocked, then write.

Critical pattern in `blueprints/monitoring.py`:

1. `with _stages_lock: host_stages = load_host_stages()`  — lock released.
2. Parallel CGI (hundreds of ms to 15s) mutates the **in-memory copy**.
3. `save_host_stages(host_stages)` writes the whole file.

Two overlapping `/data` refreshes (two browsers, or refresh + CR scheduler) can **lose stage updates** (last writer wins). `save_host_stages` also takes the same non-reentrant `Lock`; calling it while still holding `_stages_lock` would deadlock — today the hold is released first, which avoids deadlock but **widens the race**. That matches backlog **R1**.

JSON files **without** any lock (`user_permissions.json`, mappings) can tear on concurrent admin clicks (corrupt JSON → empty `{}` on next `JSONDecodeError` swallow). Several loaders `pass` on decode errors and return `{}` / `[]`, which looks like “reset config” rather than “read failed”.

`indent=2` rewrite of a growing `host_stages.json` on every monitoring poll that dirties stages is extra I/O on a disk-constrained LXC.

### Should core state move to SQLite?

**Yes — for hot, contended, many-key state.** Not for everything.

| Move to SQLite (WAL) | Keep as JSON / env |
|---|---|
| `host_stages` (and maybe last-seen CGI snapshot) | `secret_key`, `.env` / OpenRC conf |
| `user_permissions` | Sound file paths (blobs on disk) |
| Category + server mappings | Encrypted creds *can* stay JSON **or** SQLite BLOB |
| Intensive ping history (already SQLite) | Monthly JSONL audit logs (or SQLite later) |

SQLite WAL is the same engine you already proved in `services/intensive_db.py`. It gives:

- Atomic updates per host (`UPDATE ... WHERE container=? AND host=?`) instead of rewrite-all.
- Readers (Waitress threads + future worker) without a giant lock.
- Backup = copy one file (still gitignore).

It does **not** require Postgres. A hosted DB would be operationally worse on this Alpine box.

**Do not** block a frontend revamp on a full SQLite migration, but **do not** add more JSON “databases” (new features should follow `ping_history.db`). Host stages are the first candidate because they are written on the polling path.

`load_host_stages()` returning `{}` on corrupt JSON is a footgun after a torn write — SQLite would fail the transaction instead of wiping workflow state.

---

## 4. Performance & Nagios integration

### Current CGI path

Monitoring (and dashboard) for each mapped container:

1. `docker ps` (cached 15s via `DockerCache`).
2. Parallel `requests.get` **statusjson** `hostlist&details=true`.
3. Sequential **objectjson** `hostlist` (IPs) — **both must succeed** or the container is a failure (after the 2026-08-21 fetch-error work).
4. Optional **servicelist** for plugin output.
5. Reconcile with `host_stages.json`.

`ThreadPoolExecutor(max_workers=min(n, 10))` is reasonable for ~14 Prod containers. `requests` is **sync**; each Waitress worker thread blocks until the pool finishes (worst case ~2× `CGI_TIMEOUT` per container if serial status+object, but containers run in parallel). Default `CGI_TIMEOUT` is now **15s** (`MONITORING_CGI_TIMEOUT`).

Dashboard `/dashboard/stats` still uses **timeout=5** and **drops the server** on exception — not yet aligned with monitoring’s `errors[]`.

### Scalability

| Load | Behavior |
|---|---|
| 14 containers, few DOWN, CGI healthy | Fine; poll 30s × 2–5 operators |
| Mass outage, CGI slow | Pool waits up to timeout; UI can now show incomplete (monitoring only) |
| Many browsers polling | 8 Waitress threads × 10 CGI workers; CPython I/O bound, usually OK; CPU on Nagios CGI is the bottleneck, not Flask |
| 50+ containers | `max_workers=10` queues; consider a **background poller** writing a snapshot, HTTP only reads snapshot |

**Missing vs best practice**

- No `requests.Session` / HTTP connection pool to `localhost` (backlog **R3**).
- No shared in-memory snapshot: every browser poll hits Nagios again.
- No circuit breaker (failed Adiarsa still retried every 30s at full timeout — can pile Waitress threads).
- Proxy layer: **14× `proxy.py` processes (~30 MB RSS each, ~428 MB on Prod)** for Basic Auth injection. That dominates RAM more than Flask. A revamp should consider **one multiplexed proxy** or session-aware fetch from Flask using stored creds (already in `nagios_creds_*.json`) and drop per-container proxies if Nagios UI iframe is the only consumer.

Fetching **full hostlist details** to display only DOWN hosts is wasteful. `statusjson` supports host status filters; using them would shrink payload during outages (when you need it most). Worth a spike; do not assume `result_limit=100` in `cgi.cfg` applies (that is HTML `status.cgi` pagination).

**Uptime Kuma** via Socket.IO from the Flask request path (`monitoring_intens.py`) is the wrong integration style (blocking wait + login on every page load). The HOLD native worker is the better pattern: background process, SQLite, HTTP read.

---

## Pros & cons of the current setup

### Pros

- Matches the team and topology: Python-only, Jinja, no Node on Alpine Prod.
- LDAP + session + Fernet + CSRF meta is enough for an internal tool.
- Feature-oriented blueprints are easy to find.
- Docker volume `/svr/<name>/` and OpenRC are honest about the deploy.
- Config gitignore + SCP deploy keeps secrets off GitHub.
- Tokens in `base.css` and settings-page redesign show the UI *can* be modernized in place.
- Intensive worker (HOLD) already demonstrates asyncio + SQLite WAL + BusyBox/iputils ping — a template for “don’t put more loops in Waitress”.
- Recent monitoring fetch errors (banner, no silent `[]`) are the correct reliability direction.

### Cons

- JSON documents as a database, with incomplete locking and “decode error → empty”.
- Hybrid UI without rules: inline vs files, form vs JSON, CSRF vs exempt.
- Polling pages rebuild entire DOM; XSS hygiene inconsistent.
- CGI fan-out is live on every poll; dashboard still fails silent.
- 14 proxy processes vs 2 GB LXC (`oom_kill` already observed on Prod).
- Duplicate helpers (`get_nagios_servers` in `monitoring.py`).
- CSRF-exempt monitoring mutations.
- No automated tests around stage reconcile / CGI failure.
- Prod deploy is a file list in bash; easy to ship the wrong surface (HOLD had to strip `FILES_TO_UPDATE` by hand).

---

## Recommended target architecture (revamp)

Think in **layers**, not a framework swap.

```
                    ┌─────────────────────────────┐
   Browser          │ Jinja shells + CSS tokens   │
                    │ Monitoring/Dashboard: JS or │
                    │ Vue island (polling client) │
                    └────────────┬────────────────┘
                                 │ JSON {data, errors, incomplete}
                    ┌────────────▼────────────────┐
   Flask/Waitress   │ Blueprints stay; thin HTTP  │
                    │ CSRF on all session POSTs   │
                    └────────────┬────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
     ┌────────────────┐  ┌──────────────┐  ┌─────────────────┐
     │ Snapshot store │  │ SQLite WAL   │  │ Nagios CGI      │
     │ (memory or     │  │ stages,      │  │ poller process  │
     │  sqlite)       │  │ perms, maps  │  │ (not Waitress)  │
     └────────────────┘  └──────────────┘  └─────────────────┘
              ▲                  ▲                  │
              └──────────────────┴──────────────────┘
                    OpenRC: dashboard + one poller
                    (+ optional one proxy, not 14)
```

### Phase A — UI foundation (no new framework)

- Move Monitoring and Host Manager JS out of templates; `extra_css` on all pages.
- Shared `components.css` (modal, button, card, alert). `escapeHtml` everywhere you `innerHTML`.
- One JSON error convention: `errors: string[]`, `incomplete: bool` on **dashboard stats too**.
- Re-enable CSRF on `monitoring_bp`; use `csrfFetch`.
- Keep Bootstrap or drop it later; don’t add another CSS framework yet.

### Phase B — State (highest reliability ROI)

- SQLite for `host_stages` and permissions/mappings (WAL, `busy_timeout`).
- Stop rewrite-all JSON on the 30s path.
- JSONL stays for audit.
- Intensive `ping_history.db` remains the pattern (when HOLD lifts).

### Phase C — Fetch / RAM

- Background **Nagios poller** (thread or small process, like `intensive_worker.py`): writes snapshot + errors per container. HTTP reads snapshot only.
- `requests.Session` to localhost; optional status filter for DOWN-only.
- Circuit-breaker / backoff per container.
- Revisit 14× `proxy.py` RSS; one proxy or Flask-side CGI with stored creds.
- Align dashboard timeout with monitoring (`MONITORING_CGI_TIMEOUT`).

### Phase D — Optional reactivity

- If polling UI is still painful after A–C: **Vue 3 island** on Monitoring + Dashboard only.
- Settings can stay Jinja or pick up HTMX for save-in-place.
- Skip React/Next unless you hire a frontend-heavy team.

### What not to do in the first revamp quarter

- Rewrite the whole app as an SPA.
- Introduce PostgreSQL/Redis for a single LXC.
- Deploy Intensive Monitoring until HOLD + RAM check.
- Copy Dev `config/` to Prod.

### Success metrics

- Mass outage: UI shows **incomplete + container names**, never a green empty table.
- Two operators changing stages during refresh: no lost `cs` / notes.
- Waitress RSS + proxy RSS fit in the 2 GB cgroup with headroom (Prod already has OOM history).
- A new settings field does not require copying 80 lines of CSS.

---

## Related docs

| Doc | Use |
|---|---|
| `AGENTS.md` | Runtime map, Dev/Prod, conventions |
| `IMPROVEMENT_PLAN.md` | Backlog A1/R1/R3/U4 (aligns with this audit) |
| `INTENSIVE_MONITORING_PLAN.md` | Held feature; do not mix into the revamp deploy |

---

*Audit only — no application code was modified to produce this file.*
