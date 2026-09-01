# Nagios Dashboard — Improvement Plan

Living backlog. Historical security/bug work is done (see git history + `AGENTS.md`).  
**Last updated:** 2026-08-29

## Snapshot

| Area | Status |
|---|---|
| Security Phase 1–4 (CSRF, perms, encryption, path fixes) | Done |
| Theme Batch A/B + dark FOWT | Done (prod) |
| `/monitoring-settings` + `/global-settings` modern UI | Done (prod) |
| Activity Logs only under Audit | Done |
| Phase 1: stages → SQLite WAL (`host_stages.db`) | Done (prod) |
| Phase 2: `nagios-poller` + CGI snapshot DB | Done (prod) |
| Phase 3: single `async_proxy.py` multiplexer | Done (prod) |
| Dashboard stats from snapshot (no `docker stats`) | Done (prod) |
| Intensive Monitoring | **HOLD** — stripped on Prod deploy |
| Remaining settings JSON (categories, perms, mappings) | Intentional — not a second SQLite project |

## Open items (user-decide / backlog)

### Reliability
| ID | Item | Notes |
|---|---|---|
| R2 | Pre-save Nagios config validation (`nagios -v`) | Optional safety on host/config edits |

### Architecture
| ID | Item | Notes |
|---|---|---|
| A2 | Extract shared `load_json_config()` / host definition builder | DRY; low urgency after shared_helpers |
| A3 | Docker volume base `/svr/<server>/` hardcoded | Intentional for this deploy topology |

### UI / polish (optional P3)
| ID | Item | Notes |
|---|---|---|
| U1 | `monitoring_intens` residual token cleanup | border-as-text etc. |
| U2 | `edit_config` residual hex / borders | Low traffic page |
| U3 | `::selection` + stronger print/prefers-color fallbacks | Theme residual |
| U4 | Shared form/button primitives across pages | Reduce per-page CSS duplication |
| U5 | a11y: more `aria-*` / label `for=` coverage | Partial already |

### Security hold (internal tool)
| ID | Item | Notes |
|---|---|---|
| S1 | `send_file` / backup filename extra sanitization | Hold — internal |
| S2 | `/health` unauthenticated | Hold — intentional for probes |

## Deploy rules (current)

1. **UI/theme:** smoke on dev → explicit deploy → UI files only (never `config/`).
2. Backup targets under `config/backups/<name>_deploy_<TS>/`.
3. Config MD5 PRE must equal POST; UI MD5 local == prod.
4. Prod has **no git** — compare/deploy via SCP + `root@` + `bash -lc`.
5. After class-namespace redesigns on dev: **restart Waitress**.
6. After poller code: `rc-service nagios-poller restart`. After multiplexer/initd: `rc-service nagios-proxy restart`. Never spawn `proxy.py`.

Proven backups: `theme_deploy_20260721_025201`, `ms_ui_deploy_20260721_033712`, `gs_ui_deploy_20260721_034854`.

## Docs map

| Doc | Role |
|---|---|
| `README.md` | User/dev feature overview + current architecture |
| `USER_GUIDE.md` | Operator guide (ID) |
| `AGENTS.md` | Agent/architecture context |
| `.cursorrules` | Persistent AI session constraints |
| `IMPROVEMENT_PLAN.md` | This backlog |
| `MODERNIZATION_ROADMAP.md` | Historical Phases 1–3 plan (implemented) |
| `TECH_STACK_AUDIT.md` | Historical audit (pre-implementation) |
| `TRENDS_DUMMY_GUIDE.md` | Demo-only Nagios trends injection |
| `create-nagios/README.md` | Nagios container image build |

Theme/UI implementation detail for agents lives in Hermes skill `nagios-dashboard` references (not duplicated here as session logs).
