# UI/UX Triage & Fix Plan — Nagios Dashboard

**Based on:** `UIUX_AUDIT.md` (2026-07-14)
**Last updated:** 2026-07-15 (Phase 1 + Quick Wins + alert→toast done)
**Stack:** Flask + Jinja2, Bootstrap 5.3, Vanilla JS, Font Awesome 6.4
**Audience:** NOC engineers (8+ hours/day, incident-driven)

## Triage Summary

| # | Priority | Category | Finding | Effort | Impact | Bucket | Status |
|---|----------|----------|---------|--------|--------|--------|--------|
| 1 | P0 | Consistency | All 14 child templates hardcode hex colors — dark mode broken | XL | Unblocks dark mode for all pages | 🔴 FIX NOW | ✅ DONE (Phase 1) |
| 2 | P0 | Accessibility | 0 aria-* attributes, no lang on html | M | Screen reader users can't use dashboard | 🔴 FIX NOW | ⚠️ PARTIAL (lang+viewport done, aria pending) |
| 3 | P0 | Responsiveness | Missing `<meta name="viewport">` in base.html | S | Mobile rendering broken | 🔴 FIX NOW | ✅ DONE |
| 4 | P1 | Architecture | Shared components (.btn-primary, .form-group, .modal) redefined per page | L | Consistency, maintainability | 🟡 FIX SOON | ❌ PENDING |
| 5 | P1 | Consistency | 50 alert() calls for error/success feedback | M | Professional UX, no browser dialog popups | 🟡 FIX SOON | ✅ DONE (toast system) |
| 6 | P1 | Data Density | Monitoring page console.error on fetch failure — no user feedback | S | NOC sees nothing when API fails | 🟡 FIX SOON | ✅ DONE (retry + error UI) |
| 7 | P1 | Data Density | No global "total hosts down" summary on dashboard | S | NOC can't instantly see total problems | 🟡 FIX SOON | ❌ PENDING |
| 8 | P1 | Data Density | Dashboard cards don't highlight critical servers | S | Critical servers look same as healthy | 🟡 FIX SOON | ✅ DONE (border-left highlight) |
| 9 | P1 | Dark Mode | Dark mode uses "nuclear wildcard" !important overrides | M | Dark mode breaks colored badges | 🟡 FIX SOON | ✅ DONE (removed wildcards, now var()) |
| 10 | P2 | Accessibility | Form inputs lack `<label for>` association | M | Form accessibility | 🟢 FIX LATER | ❌ PENDING |
| 11 | P2 | Architecture | 18 inline `<style>` blocks, 12 `<script>` blocks | M | Page weight, caching | 🟢 FIX LATER | ❌ PENDING |
| 12 | P2 | Consistency | Mixed Indonesian/English language | S | Professional polish | 🟢 FIX LATER | ❌ PENDING |
| 13 | P2 | Dark Mode | Dark mode toggle commented out | S | Enable after #1 and #9 done | 🟢 FIX LATER | ✅ DONE |
| 14 | P3 | Data Density | No keyboard shortcuts for common NOC actions | S | Power user productivity | 🟢 FIX LATER | ❌ PENDING |
| 15 | P3 | Consistency | Page gradient header redefined per template | S | Code deduplication | 🟢 FIX LATER | ❌ PENDING |

---

## Deep Dive: Top 3 Pain Points

### CSS Variable Analysis (14 templates)

All 14 child templates hardcode hex colors instead of using CSS variables defined in `base.html:11-82`.

| Template | Hardcoded Hex Count | Top Offenders |
|----------|-------------------|---------------|
| monitoring.html | 161 | `#e2e8f0`(12x), `#1e293b`(10x), `#64748b`(8x) |
| base.html | 154 | Already uses vars, but dark mode overrides use hex |
| host_manager.html | 99 | `#e2e8f0`(8x), `#1e293b`(7x), `#4f46e5`(6x) |
| servers.html | 74 | `#e2e8f0`(6x), `#1e293b`(5x), `#f1f5f9`(4x) |
| global_settings.html | 47 | `#e2e8f0`(4x), `#1e293b`(4x) |
| monitoring_settings.html | 45 | `#e2e8f0`(4x), `#1e293b`(3x) |
| monitoring_intens.html | 37 | `#e2e8f0`(3x), `#4f46e5`(3x) |
| users.html | 31 | `#e2e8f0`(3x), `#1e293b`(2x) |
| user_permissions.html | 28 | `#e2e8f0`(2x), `#1e293b`(2x) |
| dashboard.html | 27 | `#4f46e5`(3x), `#06b6d4`(2x) |
| activity_logs.html | 20 | `#e2e8f0`(2x), `#1e293b`(2x) |
| login.html | 19 | `#667eea`(2x), `#764ba2`(1x) |
| stage_history.html | 19 | `#e2e8f0`(2x), `#1e293b`(2x) |
| setup.html | 14 | `#3b82f6`(2x) |
| edit_config.html | 4 | `#1e3a8a`(1x), `#333`(1x) |
| nagios_view.html | 3 | minimal |

**Total hardcoded hex: 800 instances across 16 files**
**Can Bootstrap utilities replace some?** Yes — `text-danger` for `#dc3545`, `bg-light` for `#f8fafc`, `border` for `#e2e8f0`. But most are custom design system colors (gradients, shadows, specific shades) that need CSS variables.

### Inline Style Breakdown (327 instances)

| Category | Count | % | Bootstrap Replaceable? |
|----------|-------|---|----------------------|
| Spacing (margin/padding) | 210 | 22.2% | ~60% (p-*, m-*, gap-*) |
| Typography (font/size/weight) | 185 | 19.6% | ~40% (fs-*, fw-*, text-*) |
| Color/Background | 146 | 15.5% | ~30% (text-*, bg-*) |
| Border/Shadow/Radius | 130 | 13.8% | ~20% (border, rounded, shadow) |
| Sizing (width/height) | 81 | 8.6% | ~50% (w-*, h-*) |
| Layout (display/flex/grid) | 70 | 7.4% | ~80% (d-flex, g-*, etc) |
| Interaction (cursor/transition) | 58 | 6.1% | ~10% (mostly custom) |
| Other | 64 | 6.8% | varies |

**Top offenders:** host_manager.html (102), monitoring.html (76), monitoring_settings.html (39), servers.html (34)

**Estimate:** ~45% replaceable with Bootstrap utilities, ~55% need custom CSS classes.

### Hex Value Deduplication (800 → 96 unique → 30 semantic)

**Top 10 colors (covers 70% of all usage):**

| Hex | Count | Semantic Name | Usage |
|-----|-------|---------------|-------|
| `#e2e8f0` | 86 | `--border-color` | Borders everywhere |
| `#1e293b` | 68 | `--text-primary` | Headings, dark text |
| `#64748b` | 58 | `--text-secondary` | Secondary text |
| `#4f46e5` | 51 | `--color-primary` | Buttons, links, accents |
| `#f1f5f9` | 46 | `--bg-tertiary` | Table headers, subtle bg |
| `#94a3b8` | 43 | `--text-muted` | Muted text |
| `#f8fafc` | 31 | `--bg-primary` | Page background |
| `#475569` | 31 | `--text-secondary-dark` | Dark theme text |
| `#334155` | 25 | `--bg-tertiary-dark` | Dark theme bg |
| `#06b6d4` | 21 | `--color-secondary` | Gradient accent |

---

## Proposed CSS Variable Palette

```css
:root {
  /* Brand */
  --color-primary: #4f46e5;
  --color-primary-dark: #4338ca;
  --color-secondary: #06b6d4;

  /* Status */
  --color-success: #10b981;
  --color-danger: #ef4444;
  --color-danger-alt: #dc2626;
  --color-warning: #f59e0b;
  --color-info: #3b82f6;
  --color-gray: #6b7280;

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

  /* Components */
  --card-bg: #ffffff;
  --card-border: #f1f5f9;
  --table-header-bg: #f8fafc;
  --table-row-border: #f1f5f9;
  --sidebar-bg: #ffffff;
  --input-bg: #ffffff;
  --input-border: #e2e8f0;
  --modal-bg: #ffffff;

  /* Shadows */
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.05);
  --shadow-md: 0 4px 20px rgba(0,0,0,0.08);

  /* Sidebar */
  --sidebar-width: 280px;
  --sidebar-collapsed: 80px;
}

[data-theme="dark"] {
  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;
  --bg-primary: #0f172a;
  --bg-secondary: #1e293b;
  --bg-tertiary: #334155;
  --border-color: #334155;
  --border-color-alt: #475569;
  --card-bg: #1e293b;
  --card-border: #334155;
  --table-header-bg: #334155;
  --table-row-border: #334155;
  --sidebar-bg: #1e293b;
  --input-bg: #1e293b;
  --input-border: #475569;
  --modal-bg: #1e293b;
  --alert-success-bg: #064e3b;
  --alert-success-color: #6ee7b7;
  --alert-error-bg: #7f1d1d;
  --alert-error-color: #fca5a5;
  --alert-info-bg: #1e3a5f;
  --alert-info-color: #93c5fd;
  --alert-warning-bg: #78350f;
  --alert-warning-color: #fde68a;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.2);
  --shadow-md: 0 4px 20px rgba(0,0,0,0.3);
}
```

---

## Quick Wins (do these today)

### Quick Win 1: Add viewport meta to base.html
**File:** `templates/base.html:2`
**Effort:** 2 min
**Before:**
```html
<html>
```
**After:**
```html
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
```
**Impact:** Mobile rendering works correctly.

### Quick Win 2: Add lang attribute to login.html and setup.html
**File:** `templates/login.html:2`, `templates/setup.html:2`
**Effort:** 2 min
**Before:**
```html
<html>
```
**After:**
```html
<html lang="en">
```
**Impact:** Screen readers identify page language.

### Quick Win 3: Show error to user on monitoring fetch failure
**File:** `templates/monitoring.html:660`
**Effort:** 5 min
**Before:**
```javascript
console.error('Error fetching monitoring data:', error);
```
**After:**
```javascript
console.error('Error fetching monitoring data:', error);
const tbody = document.getElementById('hostsTableBody');
if (tbody) {
    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger p-4"><i class="fas fa-exclamation-triangle me-2"></i>Failed to load monitoring data. <button onclick="location.reload()" class="btn btn-sm btn-outline-danger ms-2">Retry</button></td></tr>';
}
```
**Impact:** NOC sees error + retry button instead of blank table.

### Quick Win 4: Add loading state to host manager table
**File:** `templates/host_manager.html:439`
**Effort:** 5 min
**Before:**
```html
<tbody id="hostTableBody">
</tbody>
```
**After:**
```html
<tbody id="hostTableBody">
    <tr><td colspan="7" class="text-center p-4"><i class="fas fa-spinner fa-spin me-2"></i>Loading hosts...</td></tr>
</tbody>
```
**Impact:** User sees loading indicator instead of empty table.

### Quick Win 5: Highlight critical servers on dashboard
**File:** `templates/dashboard.html:225`
**Effort:** 10 min
Add red left border to server cards with DOWN hosts:
```javascript
// In the card rendering logic, add:
const hasDown = stats.hosts_down > 0;
card.style.borderLeft = hasDown ? '4px solid #ef4444' : '4px solid #10b981';
```
**Impact:** NOC instantly sees which servers have problems.

---

## Phased Fix Plan

### Phase 1: CSS Variable Foundation
**Goal:** Replace all hardcoded hex colors with CSS variables. Dark mode works on all pages.

**Files to Modify:**
- `templates/base.html` — consolidate `:root` and `[data-theme="dark"]` variables
- All 14 child templates — replace hardcoded hex with `var(--*)`

**Tasks:**

1. **Consolidate CSS variables in base.html**
   - Merge existing `:root` (lines 11-51) with proposed palette above
   - Refactor `[data-theme="dark"]` (lines 53-82) to use clean variable overrides
   - Remove "nuclear wildcard" dark mode overrides (lines 648-799)
   - Files: `templates/base.html`
   - Effort: M (2h)
   - Verify: Toggle dark mode — navbar, sidebar, content all switch correctly

2. **Replace hardcoded hex in dashboard.html**
   - 27 replacements: `#4f46e5` → `var(--color-primary)`, `#1e293b` → `var(--text-primary)`, etc.
   - File: `templates/dashboard.html`
   - Effort: S (30min)
   - Verify: Page looks identical in light mode, dark mode shows correct colors

3. **Replace hardcoded hex in monitoring.html**
   - 161 replacements (largest file)
   - File: `templates/monitoring.html`
   - Effort: M (2h)
   - Verify: Monitoring page, filters, table, stage badges all work in both themes

4. **Replace hardcoded hex in host_manager.html**
   - 99 replacements
   - File: `templates/host_manager.html`
   - Effort: M (1.5h)
   - Verify: Host CRUD, modals, backup/restore all work in both themes

5. **Replace hardcoded hex in servers.html**
   - 74 replacements
   - File: `templates/servers.html`
   - Effort: M (1h)
   - Verify: Server list, start/stop/restart, config editor all work

6. **Replace hardcoded hex in remaining 9 templates**
   - global_settings (47), monitoring_settings (45), monitoring_intens (37), users (31), user_permissions (28), activity_logs (20), login (19), stage_history (19), setup (14), edit_config (4), nagios_view (3)
   - Files: All remaining templates
   - Effort: M (3h total)
   - Verify: Each page looks identical in light mode, dark mode works

**Phase Exit Criteria:**
- [ ] Zero hardcoded hex colors in any template (except login.html gradient background)
- [ ] Dark mode toggle works on ALL pages — no broken colors
- [ ] All pages look identical in light mode to before
- [ ] CSS variable count in `:root`: ~35 variables

---

### Phase 2: Shared Component Extraction
**Goal:** Extract duplicated CSS classes to base.html. One definition per component.

**Files to Modify:**
- `templates/base.html` — add shared component classes
- All child templates — remove per-page `<style>` blocks for shared components

**Tasks:**

1. **Extract `.page-header` to base.html**
   - Current: Every template defines its own gradient header with same gradient
   - Create: `.page-header { background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-secondary) 100%); padding: 2rem; border-radius: 16px; color: white; margin-bottom: 2rem; }`
   - Files: `base.html` (add), all child templates (remove duplicates)
   - Effort: S (30min)
   - Verify: All page headers look identical

2. **Extract `.btn-primary` to base.html**
   - Current: 6 templates define `.btn-primary` with different padding/sizing
   - Files: `base.html`, servers.html, users.html, host_manager.html, global_settings.html, monitoring_settings.html, user_permissions.html
   - Effort: S (30min)
   - Verify: All primary buttons same size/style

3. **Extract `.form-group` to base.html**
   - Current: 8 templates define `.form-group` with slight variations
   - Files: `base.html`, monitoring.html, servers.html, users.html, host_manager.html, global_settings.html, monitoring_settings.html, stage_history.html
   - Effort: S (30min)

4. **Extract `.section-card` to base.html**
   - Current: 7 templates define `.section-card`
   - Files: `base.html`, users.html, host_manager.html, global_settings.html, monitoring_settings.html, activity_logs.html, stage_history.html, user_permissions.html
   - Effort: S (30min)

5. **Extract `.modal` styles to base.html**
   - Current: 5 templates define modal styles differently
   - Files: `base.html`, monitoring.html, servers.html, user_permissions.html, host_manager.html, monitoring_settings.html
   - Effort: M (1h)

6. **Extract `.status-badge` to base.html**
   - Current: dashboard.html, monitoring.html, servers.html define differently
   - Files: `base.html`, dashboard.html, monitoring.html, servers.html
   - Effort: S (20min)

7. **Extract `@keyframes` to base.html**
   - Current: fadeIn and slideUp duplicated in 4 templates
   - Files: `base.html`, dashboard.html, monitoring.html, servers.html, host_manager.html
   - Effort: S (10min)

**Phase Exit Criteria:**
- [ ] `.page-header`, `.btn-primary`, `.form-group`, `.section-card`, `.modal`, `.status-badge` defined once in base.html
- [ ] Child templates no longer redefine these classes
- [ ] All pages look identical to Phase 1

---

### Phase 3: Inline Style Cleanup (High-Traffic Pages)
**Goal:** Replace inline `style=` with Bootstrap utilities or custom CSS classes on primary pages.

**Priority order:** monitoring.html (76) → host_manager.html (102) → dashboard.html (8) → servers.html (34)

**Tasks:**

1. **Clean monitoring.html inline styles (76 instances)**
   - Replace `style="padding: 1.25rem 1rem"` with `class="p-3 px-4"`
   - Replace `style="font-weight: 600"` with `class="fw-semibold"`
   - Replace `style="display: flex; gap: 1rem"` with `class="d-flex gap-3"`
   - File: `templates/monitoring.html`
   - Effort: M (2h)
   - Verify: Monitoring page looks identical, all interactions work

2. **Clean host_manager.html inline styles (102 instances)**
   - File: `templates/host_manager.html`
   - Effort: M (2.5h)
   - Verify: Host CRUD, modals, batch operations all work

3. **Clean servers.html inline styles (34 instances)**
   - File: `templates/servers.html`
   - Effort: S (1h)
   - Verify: Server management, proxy controls all work

4. **Clean dashboard.html inline styles (8 instances)**
   - File: `templates/dashboard.html`
   - Effort: S (20min)
   - Verify: Dashboard cards, stats all work

**Phase Exit Criteria:**
- [ ] Inline style count reduced from 327 to <100
- [ ] Primary pages (monitoring, host_manager, dashboard, servers) have <10 inline styles each
- [ ] All pages look identical

---

### Phase 4: Accessibility & Error Handling
**Goal:** Make dashboard usable with screen readers. Replace alert() with toasts.

**Tasks:**

1. **Add aria-* attributes to key interactive elements**
   - Sidebar menu: `role="navigation"`, `aria-label="Main menu"`
   - Submenu toggles: `role="button"`, `aria-expanded="true/false"`
   - Monitoring table: `role="table"`, `aria-label="Host monitoring"`
   - Checkboxes: `aria-label="Select host [hostname]"`
   - Files: `base.html`, `monitoring.html`, `host_manager.html`
   - Effort: M (2h)
   - Verify: VoiceOver/NVDA reads page structure correctly

2. **Add `<label for>` to form inputs**
   - servers.html: add server form, edit config form
   - host_manager.html: add host form, edit host form
   - monitoring.html: filter selects
   - Files: servers.html, host_manager.html, monitoring.html, users.html
   - Effort: M (1.5h)
   - Verify: Tab through forms — labels read correctly

3. **Add visible focus indicators**
   - In base.html: `button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }`
   - File: `templates/base.html`
   - Effort: S (15min)
   - Verify: Tab through page — all interactive elements show focus ring

4. **Replace alert() with toast notifications (50 instances)**
   - Create toast function in base.html: `function showToast(message, type) { ... }`
   - Replace `alert('Success!')` with `showToast('Success!', 'success')`
   - Replace `alert('Error: ...')` with `showToast('Error: ...', 'error')`
   - Priority files: servers.html (14), global_settings.html (10), monitoring.html (8), host_manager.html (7)
   - Effort: M (3h)
   - Verify: All operations show toast instead of browser dialog

5. **Add error UI to monitoring fetch failure**
   - File: `templates/monitoring.html:660`
   - Effort: S (10min) — already detailed in Quick Wins
   - Verify: Disconnect network → see error banner with retry button

**Phase Exit Criteria:**
- [ ] `aria-*` count > 20 (from 0)
- [ ] All form inputs have `<label for>` association
- [ ] Focus indicators visible on all interactive elements
- [ ] `alert()` count reduced from 50 to <10
- [ ] Monitoring page shows error UI on fetch failure

---

### Phase 5: Polish & Performance
**Goal:** Data density improvements, language standardization, performance.

**Tasks:**

1. **Add global "total hosts down" to dashboard header**
   - File: `templates/dashboard.html:180-196`
   - Add: `<span class="stat-badge">Total DOWN: X</span>` in header
   - Effort: S (20min)
   - Verify: Dashboard shows total across all servers

2. **Standardize language to English**
   - Replace Indonesian strings in: base.html (password form), monitoring.html (stage labels), activity_logs.html, stage_history.html
   - Files: base.html, monitoring.html, activity_logs.html, stage_history.html
   - Effort: S (30min)
   - Verify: All UI text in English

3. **Add `<meta name="viewport">` to setup.html**
   - File: `templates/setup.html:2`
   - Effort: S (2min)
   - Verify: Setup page renders correctly on mobile

4. **Uncomment dark mode toggle**
   - File: `templates/base.html:349-353`
   - Effort: S (2min)
   - Only after Phase 1 complete
   - Verify: Toggle button visible and functional

5. **Add image dimensions to prevent layout shift**
   - File: `templates/base.html:344` — add `width="32" height="32"`
   - File: `templates/login.html:101` — add dimensions
   - Effort: S (5min)

**Phase Exit Criteria:**
- [ ] Dashboard shows total hosts down prominently
- [ ] All UI text in English
- [ ] Dark mode toggle enabled and working
- [ ] No layout shifts on page load

---

## Estimated Total Timeline

| Phase | Effort | Duration |
|-------|--------|----------|
| Phase 1: CSS Variables | XL | 2-3 days |
| Phase 2: Shared Components | M | 1 day |
| Phase 3: Inline Style Cleanup | L | 1-2 days |
| Phase 4: Accessibility | M | 1 day |
| Phase 5: Polish | S | 0.5 day |
| **Total** | | **5-7 days** |

**Quick Wins (today):** 5 items, ~30 min total
