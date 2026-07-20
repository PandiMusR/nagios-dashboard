# Nagios Dashboard — Improvement Plan

Living backlog. Historical security/bug work is done (see git history + `AGENTS.md`).  
**Last updated:** 2026-07-21

## Snapshot

| Area | Status |
|---|---|
| Security Phase 1–4 (CSRF, perms, encryption, path fixes) | Done |
| Theme Batch A/B + dark FOWT | Done (prod) |
| `/monitoring-settings` + `/global-settings` modern UI | Done (prod) |
| Activity Logs only under Audit | Done |
| SQLite migration | Not started |
| Connection pooling Nagios CGI | Open (user decide) |
| Stage tracking race hardening | Open (user decide) |

## Open items (user-decide / backlog)

### Reliability
| ID | Item | Notes |
|---|---|---|
| R1 | Stage tracking race (beyond current lock) | Optional; file JSON still used |
| R2 | Pre-save Nagios config validation (`nagios -v`) | Optional safety on host/config edits |
| R3 | Connection pooling HTTP → Nagios CGI | Performance under many containers |

### Architecture
| ID | Item | Notes |
|---|---|---|
| A1 | SQLite (or similar) instead of flat JSON | Large migration; not started |
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

Proven backups: `theme_deploy_20260721_025201`, `ms_ui_deploy_20260721_033712`, `gs_ui_deploy_20260721_034854`.

## Docs map

| Doc | Role |
|---|---|
| `README.md` | User/dev feature overview |
| `USER_GUIDE.md` | Operator guide (ID) |
| `AGENTS.md` | Agent/architecture context |
| `IMPROVEMENT_PLAN.md` | This backlog |
| `TRENDS_DUMMY_GUIDE.md` | Demo-only Nagios trends injection |
| `create-nagios/README.md` | Nagios container image build |

Theme/UI implementation detail for agents lives in Hermes skill `nagios-dashboard` references (not duplicated here as session logs).
