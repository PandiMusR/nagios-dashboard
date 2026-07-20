# Nagios Dashboard — Theme Fix Plan

**Based on:** `THEME_AUDIT.md` (2026-07-17)  
**Status:** Plan only — do not implement yet  
**Total breakages triaged:** 18 (5 critical, 8 high, 5 medium)  

---

## Phase 1 — Triage

| # | Priority | Breakage Description | Effort | Fix Type | File:Line | Fix Summary |
|---|---|---|---|---|---|---|
| 1 | P0 | White flash on page load (FOWT) | S | JS Fix | `templates/base.html:12`, `static/js/app.js:14-19` | ✅ IMPLEMENTED 2026-07-17 — blocking script in `<head>` before CSS |
| 2 | P0 | `monitoring.css` label color inversion | S | CSS Variable | `static/css/monitoring.css:38,261` | ✅ IMPLEMENTED 2026-07-17 — `var(--bg-tertiary)` → `var(--text-secondary)` |
| 3 | P0 | `--text-muted` WCAG contrast failure | S | CSS Variable | `static/css/base.css:41` | ✅ IMPLEMENTED 2026-07-17 — `#6b7280` (light) / `#8a98aa` (dark) |
| 4 | P0 | `login.css` hardcoded gradient | S | CSS Variable | `static/css/login.css:9,158` | ✅ IMPLEMENTED 2026-07-17 — replaced with CSS variables |
| 5 | P1 | No `prefers-color-scheme` auto-detection | S | JS Fix | `templates/base.html`, `static/js/app.js` | ✅ IMPLEMENTED 2026-07-17 — included in blocking script |
| 6 | P1 | No cross-tab theme sync | S | JS Fix | `static/js/app.js` | ✅ IMPLEMENTED 2026-07-17 — `storage` event listener added |
| 7 | P1 | Bootstrap `.dropdown-menu` no dark override | S | CSS Variable | `static/css/base.css` | Add `[data-theme="dark"] .dropdown-menu` rule |
| 8 | P1 | Bootstrap `.btn-close` not inverted | S | CSS Variable | `static/css/base.css` | Add `[data-theme="dark"] .btn-close { filter: invert(1) }` |
| 9 | P2 | 69 hardcoded `rgba(0,0,0,...)` shadows across 12 CSS files | M | CSS Variable | `static/css/*.css` (12 files) | Replace with `var(--shadow-card)` etc. |
| 10 | P2 | Dashboard dark mode block uses 17 hardcoded hex | M | CSS Variable | `static/css/base.css:555-607` | Replace hardcoded dashboard colors with CSS variables |
| 11 | P2 | Dark mode `--text-primary` too bright for NOC | S | CSS Variable | `static/css/base.css:114` | Lower from `#f1f5f9` to `#e2e8f0` |
| 12 | P2 | No `@media print` rules — dark mode prints dark | S | CSS Variable | `static/css/base.css` | Add `@media print` to force light mode |
| 13 | P3 | `edit_config.html` inline `color: #333` | S | Inline Style Removal | `templates/edit_config.html:12` | Replace with `var(--text-primary)` |
| 14 | P3 | `global_settings.html` hardcoded yellow warning box | S | Inline Style Removal | `templates/global_settings.html:149` | Replace with `var(--alert-warning-bg)` / `var(--color-warning-light)` |
| 15 | P3 | `monitoring.css` hardcoded secondary button hover | S | CSS Variable | `static/css/monitoring.css:291` | Replace `#78716c` with `var(--color-gray)` |
| 16 | P3 | `global_settings.css` hardcoded info box background | S | CSS Variable | `static/css/global_settings.css:53` | Replace `#f0f9ff` with `var(--alert-info-bg)` |
| 17 | P3 | `setup.css` hardcoded page background + button | S | CSS Variable | `static/css/setup.css:8,66` | Replace `#f0f4f8` with `var(--bg-primary)`, `#2563eb` with `var(--color-info)` |
| 18 | P3 | `monitoring_settings.css` modal overlay hardcoded | S | CSS Variable | `static/css/monitoring_settings.css:202,213` | Replace `rgba(15, 23, 42, ...)` with `var(--modal-overlay)` |

**Triage notes:**
- P0 = visible breakage in current state (white flash, invisible labels, WCAG failure, hardcoded login gradient)
- P1 = breaks dark mode or accessibility but has a workaround (catch-all CSS partially covers some)
- P2 = systemic code-quality issues that become visible on close inspection (shadows, print, brightness)
- P3 = cosmetic inconsistencies / hardcoded values that should use variables

---

## Phase 2 — Fix Plan

### Group A: P0 Critical Fixes (~50 min total)

#### Fix 1: White Flash on Page Load

**Problem:** Theme is applied after first paint. User sees light background then it snaps to dark.

**Root cause:** `static/js/app.js` is loaded at the end of `<body>` (via `base.html:123`). The browser renders the page with default `:root` (light) colors before `initDarkMode()` can set `data-theme="dark"`.

**Fix:** Add a small, blocking `<script>` inside `<head>` BEFORE any CSS `<link>` tags. This script runs synchronously, reads `localStorage`, and sets the `data-theme` attribute on `<html>` before the CSSOM is constructed. The CSS then loads with the correct theme already active.

**Exact `<script>` block to add to `templates/base.html` (inside `<head>`, before any `<link>`):**

```html
<script>
    (function() {
        try {
            var theme = localStorage.getItem('theme');
            if (theme === 'dark' || (!theme && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
                document.documentElement.setAttribute('data-theme', 'dark');
            }
        } catch (e) {
            // localStorage or matchMedia unavailable — fall back to light
        }
    })();
</script>
```

**`<noscript>` fallback:**

```html
<noscript>
    <style>
        /* If JS is disabled, respect system preference via CSS only */
        @media (prefers-color-scheme: dark) {
            html { background-color: #0f172a; color: #f1f5f9; }
        }
    </style>
</noscript>
```

**Why blocking (not `defer` or `async`):**
- `defer`/`async` run after the HTML parser finishes and/or after the page has started rendering. By then, the CSS has already been applied with the default light theme.
- A plain inline `<script>` (no `defer`/`async`) blocks HTML parsing and executes immediately. Because it is placed BEFORE the CSS `<link>` tags, it sets `data-theme` before the browser even starts fetching the stylesheet, guaranteeing the correct theme on first paint.

**Verification:**
1. Set browser to dark mode via toggle
2. Reload page with DevTools Network throttling
3. Observe no white flash — background should render dark immediately

---

#### Fix 2: `monitoring.css` Label Color Inversion

**Problem:** Lines 38 and 261 use `var(--bg-tertiary)` for label text color. In dark mode `--bg-tertiary` is `#334155` (dark grey), making text nearly invisible on the dark card background (`#1e293b`).

**Before:**
```css
/* static/css/monitoring.css:38 */
.filter-group label {
    font-weight: 600;
    color: var(--bg-tertiary);
    margin-bottom: 0.5rem;
    font-size: 0.9rem;
}

/* static/css/monitoring.css:261 */
.form-group label {
    display: block;
    font-weight: 600;
    color: var(--bg-tertiary);
    margin-bottom: 0.5rem;
}
```

**After:**
```css
/* static/css/monitoring.css:38 */
.filter-group label {
    font-weight: 600;
    color: var(--text-secondary);
    margin-bottom: 0.5rem;
    font-size: 0.9rem;
}

/* static/css/monitoring.css:261 */
.form-group label {
    display: block;
    font-weight: 600;
    color: var(--text-secondary);
    margin-bottom: 0.5rem;
}
```

**Does this break light mode?** No. In light mode:
- `--bg-tertiary` = `#f1f5f9` (very light grey)
- `--text-secondary` = `#64748b` (medium slate grey)

The labels will change from an almost-white grey to a proper slate grey, which is the intended design. It improves readability in light mode too.

**Verification:**
1. Open `/monitoring/<category>` in dark mode
2. Inspect filter labels and modal form labels
3. Confirm text is `#94a3b8` (dark mode `--text-secondary`) and readable

---

#### Fix 3: `--text-muted` WCAG Contrast Failure

**Problem:** Current `--text-muted: #94a3b8` on white background yields 2.56:1 contrast ratio. WCAG AA requires ≥ 4.5:1 for normal text.

**Calculation:**
- Target: ≥ 4.5:1 against `#ffffff`
- `#6b7280` gives 4.83:1 — passes AA with margin
- Keep it "muted" by using the same value as `--color-gray` (`#6b7280`)

For dark mode, current `--text-muted: #64748b` on `#1e293b` yields 3.07:1 (fails AA). We need ≥ 4.5:1.
- `#8a98aa` gives 4.98:1 — passes AA
- This is darker than `--text-secondary` (`#94a3b8`) so it still feels muted

**New values:**
```css
:root {
    --text-muted: #6b7280;  /* was #94a3b8; 4.83:1 on white */
}

[data-theme="dark"] {
    --text-muted: #8a98aa;  /* was #64748b; 4.98:1 on #1e293b */
}
```

**Does it still feel muted?** Yes. In light mode it is slightly lighter than `--text-secondary` (`#64748b`), preserving the hierarchy. In dark mode it is slightly darker than `--text-secondary` (`#94a3b8`), also preserving hierarchy.

**Verification:**
1. Find any muted text (empty states, placeholders, hints)
2. Confirm contrast ratio ≥ 4.5:1 in both modes using DevTools contrast picker

---

#### Fix 4: `login.css` Hardcoded Gradient

**Problem:** Login page background and submit button use hardcoded `#667eea` → `#764ba2` gradient. It does not adapt to dark mode or brand color changes.

**Before:**
```css
/* static/css/login.css:9 */
body {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    /* ... */
}

/* static/css/login.css:158 */
.form-actions button {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    /* ... */
}
```

**After:**
```css
/* static/css/login.css:9 */
body {
    background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-primary-dark) 100%);
    /* ... */
}

/* static/css/login.css:158 */
.form-actions button {
    background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-primary-dark) 100%);
    /* ... */
}
```

**Dark mode values:** The login page is a standalone page without the navbar/sidebar. In dark mode, the gradient should remain recognizable but can be slightly desaturated. Since `--color-primary` dark value is `#818cf8` and `--color-primary-dark` dark value is `#6366f1`, the gradient becomes `#818cf8` → `#6366f1`, which is a lighter, more vibrant indigo. This is acceptable for a login page and maintains brand consistency.

**Alternative (if the dark gradient feels too bright):** Define login-specific variables in `base.css`:
```css
:root {
    --login-gradient-start: #667eea;
    --login-gradient-end: #764ba2;
}

[data-theme="dark"] {
    --login-gradient-start: #4f46e5;
    --login-gradient-end: #4338ca;
}
```
Then use `var(--login-gradient-start)` / `var(--login-gradient-end)` in `login.css`.

**Verification:**
1. Open `/login` in light mode — gradient should look identical
2. Open `/login` in dark mode — gradient should use brand indigo, not hardcoded purple
3. Change `--color-primary` in `base.css` and confirm login page follows

---

## Group B: Remaining Breakages (P1 + P2)

### Fix 5: Add `prefers-color-scheme` Auto-Detection

**Problem:** First visit always shows light mode. The dashboard ignores the OS dark/light preference.

**Fix:** Extend the blocking script from Fix 1 to check `matchMedia('(prefers-color-scheme: dark)')` when no `localStorage` preference exists.

**Priority order:**
```javascript
// 1. localStorage preference (manual override)
// 2. system preference
// 3. light default
```

**Exact code for `templates/base.html` `<head>`:**

```html
<script>
    (function() {
        try {
            var theme = localStorage.getItem('theme');
            if (theme === 'dark' ||
                (!theme && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
                document.documentElement.setAttribute('data-theme', 'dark');
            }
        } catch (e) {}
    })();
</script>
```

**Files to modify:** `templates/base.html`  
**Verification:**
1. Clear localStorage
2. Set OS to dark mode
3. Open dashboard — should render in dark mode immediately (no flash)
4. Set OS to light mode — should render in light mode

---

### Fix 6: Cross-Tab Theme Sync

**Problem:** Changing theme in one tab does not update other open tabs until reload.

**Fix:** Add a `storage` event listener in `static/js/app.js`.

**Exact code to add to `static/js/app.js` (after `initDarkMode()`):**

```javascript
window.addEventListener('storage', function(e) {
    if (e.key === 'theme') {
        if (e.newValue === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            updateDarkModeIcon(true);
        } else {
            document.documentElement.removeAttribute('data-theme');
            updateDarkModeIcon(false);
        }
    }
});
```

**Files to modify:** `static/js/app.js`  
**Verification:**
1. Open dashboard in two tabs
2. Toggle dark mode in Tab A
3. Tab B should update instantly without reload

---

### Fix 7: Bootstrap `.dropdown-menu` Dark Override

**Problem:** Bootstrap `.dropdown-menu` has `background-color: #fff` by default. In dark mode, dropdowns appear white.

**Fix:** Add to `static/css/base.css` inside the dark mode override block:

```css
[data-theme="dark"] .dropdown-menu {
    background-color: var(--bg-secondary) !important;
    border-color: var(--border-color) !important;
    color: var(--text-primary) !important;
}

[data-theme="dark"] .dropdown-item {
    color: var(--text-primary) !important;
}

[data-theme="dark"] .dropdown-item:hover,
[data-theme="dark"] .dropdown-item:focus {
    background-color: var(--bg-tertiary) !important;
    color: var(--text-primary) !important;
}

[data-theme="dark"] .dropdown-divider {
    border-color: var(--border-color) !important;
}
```

**Files to modify:** `static/css/base.css`  
**Verification:**
1. Open any page with a Bootstrap dropdown in dark mode
2. Confirm dropdown background is `#1e293b`, not white
3. Confirm hover state uses `--bg-tertiary`

---

### Fix 8: Bootstrap `.btn-close` Inversion

**Problem:** Bootstrap `.btn-close` uses a black SVG icon. In dark mode, it is invisible against dark backgrounds.

**Fix:** Add to `static/css/base.css`:

```css
[data-theme="dark"] .btn-close {
    filter: invert(1) grayscale(100%) brightness(200%);
}
```

**Alternative (preferred):** Use Bootstrap's `.btn-close-white` class on close buttons in dark mode. However, since templates are shared, the CSS filter approach is simpler and covers all close buttons automatically.

**Files to modify:** `static/css/base.css`  
**Verification:**
1. Open any modal or alert with a close button in dark mode
2. Confirm close icon is visible (white)

---

### Fix 9: Replace Hardcoded Shadows with CSS Variables

**Problem:** 69 hardcoded `rgba(0,0,0,...)` shadow values across 12 per-template CSS files. They don't adapt to dark mode and make maintenance difficult.

**Approach:**
1. Define reusable shadow variables in `base.css`:

```css
:root {
    --shadow-color: 0, 0, 0;
    --shadow-opacity-sm: 0.05;
    --shadow-opacity-md: 0.08;
    --shadow-opacity-lg: 0.12;
    --shadow-opacity-xl: 0.3;

    --shadow-card: 0 2px 8px rgba(var(--shadow-color), var(--shadow-opacity-sm));
    --shadow-card-hover: 0 12px 40px rgba(var(--shadow-color), var(--shadow-opacity-lg));
    --shadow-button: 0 6px 20px rgba(79, 70, 229, 0.3);
    --shadow-modal: 0 20px 60px rgba(var(--shadow-color), var(--shadow-opacity-xl));
}

[data-theme="dark"] {
    --shadow-opacity-sm: 0.2;
    --shadow-opacity-md: 0.3;
    --shadow-opacity-lg: 0.4;
    --shadow-opacity-xl: 0.5;
}
```

2. Batch-replace in per-template CSS files:

   - `box-shadow: 0 2px 8px rgba(0,0,0,0.06);` → `box-shadow: var(--shadow-card);`
   - `box-shadow: 0 12px 40px rgba(0,0,0,0.12);` → `box-shadow: var(--shadow-card-hover);`
   - `box-shadow: 0 6px 20px rgba(79, 70, 229, 0.3);` → `box-shadow: var(--shadow-button);`
   - `box-shadow: 0 20px 60px rgba(0,0,0,0.3);` → `box-shadow: var(--shadow-modal);`
   - Other brand-specific shadows (success, danger, info) can keep their color but should use a variable if reused often.

**Files to modify:** `static/css/activity_logs.css`, `dashboard.css`, `global_settings.css`, `host_manager.css`, `monitoring.css`, `monitoring_intens.css`, `monitoring_settings.css`, `nagios_view.css`, `servers.css`, `setup.css`, `stage_history.css`, `user_permissions.css`, `users.css`  
**Verification:**
1. Run a regex search for `rgba\(0,0,0` across all CSS files — should return 0 results
2. Visually inspect cards, modals, and buttons in both modes to ensure shadows still provide depth

---

### Fix 10: Dashboard Dark Mode Block — Replace Hardcoded Hex

**Problem:** `static/css/base.css:555-607` contains 17 hardcoded hex values for dashboard-specific dark mode overrides.

**Fix:** Replace with semantic CSS variables. Add to `base.css` `:root` and `[data-theme="dark"]`:

```css
:root {
    --dash-server-card-bg: var(--bg-secondary);
    --dash-resource-item-bg: linear-gradient(135deg, var(--bg-primary) 0%, var(--color-primary-lighter) 100%);
    --dash-status-up-bg: var(--alert-success-bg);
    --dash-status-down-bg: var(--alert-error-bg);
    --dash-status-warning-bg: var(--alert-warning-bg);
    --dash-status-unknown-bg: var(--bg-tertiary);
    --dash-btn-open-bg: var(--color-primary);
    --dash-spinner-border: var(--bg-tertiary);
    --dash-spinner-top: var(--color-secondary);
}

[data-theme="dark"] {
    --dash-server-card-bg: #1e2530;
    --dash-resource-item-bg: #111622;
    --dash-status-up-bg: #052e16;
    --dash-status-down-bg: #450a0a;
    --dash-status-warning-bg: #451a03;
    --dash-status-unknown-bg: #1e293b;
    --dash-btn-open-bg: #00a8e8;
    --dash-spinner-border: #475569;
    --dash-spinner-top: #00f2fe;
}
```

Then update the dashboard dark mode block to use these variables:

```css
[data-theme="dark"] .server-card {
    background: var(--dash-server-card-bg) !important;
    border: 1px solid var(--border-color) !important;
    box-shadow: var(--shadow-card) !important;
}

[data-theme="dark"] .resource-item {
    background: var(--dash-resource-item-bg) !important;
    border: 1px solid var(--border-color) !important;
}

[data-theme="dark"] .status-up {
    background: var(--dash-status-up-bg) !important;
    color: #ffffff !important;
    border: 1.5px solid var(--color-success) !important;
}

[data-theme="dark"] .status-down {
    background: var(--dash-status-down-bg) !important;
    color: #ffffff !important;
    border: 1.5px solid var(--color-danger) !important;
}

[data-theme="dark"] .status-warning {
    background: var(--dash-status-warning-bg) !important;
    color: #ffffff !important;
    border: 1.5px solid var(--color-warning) !important;
}

[data-theme="dark"] .status-unknown {
    background: var(--dash-status-unknown-bg) !important;
    color: var(--text-secondary) !important;
    border: 1.5px solid var(--border-color-alt) !important;
}

[data-theme="dark"] .btn-open {
    background: var(--dash-btn-open-bg) !important;
    color: white !important;
    border: none !important;
}

[data-theme="dark"] .loading-spinner {
    border-color: var(--dash-spinner-border) !important;
    border-top-color: var(--dash-spinner-top) !important;
}
```

**Files to modify:** `static/css/base.css`, `static/css/dashboard.css`  
**Verification:**
1. Open `/dashboard` in dark mode
2. Confirm server cards, resource items, status badges, and loading spinner render correctly
3. Search `base.css` for hardcoded hex in the dashboard block — should be 0

---

### Fix 11: Dark Mode `--text-primary` Too Bright

**Problem:** Dark mode `--text-primary` is `#f1f5f9` (~95% white). On OLED screens in dark NOC rooms, this causes halation and eye strain.

**Fix:** Lower to `#e2e8f0` (~87% white).

```css
[data-theme="dark"] {
    --text-primary: #e2e8f0;  /* was #f1f5f9 */
}
```

**Files to modify:** `static/css/base.css`  
**Verification:**
1. Open dashboard in dark mode
2. Text should still be clearly readable but slightly less harsh
3. Contrast ratio against `#1e293b` remains > 10:1

---

### Fix 12: Add `@media print` Rules

**Problem:** No print styles. Dark mode prints with dark background, wasting ink.

**Fix:** Add to `static/css/base.css`:

```css
@media print {
    html {
        background: #ffffff !important;
        color: #000000 !important;
    }

    body,
    .content,
    .card,
    .card-body,
    .section-card,
    .server-card,
    .table-section,
    .modal-content,
    .modal-password-content {
        background: #ffffff !important;
        color: #000000 !important;
        box-shadow: none !important;
    }

    .navbar,
    .sidebar,
    .burger,
    .btn-logout,
    .user-badge,
    #darkModeBtn {
        display: none !important;
    }

    .content {
        margin-left: 0 !important;
        margin-top: 0 !important;
    }
}
```

**Files to modify:** `static/css/base.css`  
**Verification:**
1. Open dashboard in dark mode
2. Use browser print preview (Ctrl+P / Cmd+P)
3. Confirm page renders with white background and black text

---

## Group C: Systemic Improvements

### Improvement 1: Add `prefers-color-scheme` Support

**Current state:** 0 usage. First visit always shows light mode.

**Fix:** Already covered in Fix 5 (blocking script). Additionally, add a CSS-only fallback for users with JS disabled:

```css
@media (prefers-color-scheme: dark) {
    html:not([data-theme]) {
        /* Pre-apply dark background before JS runs */
        background-color: #0f172a;
        color: #f1f5f9;
    }
}
```

This is a progressive enhancement: if JS is enabled, the blocking script sets `data-theme="dark"` and the full dark styles apply. If JS is disabled, at least the page background and text color match the OS preference.

**Files to modify:** `static/css/base.css`  
**Verification:**
1. Disable JavaScript in browser
2. Set OS to dark mode
3. Open dashboard — background should be dark even without JS

---

### Improvement 2: Refactor `--color-*-light` Variables

**Problem:** `--color-primary-light`, `--color-success-light`, `--color-purple-light`, `--color-warning-light` have inverted meaning in dark mode. They work for backgrounds but fail for text/borders.

**Fix options:**

**Option A (recommended):** Rename to semantic names that describe their role, not their lightness:
```css
:root {
    --color-primary-subtle: #e0e7ff;   /* was -light */
    --color-success-subtle: #86efac;    /* was -light */
    --color-purple-subtle: #d8b4fe;     /* was -light */
    --color-warning-subtle: #fde68a;    /* was -light */
}

[data-theme="dark"] {
    --color-primary-subtle: #312e81;
    --color-success-subtle: #064e3b;
    --color-purple-subtle: #3b0764;
    --color-warning-subtle: #78350f;
}
```

Then audit every usage and ensure `-subtle` is only used for backgrounds, never for text/border.

**Option B:** Keep names but add separate text-safe variables:
```css
:root {
    --color-purple-text: #7e22ce;
    --color-success-text: #10b981;
}

[data-theme="dark"] {
    --color-purple-text: #a78bfa;
    --color-success-text: #34d399;
}
```

**Recommendation:** Option A. It forces developers to think about semantic usage.

**Files to modify:** `static/css/base.css`, then grep all CSS files for `--color-*-light`  
**Verification:**
1. Replace all `--color-*-light` usages
2. Confirm no text/border uses a `-subtle` variable
3. Confirm stage badges have visible borders in dark mode

---

### Improvement 3: Standardize Shadow Variables

**Problem:** 69 hardcoded shadows. Already covered in Fix 9.

**Additional recommendation:** Consider using lighter shadows in dark mode by changing the shadow color base, not just opacity:

```css
[data-theme="dark"] {
    --shadow-color: 255, 255, 255;  /* white-ish shadows for dark mode */
    --shadow-opacity-sm: 0.05;
    --shadow-opacity-md: 0.08;
    --shadow-opacity-lg: 0.12;
    --shadow-opacity-xl: 0.2;
}
```

This makes shadows visible in dark mode (subtle white glow instead of invisible black). However, this is a design decision — test first.

---

### Improvement 4: Add Theme-Aware Focus Rings

**Problem:** Focus rings use hardcoded `rgba(79, 70, 229, 0.1)` in per-template CSS. In dark mode, they should use a lighter indigo.

**Fix:** Define `--focus-ring-color` variable:

```css
:root {
    --focus-ring-color: rgba(79, 70, 229, 0.1);
}

[data-theme="dark"] {
    --focus-ring-color: rgba(129, 140, 248, 0.2);
}
```

Then replace all `box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);` with `box-shadow: 0 0 0 3px var(--focus-ring-color);`.

**Files to modify:** `static/css/base.css`, all per-template CSS files with focus rings  
**Verification:**
1. Focus an input in light mode — ring is indigo
2. Focus an input in dark mode — ring is lighter indigo

---

### Improvement 5: Consider Bootstrap Native Dark Mode

**Problem:** Custom `data-theme` implementation requires many catch-all overrides and may miss Bootstrap components.

**Fix (future):** Migrate to Bootstrap's native `data-bs-theme="dark"`. This would:
- Remove the need for most catch-all `[data-theme="dark"]` rules
- Properly style dropdowns, modals, tooltips, toasts, forms
- Reduce CSS maintenance burden

**Migration path:**
1. Keep `data-theme="dark"` for custom CSS variables
2. Add `data-bs-theme="dark"` to `<html>` alongside `data-theme`
3. Remove redundant catch-all rules
4. Test every page thoroughly

**Effort:** Large (2-3 hours)  
**Recommendation:** Defer until after P0/P1/P2 fixes are stable.

---

## Implementation Order (Revised)

### Batch 1: Bootstrap Component Quick Wins (~20 min)
| # | Fix | Files |
|---|---|---|
| 7 | Bootstrap `.dropdown-menu` dark override | `static/css/base.css` |
| 8 | Bootstrap `.btn-close` inversion | `static/css/base.css` |

**Why first:** Same Bootstrap component family, visible impact in dark mode, low risk.

---

### Batch 2: Dark Mode Polish (~45 min)
| # | Fix | Files |
|---|---|---|
| 11 | Dark mode `--text-primary` too bright | `static/css/base.css` |
| 10 | Dashboard dark mode block hardcoded hex | `static/css/base.css`, `static/css/dashboard.css` |
| 12 | No `@media print` rules | `static/css/base.css` |

**Why together:** Three independent, single-file/simple changes. All improve dark mode quality without dependencies.

---

### Batch 3: Shadow System Standardization (~60-90 min)
| # | Fix | Files |
|---|---|---|
| 9 | 69 hardcoded `rgba(0,0,0,...)` shadows | 12 per-template CSS files |
| 17 (systemic) | Standardize shadow variables | `static/css/base.css` + 12 CSS files |

**Why combined:** Must be done together. Define shadow variables first, then replace 69 instances. Doing separately means scanning the same files twice.

---

### Batch 4: Per-File Hardcoded Cleanup (~30-45 min)
| # | Fix | Files |
|---|---|---|
| 13 | `edit_config.html` inline `color: #333` | `templates/edit_config.html` |
| 14 | `global_settings.html` hardcoded yellow warning box | `templates/global_settings.html` |
| 15 | `monitoring.css` hardcoded secondary button hover | `static/css/monitoring.css` |
| 16 | `global_settings.css` hardcoded info box background | `static/css/global_settings.css` |
| 17 | `setup.css` hardcoded page background + button | `static/css/setup.css` |
| 18 | `monitoring_settings.css` modal overlay hardcoded | `static/css/monitoring_settings.css` |

**Why after P2:** These are polish items. After Batch 2, dark mode is ~90% correct. Batch 4 cleans remaining hardcoded values.

---

### Batch 5: Systemic / Architectural Improvements (~2-3 hours)
| # | Improvement | Files |
|---|---|---|
| 1 (systemic) | CSS fallback for JS-disabled users | `static/css/base.css` |
| 2 (systemic) | Refactor `--color-*-light` variables | `static/css/base.css` + all CSS files |
| 4 (systemic) | Theme-aware focus rings | `static/css/base.css` + per-template CSS |
| 5 (systemic) | Bootstrap native dark mode migration | All templates + CSS |

**Why last:** These are improvements, not bug fixes. Can be deferred if deadline is tight. Highest risk of regression.

---

## Original Implementation Order (Archived)

For reference, the original plan was:
1. Sprint 1: P0 Critical (~50 min)
2. Sprint 2: P1 High-Impact (~45 min)
3. Sprint 3: P2 Systemic Cleanup (~90 min)
4. Sprint 4: P3 Polish (~30 min)
5. Sprint 5: Systemic Improvements (~2-3 hours)

The revised batch order above groups by dependency and visible impact.

**Total estimated effort:** ~4.5 hours for all breakages + ~3 hours for systemic improvements = **~7.5 hours total**.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Blocking script causes render delay | Low | Low | Script is < 1KB and runs synchronously before CSS; no network request |
| `--text-muted` change makes UI feel too dark | Medium | Low | Test on actual NOC monitors; easy to revert |
| Shadow variable replacement misses edge cases | Medium | Medium | Use regex search + visual regression on all pages |
| Dashboard dark block refactor breaks status colors | Medium | High | Test `/dashboard` thoroughly in both modes before deploy |
| Bootstrap native migration introduces regressions | High | High | Defer to separate sprint; test every page |
| Cross-tab sync conflicts with manual toggle | Low | Low | Storage event only fires in other tabs, not the originating tab |

---

## Verification Summary

After all fixes, run the verification checklist from `THEME_AUDIT.md`:

1. [ ] No white flash on page load in dark mode
2. [ ] All form labels readable in dark mode (monitoring page)
3. [ ] Muted text meets WCAG AA 4.5:1 in light mode
4. [ ] Login page has brand colors in dark mode
5. [ ] First visit on dark-mode OS shows dark mode
6. [ ] Theme change in Tab A reflects in Tab B
7. [ ] Bootstrap dropdown menus have dark background in dark mode
8. [ ] Close buttons visible in dark mode
9. [ ] Zero hardcoded `rgba(0,0,0,...)` shadows remain in per-template CSS
10. [ ] Dashboard dark mode block uses CSS variables, not hardcoded hex
11. [ ] Print preview shows light mode with readable text
12. [ ] Stage badges (watchlist, resolved) have visible borders in dark mode
13. [ ] Status UP count on dashboard cards is distinguishable


