# UI/UX Phase 1: CSS Variable Replacement Plan

**Goal:** Replace all hardcoded hex colors with CSS variables. Dark mode works on all pages.
**Scope:** 16 templates, 800 hex values, 782 mappable, 18 KEEP (login gradient, dark theme internals)
**Risk:** Low — pure find-replace, no logic changes

---

## Step 0: Define CSS Variables in base.html

Consolidate existing `:root` (lines 11-51) + add missing variables. This is the foundation.

**File:** `templates/base.html`

```css
:root {
  /* Brand */
  --color-primary: #4f46e5;
  --color-primary-dark: #4338ca;
  --color-primary-darker: #312e81;
  --color-primary-light: #e0e7ff;
  --color-primary-lighter: #eef2ff;
  --color-secondary: #06b6d4;

  /* Status */
  --color-success: #10b981;
  --color-success-dark: #059669;
  --color-success-light: #86efac;
  --color-danger: #ef4444;
  --color-danger-alt: #dc2626;
  --color-danger-dark: #b91c1c;
  --color-warning: #f59e0b;
  --color-warning-dark: #d97706;
  --color-warning-light: #fde68a;
  --color-warning-alt: #fbbf24;
  --color-info: #3b82f6;
  --color-info-dark: #1d4ed8;
  --color-gray: #6b7280;
  --color-purple: #7e22ce;
  --color-purple-light: #d8b4fe;
  --color-orange-dark: #c2410c;

  /* Text */
  --text-primary: #1e293b;
  --text-secondary: #64748b;
  --text-muted: #94a3b8;

  /* Backgrounds */
  --bg-primary: #f8fafc;
  --bg-secondary: #ffffff;
  --bg-tertiary: #f1f5f9;

  /* Borders */
  --border-color: #e2e8f0;
  --border-color-alt: #cbd5e1;

  /* Alerts */
  --alert-success-bg: #d1fae5;
  --alert-success-color: #065f46;
  --alert-error-bg: #fee2e2;
  --alert-error-color: #991b1b;
  --alert-info-bg: #dbeafe;
  --alert-info-color: #1e40af;
  --alert-warning-bg: #fef3c7;
  --alert-warning-color: #92400e;
  --alert-purple-bg: #f5f3ff;
}

[data-theme="dark"] {
  --color-primary: #818cf8;
  --color-primary-dark: #6366f1;
  --color-primary-darker: #4338ca;
  --color-primary-light: #312e81;
  --color-primary-lighter: #1e1b4b;
  --color-secondary: #22d3ee;
  --color-success: #34d399;
  --color-success-dark: #10b981;
  --color-success-light: #064e3b;
  --color-danger: #f87171;
  --color-danger-alt: #ef4444;
  --color-danger-dark: #dc2626;
  --color-warning: #fbbf24;
  --color-warning-dark: #f59e0b;
  --color-warning-light: #78350f;
  --color-warning-alt: #fbbf24;
  --color-info: #60a5fa;
  --color-info-dark: #3b82f6;
  --color-gray: #9ca3af;
  --color-purple: #a78bfa;
  --color-purple-light: #3b0764;
  --color-orange-dark: #ea580c;

  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;

  --bg-primary: #0f172a;
  --bg-secondary: #1e293b;
  --bg-tertiary: #334155;

  --border-color: #334155;
  --border-color-alt: #475569;

  --alert-success-bg: #064e3b;
  --alert-success-color: #6ee7b7;
  --alert-error-bg: #7f1d1d;
  --alert-error-color: #fca5a5;
  --alert-info-bg: #1e3a5f;
  --alert-info-color: #93c5fd;
  --alert-warning-bg: #78350f;
  --alert-warning-color: #fde68a;
  --alert-purple-bg: #3b0764;
}
```

**Verify:** Toggle dark mode — navbar, sidebar, alerts switch correctly.

---

## Step 1: base.html — Consolidate + Replace Internal Hex

**File:** `templates/base.html` (154 hex, 142 mappable)
**Action:** Replace hardcoded hex in the `<style>` block with var() references.

Key replacements (top occurrences):
| Hex | Count | Replace With |
|-----|-------|-------------|
| `#334155` | 12 | `var(--bg-tertiary)` |
| `#1e293b` | 11 | `var(--text-primary)` |
| `#ffffff` | 10 | `var(--bg-secondary)` |
| `#4f46e5` | 7 | `var(--color-primary)` |
| `#94a3b8` | 7 | `var(--text-muted)` |
| `#e2e8f0` | 7 | `var(--border-color)` |
| `#475569` | 7 | `var(--text-secondary)` |
| `#f1f5f9` | 6 | `var(--bg-tertiary)` |
| `#0f172a` | 4 | `var(--bg-primary)` |
| `#818cf8` | 4 | `var(--color-primary-light)` |

**KEEP (12 hex):** `#2d3748`(3x), `#00f2fe`(2x), `#8892a4`(2x), `#4e54c8`(1x), `#e0e0e0`(1x), `#1e2530`(1x), `#111622`(1x), `#00a8e8`(1x) — these are in dark mode overrides or gradients that should stay as-is.

**Verify:** Page loads correctly in light mode. Dark mode toggle works.

---

## Step 2: monitoring.html — Largest File (164 hex)

**File:** `templates/monitoring.html` (164 hex, 163 mappable)
**Risk:** High — most complex template, used daily by NOC

Key replacements:
| Hex | Count | Replace With |
|-----|-------|-------------|
| `#f1f5f9` | 12 | `var(--bg-tertiary)` |
| `#475569` | 12 | `var(--text-secondary)` |
| `#334155` | 11 | `var(--bg-tertiary)` |
| `#e2e8f0` | 10 | `var(--border-color)` |
| `#1e293b` | 10 | `var(--text-primary)` |
| `#94a3b8` | 10 | `var(--text-muted)` |
| `#4f46e5` | 9 | `var(--color-primary)` |
| `#64748b` | 9 | `var(--text-secondary)` |
| `#ef4444` | 6 | `var(--color-danger)` |

**KEEP (1 hex):** `#78716c`(1x) — neutral stone color for specific use.

**Verify:** Monitoring page loads, filters work, stage badges visible, batch operations work, alarm sounds play.

---

## Step 3: host_manager.html (100 hex)

**File:** `templates/host_manager.html` (100 hex, 100 mappable)

Key replacements:
| Hex | Count | Replace With |
|-----|-------|-------------|
| `#e2e8f0` | 36 | `var(--border-color)` |
| `#64748b` | 9 | `var(--text-secondary)` |
| `#dc2626` | 7 | `var(--color-danger-alt)` |
| `#1e293b` | 6 | `var(--text-primary)` |
| `#f8fafc` | 6 | `var(--bg-primary)` |
| `#94a3b8` | 5 | `var(--text-muted)` |
| `#6b7280` | 4 | `var(--color-gray)` |

**Verify:** Host list loads, add/edit/delete host works, modals display correctly, backup/restore works.

---

## Step 4: servers.html (74 hex)

**File:** `templates/servers.html` (74 hex, 74 mappable)

Key replacements:
| Hex | Count | Replace With |
|-----|-------|-------------|
| `#1e293b` | 9 | `var(--text-primary)` |
| `#f1f5f9` | 7 | `var(--bg-tertiary)` |
| `#f8fafc` | 5 | `var(--bg-primary)` |
| `#64748b` | 5 | `var(--text-secondary)` |
| `#94a3b8` | 5 | `var(--text-muted)` |
| `#4f46e5` | 4 | `var(--color-primary)` |
| `#e2e8f0` | 4 | `var(--border-color)` |
| `#ef4444` | 4 | `var(--color-danger)` |

**Verify:** Server list loads, start/stop/restart works, proxy controls work, config editor works.

---

## Step 5: global_settings.html (47 hex)

**File:** `templates/global_settings.html` (47 hex, 47 mappable)

**Verify:** Settings page loads, all forms submit, backup/restore works, API key generation works.

---

## Step 6: monitoring_settings.html (45 hex)

**File:** `templates/monitoring_settings.html` (45 hex, 44 mappable)

**KEEP (1 hex):** `#0369a1`(1x) — specific info-dark shade.

**Verify:** Category management works, alarm settings work, sound upload works.

---

## Step 7: monitoring_intens.html (37 hex)

**File:** `templates/monitoring_intens.html` (37 hex, 36 mappable)

**KEEP (1 hex):** `#039`(1x) — shorthand hex.

**Verify:** Uptime Kuma monitors load, status indicators correct.

---

## Step 8: Remaining Templates (batch)

Process in order of hex count:

| Template | Hex | Mappable | Effort |
|----------|-----|----------|--------|
| users.html | 31 | 31 | S |
| user_permissions.html | 28 | 28 | S |
| dashboard.html | 29 | 29 | S |
| activity_logs.html | 20 | 20 | S |
| login.html | 19 | 12 | S |
| stage_history.html | 19 | 19 | S |
| setup.html | 14 | 14 | S |
| edit_config.html | 4 | 2 | S |
| nagios_view.html | 3 | 3 | S |

**KEEP (18 hex total):**
- login.html: `#667eea`(4x), `#764ba2`(2x), `#fff`(1x) — login gradient background
- edit_config.html: `#333`(1x), `#ddd`(1x) — textarea border
- monitoring_intens.html: `#039`(1x) — shorthand hex

**Verify per template:** Page loads, forms submit, data displays correctly.

---

## Step 9: Remove Dark Mode "Nuclear Wildcard" Overrides

**File:** `templates/base.html` (lines 648-799)
**Action:** Delete the `[data-theme="dark"] .content *` wildcard overrides. CSS variables handle everything now.

**Verify:** Dark mode works on ALL pages without the wildcard overrides. No broken colors.

---

## Step 10: Uncomment Dark Mode Toggle

**File:** `templates/base.html:349-353`
**Action:** Uncomment the dark mode toggle button.

**Verify:** Toggle visible in navbar, switches theme correctly on all pages.

---

## Execution Order & Verification

| Step | File(s) | Hex Count | Effort | Verify After |
|------|---------|-----------|--------|-------------|
| 0 | base.html (CSS vars) | 0 | S | CSS vars defined, light mode works |
| 1 | base.html (replace) | 142 | M | Light + dark mode works |
| 2 | monitoring.html | 163 | M | Monitoring page works in both themes |
| 3 | host_manager.html | 100 | M | Host CRUD works in both themes |
| 4 | servers.html | 74 | M | Server management works |
| 5 | global_settings.html | 47 | S | Settings work |
| 6 | monitoring_settings.html | 44 | S | Alarm config works |
| 7 | monitoring_intens.html | 36 | S | Uptime Kuma works |
| 8 | 9 remaining | 158 | M | All pages work |
| 9 | Remove wildcards | 0 | S | Dark mode still works |
| 10 | Enable toggle | 0 | S | Toggle visible + functional |

**Total:** 782 replacements, ~10 steps, ~1-2 days

---

## Risk Mitigation

1. **After each step:** Verify light mode looks identical to before
2. **After step 1:** Verify dark mode toggle works on base.html elements
3. **After step 2:** Verify monitoring page (most critical page) works in both themes
4. **After step 9:** Verify dark mode works WITHOUT wildcard overrides
5. **If something breaks:** Revert that specific template, not everything

## Files NOT Modified

- `static/` — no CSS/JS files exist (all inline)
- `blueprints/` — no Python changes
- `services/` — no backend changes
- `login.html` gradient — `#667eea → #764ba2` stays hardcoded (brand-specific gradient)
