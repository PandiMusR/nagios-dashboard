# Nagios Dashboard — Audit Triage & Shortlist

> Derived from `AUDIT_REPORT.md`. Every finding is triaged by Priority, Effort, Impact, and Category.
>
> **Priority:** P0 = Critical (security breach / data loss / crash) · P1 = High (broken functionality / major perf) · P2 = Medium (maintainability risk) · P3 = Low (cosmetic / nice-to-have)
>
> **Effort:** S = ≤30 min · M = 1–4 hours · L = ½–2 days · XL = 2+ days
>
> **Category:** Security · Bug · Refactor · Performance · Architecture · Tech Debt

---

## Full Triage Table

| # | Priority | Category | Finding (file:line) | Effort | Impact | Bucket |
|---|---|---|---|---|---|---|
| 1 | P0 | Security | 25+ routes check auth only, no `check_permission()` — any user can delete containers, overwrite configs, manage hosts (`servers.py:155,218,237,400,417,432,447,487,510,539,557,572,623,642`; `monitoring_settings.py:47,140,162,198,346`; `host_manager.py:32,68,94,120,137`; `monitoring.py:385`; `global_settings.py:347`) | M | Eliminates privilege escalation — biggest single security win | FIX NOW |
| 2 | P0 | Security | Hardcoded LDAP admin password `'admin'` as default (`config.py:19`; also `ldap_service.py:37`; `nagios.conf:20,34`) | S | Prevents trivial LDAP takeover if env var not set | FIX NOW |
| 3 | P0 | Security | Hardcoded fallback `nagiosadmin:nagiosadmin` when creds file missing (`proxy.py:67`; `host_manager.py:165-166`) | S | Stops unauthenticated proxy access with default Nagios creds | FIX NOW |
| 4 | P0 | Security | No CSRF protection on any POST forms (entire app) | M | Prevents CSRF attacks on all state-changing operations | FIX NOW |
| 5 | P1 | Security | Nextcloud password stored plaintext in `global_config.json` (`global_settings.py:262`) | S | Protects cloud storage credentials at rest | FIX NOW |
| 6 | P1 | Security | Uptime Kuma password stored plaintext in `global_config.json` (`global_settings.py:333`) | S | Protects monitoring platform credentials at rest | FIX NOW |
| 7 | P1 | Security | `tar.extractall('/tmp/restore_temp')` path traversal on backup restore (`global_settings.py:161`) | S | Prevents arbitrary file overwrite via malicious backup | FIX NOW |
| 8 | P1 | Bug | Hardcoded `'username': 'admin'` in Uptime Kuma login instead of `config['username']` (`monitoring_intens.py:79`) | S | Uptime Kuma integration actually works with configured user | FIX NOW |
| 9 | P1 | Security | Sound file upload accepts any extension — `.php`, `.sh` possible (`monitoring_settings.py:239-247`) | S | Prevents executable file upload to web-accessible dir | FIX NOW |
| 10 | P1 | Security | Plugin upload: unsanitized filename in `os.path.join` — path traversal (`servers.py:526`) | S | Prevents writing files outside plugin directory | FIX NOW |
| 11 | P1 | Security | `rm -rf /svr/{server}` with `server` from user input, no validation in batch-delete (`servers.py:256`) | S | Prevents directory deletion outside expected path | FIX NOW |
| 12 | P2 | Refactor | `_fetch_monitoring_hosts()` 163 lines, 5+ nesting levels, high cyclomatic complexity (`monitoring.py:140-303`) | L | Makes monitoring logic testable and maintainable | FIX SOON |
| 13 | P2 | Refactor | God file `servers.py` (670 LOC, 22 routes) | XL | Improves navigability and testability of server management | FIX SOON |
| 14 | P2 | Refactor | God file `host_manager.py` (665 LOC) | XL | Improves maintainability of host CRUD + backup logic | FIX SOON |
| 15 | P2 | Refactor | Duplicated host definition building in `host_manager.py:313-335` & `api.py:66-104` | M | Single source of truth for Nagios config generation | FIX SOON |
| 16 | P2 | Refactor | Local duplicate `get_nagios_servers()` / `get_monitoring_categories()` in `monitoring.py:22-82` ignoring `shared_helpers.py` | S | Eliminates divergent behavior between routes | FIX SOON |
| 17 | P2 | Security | Race condition: stage mutations outside `host_stages_transaction()` in `_fetch_monitoring_hosts()` (`monitoring.py:171`) | M | Prevents lost stage updates under concurrent requests | FIX SOON |
| 18 | P2 | Security | LDAP filter built via f-string interpolation — potential LDAP injection (`ldap_service.py:173`) | S | Prevents LDAP injection via crafted usernames | FIX SOON |
| 19 | P2 | Tech Debt | Debug `print()` leaks session data to stdout on every dashboard load (`dashboard.py:22`) | S | Stops leaking session data to logs | FIX SOON |
| 20 | P2 | Refactor | Config-loading boilerplate repeated 8+ times across blueprints | M | Reduces duplication, single error-handled loader | FIX SOON |
| 21 | P2 | Bug | Silent `except Exception: continue` in ThreadPoolExecutor swallows container fetch errors (`dashboard.py:154-155`) | S | Failed containers become visible instead of silently missing | FIX SOON |
| 22 | P2 | Bug | Error responses return `str(e)` to client — leaks internal paths (`dashboard.py:158-159`; `servers.py:167`) | S | Prevents information disclosure in error messages | FIX SOON |
| 23 | P2 | Security | Config editor writes arbitrary content to Nagios config without pre-save validation (`servers.py:456-459`) | M | Prevents invalid/malicious config from breaking Nagios | FIX SOON |
| 24 | P2 | Refactor | Bare `except Exception: pass` in `setup_ldap_structure()` and `setup()` route — swallows LDAP errors (`ldap_service.py:72-83`; `auth.py:107-118`) | S | LDAP setup failures become visible | FIX SOON |
| 25 | P2 | Performance | No connection pooling for Nagios CGI API — new `requests.get()` per call (entire app, `dashboard.py:57-58`, `monitoring.py:103-104`) | L | Reduces latency on monitoring data fetch | FIX SOON |
| 26 | P3 | Tech Debt | Zero test coverage — no `tests/`, no test framework in requirements.txt | XL | Enables regression prevention and safe refactoring | FIX LATER |
| 27 | P3 | Tech Debt | No CI/CD pipeline — no GitHub Actions, GitLab CI, or Jenkinsfile | L | Automates test/lint/deploy gatekeeping | FIX LATER |
| 28 | P3 | Tech Debt | `requests==2.31.0` has CVE-2024-35195 (Session verify bypass) (`requirements.txt:3`) | S | Eliminates known supply-chain vulnerability | FIX LATER |
| 29 | P3 | Tech Debt | No type checking — `mypy`/`pyright` not configured despite type hints | M | Catches type errors before runtime | FIX LATER |
| 30 | P3 | Tech Debt | No linting — no `ruff`, `flake8`, or `pylint` config | M | Enforces consistent code style | FIX LATER |
| 31 | P3 | Tech Debt | `cryptography>=41.0.0` unpinned — could pull incompatible version (`requirements.txt`) | S | Prevents surprise dependency breakage | FIX LATER |
| 32 | P3 | Tech Debt | No `.env.example` file — env vars undocumented | S | Onboarding: new deployer knows what to set | FIX LATER |
| 33 | P3 | Refactor | Magic number `1000` for proxy port offset repeated 8+ times (`servers.py:39,94,185,207,330,369,582,633,652`) | S | Improves readability, single point of change | FIX LATER |
| 34 | P3 | Refactor | Inconsistent path construction: mix of f-strings and `os.path.join()` | S | Reduces path bugs on non-Linux platforms | FIX LATER |
| 35 | P3 | Refactor | Deprecated `*_old.html` templates still tracked in repo | S | Cleans up repo, reduces confusion | FIX LATER |
| 36 | P3 | Refactor | `TRENDS_DUMMY_GUIDE.md` — internal demo doc in production repo | S | Keeps repo focused on production code | FIX LATER |
| 37 | P3 | Tech Debt | No API documentation / OpenAPI spec | M | Improves API discoverability for integrators | FIX LATER |
| 38 | P3 | Tech Debt | `APP_PORT` defaults to `5000` in code but AGENTS.md says `80` | S | Aligns docs with code | FIX LATER |

---

## Quick Wins

High impact, low effort (S). Knock these out first in a single sprint.

1. **#2** — Remove hardcoded LDAP admin password default (`config.py:19`). Change to `os.environ['LDAP_ADMIN_PASSWORD']` (no fallback). **5 min.**
2. **#3** — Remove `nagiosadmin:nagiosadmin` fallback in `proxy.py:67` and `host_manager.py:165-166`. Return 401/error instead. **15 min.**
3. **#5 + #6** — Encrypt Nextcloud and Uptime Kuma passwords using existing `save_encrypted_json()` for `global_config.json` password fields. **30 min total.**
4. **#7** — Fix `tar.extractall()` path traversal: add `filter='data'` (Python 3.12+) or validate member paths. **10 min.**
5. **#8** — Fix hardcoded `'admin'` in Uptime Kuma login to use `config['username']`. **5 min.**
6. **#9** — Whitelist sound file extensions (`.wav`, `.mp3`, `.ogg`) in `monitoring_settings.py:239`. **10 min.**
7. **#10** — Add `secure_filename()` to plugin upload in `servers.py:526`. **10 min.**
8. **#19** — Delete the debug `print()` in `dashboard.py:22`. **1 min.**

---

## Major Undertakings

P0/P1 items with L/XL effort. These need proper planning — design, review, phased rollout.

1. **#1 — Add permission checks to 25+ unprotected routes** (P0 · Security · M)
   While effort is only M, the scope is large: every route in `servers.py`, `host_manager.py`, `monitoring_settings.py` needs auditing. Recommend creating a decorator like `@permission_required('servers')` to prevent future omissions. Test each route after adding checks.

2. **#4 — Implement CSRF protection globally** (P0 · Security · M)
   Install Flask-WTF, enable `CSRFProtect(app)`, add `{{ csrf_token() }}` to all 18 templates with forms. Need to handle AJAX endpoints (exempt or return token). Test every form submission.

3. **#12 — Refactor `_fetch_monitoring_hosts()`** (P2 · Refactor · L)
   Split 163-line function into 3–4 focused functions. Needs careful testing of stage transition logic — currently no tests exist, so manual verification required. Consider writing tests first (TDD) to lock behavior before refactoring.

4. **#13 — Split `servers.py` god file** (P2 · Refactor · XL)
   670 LOC, 22 routes. Split into `servers_crud.py`, `servers_batch.py`, `servers_proxy.py`, `servers_plugins.py`. High risk of breaking routes — needs integration testing after split.

5. **#26 — Add test coverage from zero** (P3 · Tech Debt · XL)
   Start with unit tests for `services/encryption.py`, `services/stage_service.py`, `utils/permissions.py`. Then API endpoint tests for `blueprints/api.py`. Requires setting up `pytest`, `pytest-flask`, fixtures for Flask app + mock Docker. This is foundational — all other refactors become safer once tests exist.

6. **#27 — Set up CI/CD pipeline** (P3 · Tech Debt · L)
   GitHub Actions workflow: lint (ruff) → type check (mypy) → test (pytest) → build → deploy. Requires tests to exist first (#26). Can start with lint-only pipeline immediately.
