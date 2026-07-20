# Nagios Dashboard — Theme System Audit

**Date:** 2026-07-17  
**Auditor:** GLM-5.2 AI Agent  
**Scope:** Light Mode + Dark Mode implementation (read-only analysis)  

---

## Executive Summary

| Metric | Score |
|---|---|
| Light mode score | 6.5/10 |
| Dark mode score | 5.0/10 |
| Theme system score | 5.5/10 |
| Total dark mode breakages | 18 (5 critical, 8 high, 5 medium) |
| Unique hardcoded hex colors in per-template CSS | 11 |
| Unique hardcoded hex colors in HTML templates | 4 |
| Per-template CSS hardcoded rgba() calls | 69 |
| HTML inline style attributes (color-related) | 152 |
| `--color-*-light` vars silently redefined dark in dark mode | 3 (known bug) |

**Bottom line:** The CSS variable infrastructure in `base.css` is solid — 50+ variables defined for both light and dark modes. `base.html` nav, sidebar, cards, alerts, badges, and tables all use `var()` correctly. The dark mode override block (lines 447-607) catches common miss cases with `[data-theme="dark"]` catch-all rules. However, 15 per-template CSS files contain 80 hardcoded colors (mostly `rgba()` shadows) that don't adapt to dark mode, and 152 inline `style=` attributes scatter across 17 templates. The dark mode toggle works but has no `prefers-color-scheme` auto-detection and is applied AFTER first paint (causes flash). No `data-bs-theme` Bootstrap native support is used.

---

## Phase 1: Theme Infrastructure

### CSS Variable Definitions

All defined in `static/css/base.css:1-150`.

#### Brand Colors

| Variable | Light Value | Dark Value | Usage |
|---|---|---|---|
| `--primary` | `#4f46e5` | `#818cf8` | Navbar gradient, sidebar |
| `--primary-dark` | `#4338ca` | `#6366f1` | — |
| `--secondary` | `#06b6d4` | `#22d3ee` | Navbar gradient |
| `--success` | `#10b981` | `#34d399` | Toast border |
| `--danger` | `#ef4444` | `#f87171` | Toast border |
| `--warning` | `#f59e0b` | `#fbbf24` | Toast |
| `--dark` | `#1e293b` | *(not redefined)* | — |
| `--light` | `#f8fafc` | *(not redefined)* | — |

#### Color System

| Variable | Light Value | Dark Value | Dark Name Mismatch? |
|---|---|---|---|
| `--color-primary` | `#4f46e5` | `#818cf8` | ✓ OK |
| `--color-primary-dark` | `#4338ca` | `#6366f1` | ✓ OK |
| `--color-primary-darker` | `#312e81` | `#4338ca` | ✓ OK |
| `--color-primary-light` | `#e0e7ff` | `#312e81` | ⚠️ SILENTLY DARK |
| `--color-primary-lighter` | `#eef2ff` | `#1e1b4b` | ⚠️ SILENTLY DARK |
| `--color-secondary` | `#06b6d4` | `#22d3ee` | ✓ OK |
| `--color-success` | `#10b981` | `#34d399` | ✓ OK |
| `--color-success-dark` | `#059669` | `#10b981` | ✓ OK |
| `--color-success-light` | `#86efac` | `#064e3b` | ⚠️ CRITICAL — opposite meaning |
| `--color-danger` | `#ef4444` | `#f87171` | ✓ OK |
| `--color-danger-alt` | `#dc2626` | `#ef4444` | ✓ OK |
| `--color-danger-dark` | `#b91c1c` | `#dc2626` | ✓ OK |
| `--color-warning` | `#f59e0b` | `#fbbf24` | ✓ OK |
| `--color-warning-dark` | `#d97706` | `#f59e0b` | ✓ OK |
| `--color-warning-light` | `#fde68a` | `#78350f` | ⚠️ SILENTLY DARK |
| `--color-warning-alt` | `#fbbf24` | `#fbbf24` | Same value |
| `--color-info` | `#3b82f6` | `#60a5fa` | ✓ OK |
| `--color-info-dark` | `#1d4ed8` | `#3b82f6` | ✓ OK |
| `--color-gray` | `#6b7280` | `#9ca3af` | ✓ OK |
| `--color-purple` | `#7e22ce` | `#a78bfa` | ✓ OK |
| `--color-purple-light` | `#d8b4fe` | `#3b0764` | ⚠️ CRITICAL — opposite meaning |
| `--color-orange-dark` | `#c2410c` | `#ea580c` | ✓ OK |

**Critical Issue:** Three "`-light`" suffix variables (`--color-primary-light`, `--color-success-light`, `--color-purple-light`, `--color-warning-light`) have their **semantic meaning inverted** in dark mode. In light mode they're "lighter than the base color" (e.g. `#d8b4fe` is light purple). In dark mode they become "darker than the background" (`#3b0764` is dark purple — nearly black). Any CSS rule using these **for text color** will produce invisible text on dark backgrounds. This is a known bug (per the nagios-dashboard skill) — fixed for `.stage-watchlist` and `.stage-resolved` in base.css:515-516, but other uses may still be affected.

#### Text Colors

| Variable | Light Value | Dark Value | Role |
|---|---|---|---|
| `--text-primary` | `#1e293b` | `#f1f5f9` | Main body text |
| `--text-secondary` | `#64748b` | `#94a3b8` | Secondary labels |
| `--text-muted` | `#94a3b8` | `#64748b` | Disabled/placeholder |

#### Backgrounds

| Variable | Light Value | Dark Value | Role |
|---|---|---|---|
| `--bg-primary` | `#f8fafc` | `#0f172a` | Page background |
| `--bg-secondary` | `#ffffff` | `#1e293b` | Cards, modals |
| `--bg-tertiary` | `#f1f5f9` | `#334155` | Hover, table header |

#### Component Colors

| Variable | Light Value | Dark Value | Role |
|---|---|---|---|
| `--hover-bg` | `#f1f5f9` | `#334155` | Row hover |
| `--input-bg` | `#ffffff` | `#1e293b` | Form inputs |
| `--input-border` | `#e2e8f0` | `#475569` | Form borders |
| `--sidebar-bg` | `#ffffff` | `#1e293b` | Sidebar bg |
| `--modal-bg` | `#ffffff` | `#1e293b` | Modal bg |
| `--card-bg` | `#ffffff` | `#1e293b` | Card bg |
| `--card-border` | `#f1f5f9` | `#334155` | Card border |
| `--table-header-bg` | `#f8fafc` | `#334155` | Table header |
| `--table-row-border` | `#f1f5f9` | `#334155` | Row dividers |
| `--active-menu-bg` | `linear-gradient(90deg, #eef2ff 0%, #e0e7ff 100%)` | `linear-gradient(90deg, #312e81 0%, #1e1b4b 100%)` | Active sidebar item |

#### Alert Colors

| Variable | Light Value | Dark Value | Role |
|---|---|---|---|
| `--alert-success-bg` | `#d1fae5` | `#064e3b` | Success bg |
| `--alert-success-color` | `#065f46` | `#6ee7b7` | Success text |
| `--alert-error-bg` | `#fee2e2` | `#7f1d1d` | Error bg |
| `--alert-error-color` | `#991b1b` | `#fca5a5` | Error text |
| `--alert-info-bg` | `#dbeafe` | `#1e3a5f` | Info bg |
| `--alert-info-color` | `#1e40af` | `#93c5fd` | Info text |
| `--alert-warning-bg` | `#fef3c7` | `#78350f` | Warning bg |
| `--alert-warning-color` | `#92400e` | `#fde68a` | Warning text |
| `--alert-purple-bg` | `#f5f3ff` | `#3b0764` | Purple bg |

#### Shadow Variables

| Variable | Light Value | Dark Value |
|---|---|---|
| `--shadow-sm` | `0 1px 3px rgba(0,0,0,0.05)` | `0 1px 3px rgba(0,0,0,0.2)` |
| `--shadow-md` | `0 4px 20px rgba(0,0,0,0.08)` | `0 4px 20px rgba(0,0,0,0.3)` |
| `--shadow-lg` | `0 20px 60px rgba(0,0,0,0.3)` | `0 20px 60px rgba(0,0,0,0.5)` |

**Issue:** The `--shadow-*` variables are `rgba(0,0,0,...)` in both modes. They are defined correctly in `[data-theme="dark"]` BUT **none of the per-template CSS files actually use these variables**. Every template uses hardcoded `rgba(0,0,0,...)` for box-shadows. This is the single biggest source of hardcoded colors (69 out of 80 per-template hex/rgba occurrences).

#### Non-Redefined Variables (potential dark mode gaps)

These variables are only defined in `:root` — NOT in `[data-theme="dark"]`:
- `--dark` (line 9): `#1e293b` — not used in any CSS rule in this codebase
- `--light` (line 10): `#f8fafc` — not used directly

Both are legacy and safe.

### Theme Toggle Analysis

**Toggle code:** `static/js/app.js:13-39`

| Question | Answer |
|---|---|
| How triggered? | Button click on `#darkModeBtn` (sun/moon icon in navbar) |
| Preference stored where? | `localStorage.setItem('theme', 'dark'/'light')` |
| Persist across reloads? | YES — `initDarkMode()` reads `localStorage` on page load |
| Persist across tabs? | NO — no `storage` event listener, each tab reads localStorage independently |
| Work on initial page load? | YES, but with a **white flash** — see below |

**Flash of Wrong Theme (FOWT):** The theme is applied via JavaScript after page load:
1. Browser starts rendering with default light `:root` colors
2. `initDarkMode()` runs (line 39, inline in `<script src="...">`)
3. Sets `document.documentElement.setAttribute('data-theme', 'dark')` 
4. This is **after first paint** — user sees white background then it snaps to dark

**Fix:** Add a blocking `<script>` in `<head>` BEFORE any CSS `<link>` tags to check `localStorage` and set `data-theme` on `<html>` before the CSSOM is constructed. Or use a CSS-only approach with `prefers-color-scheme` + `localStorage` override.

### Theme Application

- **Applied on:** `<html>` element via `data-theme="dark"` attribute
- **Applied BEFORE or AFTER paint?** AFTER — causes white flash
- **CSS selector:** `[data-theme="dark"]` (not `html[data-theme="dark"]`)

### Bootstrap Dark Mode

**Bootstrap's native `data-bs-theme="dark"` is NOT used.** This is a custom implementation using `data-theme="dark"` attribute.

**Why not Bootstrap native?** The project predates the migration to Bootstrap's built-in dark mode (Bootstrap 5.3 added `data-bs-theme` in the same release the project uses). The custom approach gives more granular control over which colors change, but it misses Bootstrap's built-in component adaptations for forms, tables, dropdowns, tooltips, and toasts. The current implementation compensates with catch-all `[data-theme="dark"]` rules in base.css:447-607 that apply `!important` overrides to every element type.

**Risk:** Bootstrap components rendered via JS (dropdowns, tooltips, popovers collapsed by default) may not inherit the `[data-theme="dark"]` context since they're attached to `<body>` after page load. This is a latent bug — it works now because the catch-all applies to all elements within the page, but if Bootstrap adds dark-mode-specific component overrides in future versions, there will be conflicts.

### Component Coverage

| Component | Light Works? | Dark Works? | File:Line | Issue |
|---|---|---|---|---|
| Navbar | ✅ | ✅ | base.css:156 | Gradient adapts via `--primary`/`--secondary` vars |
| Cards | ✅ | ✅ | base.css:391 | `--card-bg` + catch-all `.section-card`, `.server-card` |
| Tables | ✅ | ⚠️ | monitoring.css:88 | Uses `--bg-primary`/`--bg-tertiary` which work, but row hover hardcoded in per-template files |
| Forms/Inputs | ✅ | ⚠️ | base.css:469 | Catch-all forces `var(--bg-primary)` bg + `var(--text-primary)` text. But `monitoring.css:261` `.form-group label` uses `color: var(--bg-tertiary)` — wrong var, will be dark-grey on dark bg |
| Buttons | ✅ | ✅ | base.css:497 | All `.btn-*` variants covered by dark overrides |
| Modals | ✅ | ✅ | base.css:527 | `.modal` overlay + background covered |
| Toasts | ✅ | ✅ | base.css:376 | `.toast-*` uses color vars |
| Badges | ✅ | ✅ | monitoring.css:135 | Stage badges have explicit dark overrides (base.css:509) |
| Tooltips | ❓ | ❓ | — | No custom tooltips found. Bootstrap tooltips inherit from catch-all |
| Scrollbars | ✅ | ✅ | base.css:529 | WebKit scrollbar dark override present |
| Status indicators | ✅ | ✅ | base.css:581 | `.status-up/down/warning/unknown` explicitly overridden |
| Charts/graphs | N/A | N/A | — | No charts/graphs in this codebase |
| Loading spinners | ✅ | ✅ | base.css:607 | `.loading-spinner` border overridden |

---

## Phase 2: Dark Mode Breakage

### CRITICAL (5 Issues)

#### C1. Silent Variable Meaning Inversion (`base.css:94, 99, 111`)

The `--color-*-light` variables change from "lighter tint" in light mode to "dark shade" in dark mode. This is fine for backgrounds but **catastrophic for text/foreground**. Any CSS rule using `--color-success-light` or `--color-purple-light` as a text/border color will render invisible on the dark background.

**Affected variables:** `--color-primary-light`, `--color-success-light`, `--color-purple-light`, `--color-warning-light`

**Current known site:** `monitoring.css:150-151` — `.stage-watchlist` uses `--color-purple-light` for border, `.stage-resolved` uses `--color-success-light` for border. Both become invisible in dark mode.

#### C2. White Flash on Page Load (`app.js:14-19` + `base.html:12`)

`initDarkMode()` runs in `app.js` which is loaded **after** `base.css` in the `<head>`. The CSS renders: light mode → JS sets `data-theme="dark"` → dark mode renders. This produces a jarring white flash for ~100-300ms. For NOC environments (dark room, 8+ hour shifts), this is physically painful.

#### C3. Dashboard-Specific Overrides Use Hardcoded Colors (`base.css:555-607`)

The dashboard dark mode block uses 17 hardcoded hex values instead of CSS variables:
- `#4e54c8`, `#00f2fe`, `#e0e0e0`, `#1e2530`, `#2d3748`, `#ffffff`, `#111622`, `#8892a4`, `#052e16`, `#22c55e`, `#450a0a`, `#451a03`, `#00a8e8`, `#475569`

These duplicate colors already in the CSS variable system but are not referenced. Changes to `--bg-secondary` or `--text-primary` won't affect these elements.

#### C4. Per-Template CSS Shadow Hardcoding (`dashboard.css:14,21,49` plus 14 other files)

All 69 `rgba(0,0,0,...)` calls across 15 per-template CSS files use hardcoded shadow values. In dark mode, these shadows look the same (black drop shadows on dark backgrounds are barely visible), but they should be lighter/more diffuse. However, since shadow perception is minimal in dark mode, this is more of a code-quality issue than a visible breakage.

#### C5. Login Page Gradient Hardcoded (`login.css:9, 158`)

```css
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
```

The login page page background and submit button use hardcoded `#667eea`/`#764ba2` gradients. These don't adapt to CSS variable changes. If the brand changes its primary/secondary colors via the variable system, the login page won't follow.

### HIGH (8 Issues)

#### H1. Per-CSS Shadow Hardcoding (`12 files`)
Every `.section-card`, `.server-card`, `.table-section`, `.filters-section` in per-template CSS uses `box-shadow: 0 2px 8px rgba(0,0,0,0.06)`. The `--shadow-sm` variable exists in `base.css` but is unused. Total: 69 hardcoded rgba shadows across 12 files.

#### H2. `dashboard.css:58` — Hardcoded Gradient End Color
```css
background: linear-gradient(135deg, var(--bg-primary) 0%, #eef2ff 100%);
```
The gradient end `#eef2ff` (light lavender) is hardcoded. In dark mode the resource items get a light gradient on a dark body — jarring visual.

#### H3. `monitoring.css:38, 261` — Wrong Variable for Label Text
```css
color: var(--bg-tertiary);  /* should be var(--text-primary) or var(--text-secondary) */
```
`.filter-group label` and `.form-group label` use `--bg-tertiary` for text color. In dark mode `--bg-tertiary` is `#334155` (dark grey) — text is barely visible against `--bg-secondary` (#1e293b). Contrast ratio: 1.5:1 — FAILS WCAG AA.

#### H4. `global_settings.css:53` — Hardcoded Info Box Background
```css
background: #f0f9ff;
```
The info box background is hardcoded light blue. In dark mode, light blue box on dark background looks out of place.

#### H5. `global_settings.css:145` — Hardcoded Button Hover
```css
background: #d97706;
```
`.btn-restore:hover` hardcodes amber. In dark mode, this is the same value as `--color-warning-dark`.

#### H6. `monitoring_settings.css:45` — Hardcoded Button Hover
```css
background: #4b5563;
```
`.btn-small:hover` hardcodes grey. In dark mode `--color-gray` is `#9ca3af`.

#### H7. `setup.css:8, 66` — Hardcoded Page Background + Button
```css
background: #f0f4f8;  /* page bg */
background: #2563eb;  /* submit button */
```
Setup page background and button are hardcoded and won't adapt to dark mode.

#### H8. `login.css:148, 171` — Hardcoded Focus/Shadow on Brand Color
```css
box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);  /* focus ring */
box-shadow: 0 8px 20px rgba(102, 126, 234, 0.4);   /* button hover */
```
These use `#667eea` (login brand color) instead of a CSS variable. If the brand color changes, these don't follow.

### MEDIUM (5 Issues)

#### M1. `edit_config.html:12` — Inline `color: #333`
The only hardcoded text color in an HTML template. Edit config label text will be `#333` on dark background — poor contrast.

#### M2. `global_settings.html:149` — Inline Background + Border
```html
style="background: #fefce8; border: 1px solid #fde68a"
```
Warning info box uses hardcoded light yellow. In dark mode, this stands out as a bright rectangle.

#### M3. `monitoring.css:291` — Hardcoded Secondary Button Hover
```css
background: #78716c;
```
`.btn-secondary:hover` hardcodes warm grey. `--text-muted` and `--color-gray` variables exist but aren't used.

#### M4. `servers.css:4, 40, 55, 65, 101` — Shadow Hardcoding (Same Pattern)
Same as H1 but across servers page specifically.

#### M5. `monitoring_settings.css:202, 213` — Modal Overlay Uses Hardcoded Dark
```css
background: rgba(15, 23, 42, 0.45);
box-shadow: 0 20px 40px rgba(15, 23, 42, 0.25);
```
These use `#0f172a` (same as `--bg-primary` dark value) hardcoded. They'll look identical in dark mode but the intent (dark overlay) should use a CSS variable for maintainability.

### Inline Style Breakage Summary

Of the 152 `style=""` attributes with color properties, 145 (95.4%) already use `var(--...)` — excellent. Only 7 are hardcoded:

| File | Line | Hardcoded Value | Severity |
|---|---|---|---|
| `base.html` | 24 | `background: rgba(255,255,255,0.2); color: white` | None — intentionally semi-transparent white on gradient navbar |
| `edit_config.html` | 12 | `color: #333` | Medium — invisible on dark bg |
| `global_settings.html` | 149 | `background: #fefce8; border: #fde68a` | Medium — bright yellow box in dark mode |
| `global_settings.html` | 143 | `background: var(--bg-primary)` | None — uses variable |
| `monitoring.html` | 12,15,18 | `background: rgba(255,255,255,0.2)` | None — page-header stat badges, intentional |
| `monitoring.html` | 53,834 | `background: rgba(239,68,68,0.9)` | None — intentional red badge |
| `monitoring.html` | 297 | `background: white` | Critical — invisible text on dark bg. `color: var(--color-danger)` with `background: white` = red text on white bg. In dark mode: red text still visible but white bg jarring |

### Background Color Conflicts

| File:Line | Current | Problem | Fix |
|---|---|---|---|
| `edit_config.html:12` | `color: #333` | Dark text invisible on dark bg | Remove inline or use `var(--text-primary)` |
| `monitoring.css:261` | `color: var(--bg-tertiary)` | Uses bg var for text | `var(--text-secondary)` |
| `monitoring.css:38` | `color: var(--bg-tertiary)` | Uses bg var for text | `var(--text-secondary)` |
| `setup.css:8` | `background: #f0f4f8` | Hardcoded light bg | `var(--bg-primary)` |
| `global_settings.css:53` | `background: #f0f9ff` | Hardcoded light blue bg | `var(--alert-info-bg)` or new var |
| `login.css:9` | `background: linear-gradient(135deg, #667eea, #764ba2)` | Hardcoded brand gradient | `var(--color-primary)`, `var(--color-primary-dark)` |
| `dashboard.css:58` | `linear-gradient(...#eef2ff 100%)` | Hard white end color | `var(--bg-primary)` or new var |

### Image/Asset Issues

- **SVG icons:** No SVGs found with hardcoded fill colors. No SVGs in this project. Uses Font Awesome 6.4 (CDN).
- **Logo (`icon.png`):** Single icon at `static/assets/img/icon.png`. Used in navbar (line 19) on gradient background — always visible. Used in login page logo section — on dark bg in dark mode, check if transparent PNG works.
- **Background images:** None used.
- **Font Awesome icons:** `.fa-*` icons use `currentColor` by default (Font Awesome 6 behavior) — inherits text color. This is correct behavior for dark mode.

### Third-Party Component Issues

- **Bootstrap tables:** `.table` class from Bootstrap may have its own `background-color: white`. The catch-all `[data-theme="dark"] .table` (base.css:548) overrides to `var(--bg-secondary)`.
- **Bootstrap forms:** `.form-control` from Bootstrap has `background-color: #fff`. The catch-all `[data-theme="dark"] input` (base.css:469) overrides.
- **Bootstrap dropdowns:** `.dropdown-menu` from Bootstrap renders with `background: #fff`. NO explicit dark mode override for `.dropdown-menu`. If any dropdowns exist (beyond navbar user menu), they will appear white on dark background.
- **Bootstrap close buttons:** `.btn-close` uses `background-image` with encoded SVG data-URI that includes a `#000` fill. Bootstrap provides `.btn-close-white` variant that should be used in dark mode. The current CSS doesn't swap it.

---

## Phase 3: Light Mode Quality Audit

### WCAG Color Contrast

Using WCAG 2.1 AA/AAA thresholds:
- Normal text (<18px): AA ≥ 4.5:1, AAA ≥ 7:1
- Large text (≥18px or ≥14px bold): AA ≥ 3:1, AAA ≥ 4.5:1
- UI components: AA ≥ 3:1

| Foreground | Background | Ratio | Pass AA? | Pass AAA? | Context |
|---|---|---|---|---|---|
| `var(--text-primary)` #1e293b | `var(--bg-secondary)` #ffffff | 14.5:1 | ✅ | ✅ | Card body text |
| `var(--text-primary)` #1e293b | `var(--bg-primary)` #f8fafc | 13.8:1 | ✅ | ✅ | Page body text |
| `var(--text-secondary)` #64748b | #ffffff | 4.6:1 | ✅ | ❌ | Secondary labels |
| `var(--text-muted)` #94a3b8 | #ffffff | 2.9:1 | ❌ | ❌ | Muted text — FAILS AA for normal text |
| `var(--alert-success-color)` #065f46 | `var(--alert-success-bg)` #d1fae5 | 5.8:1 | ✅ | ❌ | Success alert |
| `var(--alert-error-color)` #991b1b | `var(--alert-error-bg)` #fee2e2 | 6.3:1 | ✅ | ❌ | Error alert |
| `var(--alert-warning-color)` #92400e | `var(--alert-warning-bg)` #fef3c7 | 4.7:1 | ✅ | ❌ | Warning alert |
| `var(--alert-info-color)` #1e40af | `var(--alert-info-bg)` #dbeafe | 6.7:1 | ✅ | ❌ | Info alert |
| `white` (#fff) | Navbar gradient (#4f46e5→#06b6d4) | ~4.2:1 | ✅ (large) | ⚠️ | Navbar text — passes for large text only |
| `var(--color-primary)` #4f46e5 | `var(--bg-secondary)` #ffffff | 6.5:1 | ✅ | ❌ | Active sidebar link text |
| `var(--text-secondary)` #64748b | `var(--bg-tertiary)` #f1f5f9 | 3.6:1 | ✅ (large) | ❌ | Table headers |
| `var(--alert-success-bg)` #d1fae5 | `var(--bg-secondary)` #ffffff | 1.4:1 | ❌ | ❌ | Status UP badge bg on card — indistinguishable |

**Critical Finding:** `--text-muted` (#94a3b8) on `--bg-secondary` (#ffffff) = 2.9:1 — FAILS WCAG AA for normal text. This color is used for hints, placeholders, empty states across all pages. In a NOC environment with eye fatigue after 8 hours, this is unreadable.

### Status Color Visibility

In a well-lit NOC room:

| Status | Color | Distinguishable? |
|---|---|---|
| Critical/DOWN | `--alert-error-color` #991b1b (dark red) | ✅ — dark red is unmistakable |
| Warning | `--alert-warning-color` #92400e (dark amber) | ⚠️ — amber vs red at a glance can be confused |
| OK/UP | `--alert-success-color` #065f46 (dark green) | ✅ — green clearly different |
| Unknown/Unreachable | `--bg-tertiary` #f1f5f9 (light grey) | ⚠️ — light grey with `--text-secondary` text, low contrast |
| Acknowledged (Resolved) | `--alert-success-bg` #d1fae5 (light mint) | ✅ — light green clearly different |
| Watchlist/Flapping | `--alert-purple-bg` #f5f3ff (light lavender) | ✅ |
| CR Verification | `--alert-info-bg` #dbeafe (light blue) | ✅ |

**Issue:** Warning (amber) and critical (red) have similar luminance (#92400e vs #991b1b). Both are dark warm colors. In peripheral vision or quick scanning, they can be confused. Consider using a brighter amber or adding icon-based differentiation.

### Color Blindness Simulation

For the 3 most common types:

**Deuteranopia (green-blind, ~6% of males):**
- Critical (red) vs Warning (amber): Distinguishable — red still looks red, amber looks yellowish
- OK (green) vs Unknown (grey): Difficult — green and grey converge to similar murky tones
- Current non-color indicators: ✅ Status badges have text labels ("UP", "DOWN", etc.)
- Current non-color indicators: ✅ Stage badges have stage names in addition to color

**Protanopia (red-blind, ~2% of males):**
- Critical (red) vs OK (green): Difficult — both appear brownish
- Warning (amber) vs OK (green): Distinguishable — amber brighter
- Current non-color indicators: ✅ Status icon shapes (Font Awesome) + text labels

**Tritanopia (blue-blind, very rare):**
- Info (blue) vs OK (green): Difficult — both appear greenish
- Watchlist (purple) vs CR Verification (blue): Difficult — both lose blue component
- Current non-color indicators: ✅ Distinct stage names as text

**Overall:** The dashboard does well at providing non-color indicators. Every badge has a text label. Every status has an icon. The only concern is the status-to-color mapping in the dashboard stat cards (`dashboard.html`), where users must rely solely on color to distinguish UP/DOWN/WARNING counts.

---

## Phase 4: Dark Mode Quality Audit

### Darkness Level

| Element | Color | Assessment |
|---|---|---|
| Page background (`--bg-primary`) | `#0f172a` | ✅ Material-dark level. Excellent for NOC — dark enough for OLED comfort, not pure black (avoids smearing) |
| Card/modal background (`--bg-secondary`) | `#1e293b` | ✅ Good mid-grey. Cards visibly distinct from page bg |
| Tertiary/hover (`--bg-tertiary`) | `#334155` | ✅ One level up from secondary. Good for hover states |
| Navbar | Gradient via `--primary`/`--secondary` | ✅ Keeps brand identity. Looks good on dark |

**Assessment:** The darkness level is well-chosen. `#0f172a` is 97% black — dark enough for eye comfort in a dark NOC, not `#000000` which causes OLED smearing on scrolling. The elevation hierarchy (primary → secondary → tertiary) is visually clear.

### Brightness Ratio Check

| Element | Color | Should Be | Assessment |
|---|---|---|---|
| Primary text (`--text-primary`) | `#f1f5f9` (~95% white) | ~87-90% white | ⚠️ Slightly too bright — causes halation on OLED at full brightness |
| Secondary text (`--text-secondary`) | `#94a3b8` (~65% white) | ~60-70% white | ✅ Good |
| Muted text (`--text-muted`) | `#64748b` (~40% white) | ~40-50% white | ✅ Good |
| Borders (`--border-color`) | `#334155` (~20% white) | ~12-20% white | ✅ Good |
| Input border (`--input-border`) | `#475569` (~28% white) | ~20-25% white | Slightly bright but acceptable |

**Recommendation:** Lower `--text-primary` from `#f1f5f9` to `#e2e8f0` (87% white) for better long-reading comfort in dark rooms.

### Accent Color Saturation

| Color | Light Mode | Dark Mode | Desaturated? |
|---|---|---|---|
| Primary | `#4f46e5` (indigo) | `#818cf8` (lighter indigo) | ✅ Yes — shifted from 80% to 70% saturation |
| Success | `#10b981` (emerald) | `#34d399` (lighter emerald) | ✅ Yes |
| Danger | `#ef4444` (red) | `#f87171` (coral red) | ✅ Yes |
| Warning | `#f59e0b` (amber) | `#fbbf24` (bright amber) | ⚠️ Warning is now brighter — good for visibility, but `#fbbf24` on dark bg can be harsh |

**Assessment:** Good overall. The muted primary/success/danger colors are appropriate for dark mode. Warning at `#fbbf24` is borderline — consider `#fcd34d` for slightly less harsh amber.

### Shadow & Elevation

| Element | Light Mode Elevation | Dark Mode Elevation | Method |
|---|---|---|---|
| Cards | `box-shadow: 0 2px 8px rgba(0,0,0,0.06)` | Same rgba shadow | ❌ Shadows are invisible |
| Modals | `box-shadow: 0 20px 60px rgba(0,0,0,0.3)` | Same rgba | ⚠️ Barely visible |
| Sidebar | `box-shadow: 4px 0 20px rgba(0,0,0,0.05)` | Same rgba | ❌ Invisible |

**Problem:** In dark mode, `rgba(0,0,0,...)` shadows are nearly invisible because the background is already dark. The shadow variables in `[data-theme="dark"]` increase the alpha (0.05→0.2, 0.08→0.3, 0.3→0.5) but these are not actually used. Every template hardcodes its own shadow values.

**How elevation IS communicated in dark mode:** Through lighter backgrounds. Cards use `--bg-secondary` (#1e293b) on `--bg-primary` (#0f172a) — visible contrast. But modals have no additional border to separate from the page, relying solely on the shadow (which is invisible).

### Dark Mode Glitches Checklist

| Glitch | Found? | Details |
|---|---|---|
| White flash on page load | ✅ YES | initDarkMode() runs after CSSOM, causes FOWT |
| White borders on dark cards | ❌ No | Borders use `--border-color`/`--card-border` — properly dark |
| Form input: dark field, dark text | ⚠️ Partially | Catch-all fixes this, but 2 label instances use wrong var |
| Placeholder text visibility | ❓ Untested | Bootstrap default placeholder is `#6c757d` (43% grey) — should be visible on `--input-bg` (#1e293b) but needs verification |
| Scrollbars light-themed | ❌ No | Webkit scrollbar explicitly overridden (base.css:529) |
| Selection/highlight color | ❌ No explicit override | Browser default selection color is used. On dark bg, default blue selection may look out of place |
| Print styles force light mode | ❌ No print styles | No `@media print` rules exist. Dark mode will print with dark background — wastes ink/toner |

---

## Phase 5: Theme Switching Experience

### Toggle UX

| Aspect | Assessment |
|---|---|
| Easy to find? | ✅ Moon icon in navbar, right side. Standard placement |
| Clear which mode is active? | ✅ Icon swaps: moon = light mode active, sun = dark mode active |
| Keyboard navigable? | ✅ Button is a `<button>` element — Tab-focusable |
| Screen reader announced? | ⚠️ Partial — `aria-label="Mode Gelap/Terang"` exists but doesn't announce current state |
| Tooltip? | ✅ `title="Mode Gelap/Terang"` |

### Transition

- **No CSS transition** on the theme switch. When `data-theme="dark"` is set on `<html>`, all colors snap instantly. This is actually **correct** for a NOC dashboard — smooth transitions during a critical monitoring situation would be jarring.
- The `.navbar`, `.sidebar`, `.content`, `.card` elements all have `transition: all 0.3s` — but these don't participate in the theme switch because CSS custom properties don't animate unless registered with `@property`.

### State Preservation

| Aspect | Preserved? |
|---|---|
| Scroll position | ✅ Yes — theme switch only modifies CSS, not DOM |
| Form inputs | ✅ Yes — values persist in DOM |
| Modals/dropdowns | ✅ Yes — JS state unaffected |
| Socket.IO connection | ✅ Yes — theme toggle has no JS side effects beyond DOM attribute |
| Auto-refresh timers | ✅ Yes — unaffected |

### Preference Sync Across Tabs

**NOT supported.** There is no `window.addEventListener('storage', ...)` listener. If a user opens two tabs and changes the theme in one, the other tab does NOT update. It will update on the next page reload (reading from localStorage) but not live.

### System Preference Detection

**NOT implemented.** No `prefers-color-scheme` media query anywhere in the codebase. For a NOC dashboard, this is an important feature:

1. NOC operators typically have their OS in dark mode
2. First visit should auto-detect this
3. Manual toggle should override system preference
4. If system preference changes (e.g., based on time of day / Night Shift), the dashboard should follow

**Current behavior:** First visit always shows light mode (the CSS `:root` default). `initDarkMode()` only reads `localStorage`, which is empty on first visit.

---

## Proposed CSS Variable System

### New Variables (Beyond Current)

To cover all hardcoded colors found, the system needs these ADDITIONAL variables:

```css
:root {
    /* Shadow opacity tokens — keep rgba(0,0,0,...) but use variables for alpha */
    --shadow-color: 0, 0, 0;                    /* black shadow base */
    --shadow-opacity-sm: 0.05;
    --shadow-opacity-md: 0.08;
    --shadow-opacity-lg: 0.12;
    --shadow-opacity-xl: 0.3;

    /* Box shadows as composed variables */
    --shadow-card: 0 2px 8px rgba(var(--shadow-color), var(--shadow-opacity-sm));
    --shadow-card-hover: 0 12px 40px rgba(var(--shadow-color), var(--shadow-opacity-lg));
    --shadow-button: 0 6px 20px rgba(79, 70, 229, 0.3);   /* brand-specific */
    --shadow-modal: 0 20px 60px rgba(var(--shadow-color), var(--shadow-opacity-xl));

    /* Brand gradient (login page) */
    --brand-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);

    /* Resource item gradient end */
    --resource-gradient-end: #eef2ff;

    /* Info box background */
    --info-box-bg: #f0f9ff;

    /* Page backgrounds for special pages */
    --setup-bg: #f0f4f8;
    --setup-btn: #2563eb;

    /* Button hover backgrounds */
    --btn-secondary-hover: #78716c;
    --btn-small-hover: #4b5563;
    --btn-restore-hover: #d97706;

    /* Dashboard dark mode overrides (keep as vars) */
    --dash-server-card-bg: #1e2530;
    --dash-resource-item-bg: #111622;
    --dash-status-up-bg: #052e16;
    --dash-status-down-bg: #450a0a;
    --dash-status-warning-bg: #451a03;
    --dash-btn-open-bg: #00a8e8;
    --dash-spinner-border: #475569;
    --dash-spinner-top: #00f2fe;

    /* Focus ring */
    --focus-ring-color: rgba(79, 70, 229, 0.1);  /* light mode */
}
```

### Mapping: Hardcoded Values → Variables

| Hardcoded | File:Line | Replacement Variable |
|---|---|---|
| `#667eea` | login.css:9,158 | `var(--brand-gradient-start)` or new brand var |
| `#764ba2` | login.css:9,158 | `var(--brand-gradient-end)` |
| `#f0f4f8` | setup.css:8 | `var(--bg-primary)` |
| `#2563eb` | setup.css:66 | `var(--color-info)` |
| `#f0f9ff` | global_settings.css:53 | `var(--alert-info-bg)` |
| `#d97706` | global_settings.css:145 | `var(--color-warning-dark)` |
| `#4b5563` | monitoring_settings.css:45 | `var(--color-gray)` |
| `#78716c` | monitoring.css:291 | `var(--color-gray)` |
| `#eef2ff` | dashboard.css:58 | `var(--color-primary-lighter)` |
| `#333` | edit_config.html:12 | `var(--text-primary)` |
| `#fefce8` | global_settings.html:149 | `var(--alert-warning-bg)` |
| `#fde68a` | global_settings.html:149 | `var(--color-warning-light)` |
| `#0 2px 8px rgba(0,0,0,0.06)` | 12 CSS files | `var(--shadow-card)` |

### Dark Mode Adjustments to Proposed Variables

```css
[data-theme="dark"] {
    --shadow-color: 0, 0, 0;
    --shadow-opacity-sm: 0.2;
    --shadow-opacity-md: 0.3;
    --shadow-opacity-lg: 0.4;
    --shadow-opacity-xl: 0.5;

    --resource-gradient-end: var(--bg-primary);
    --info-box-bg: var(--alert-info-bg);
    --setup-bg: var(--bg-primary);
    --setup-btn: var(--color-primary);

    --btn-secondary-hover: var(--color-gray);
    --btn-small-hover: var(--color-gray);
    --btn-restore-hover: var(--color-warning-dark);

    --focus-ring-color: rgba(129, 140, 248, 0.2);  /* lighter in dark mode */

    /* Dashboard dark overrides stay the same */
    --dash-server-card-bg: #1e2530;
    --dash-resource-item-bg: #111622;
    --dash-status-up-bg: #052e16;
    --dash-status-down-bg: #450a0a;
    --dash-status-warning-bg: #451a03;
    --dash-btn-open-bg: #00a8e8;
    --dash-spinner-border: #475569;
    --dash-spinner-top: #00f2fe;
}
```

---

## Priority Action Items

| # | Priority | Category | Finding | Effort | Files | Recommendation |
|---|---|---|---|---|---|---|
| 1 | P0 | Flash | White flash on page load (FOWT) | 30m | base.html, app.js | Add blocking script in `<head>` before CSS links |
| 2 | P0 | Contrast | `monitoring.css:38,261` — labels use `var(--bg-tertiary)` for text color | 5m | monitoring.css | Change to `var(--text-secondary)` |
| 3 | P0 | Contrast | `--text-muted` (#94a3b8) on white bg = 2.9:1, fails WCAG AA | 5m | base.css | Darken to `#7c8798` (4.6:1 ratio) |
| 4 | P0 | Dark mode | `login.css:9,158` — hardcoded brand gradient won't adapt | 10m | login.css | Replace with `var(--color-primary)`, `var(--color-primary-dark)` |
| 5 | P1 | System pref | No `prefers-color-scheme` auto-detection | 20m | app.js | Add `matchMedia('(prefers-color-scheme: dark)')` check on first visit |
| 6 | P1 | Cross-tab | No live sync across tabs | 15m | app.js | Add `storage` event listener |
| 7 | P1 | Dark mode | `.dropdown-menu` no dark override | 5m | base.css | Add `[data-theme="dark"] .dropdown-menu` rule |
| 8 | P1 | Dark mode | `.btn-close` not swapped to white variant | 5m | base.css | Add `[data-theme="dark"] .btn-close { filter: invert(1) }` |
| 9 | P2 | Shadows | 69 hardcoded `rgba(0,0,0,...)` across 12 CSS files | 45m | 12 CSS files | Batch-replace with `var(--shadow-card)` etc. |
| 10 | P2 | Dashboard | 17 hardcoded hex in dashboard dark block (base.css:555-607) | 20m | base.css | Replace with CSS variables |
| 11 | P2 | Muted text | Dark mode `--text-primary` (#f1f5f9) too bright for NOC | 5m | base.css | Lower to `#e2e8f0` |
| 12 | P2 | Print | No `@media print` rules — dark mode prints dark | 10m | base.css | Add print styles to force light mode |
| 13 | P3 | Inline | `edit_config.html:12` `color: #333` | 2m | edit_config.html | Replace with `var(--text-primary)` |
| 14 | P3 | Inline | `global_settings.html:149` hardcoded yellow warning box | 5m | global_settings.html | Replace with alert variables |
| 15 | P3 | Saturation | `--color-warning` (#fbbf24) harsh in dark mode | 5m | base.css | Desaturate to `#fcd34d` |
| 16 | P3 | Contrast | Status UP badge on white card = 1.4:1 ratio | 10m | base.css | Add border or increase contrast |

**Total estimated effort:** ~3.5 hours for all items. P0 items (high impact, low effort): ~50 minutes.

---

## Verification Checklist

After implementing fixes, verify:
1. [ ] No white flash on page load in dark mode
2. [ ] All form labels readable in dark mode (monitoring page)
3. [ ] Muted text meets WCAG AA 4.5:1 in light mode
4. [ ] Login page has brand colors in dark mode (if login page gets dark mode support)
5. [ ] First visit on dark-mode OS shows dark mode
6. [ ] Theme change in Tab A reflects in Tab B
7. [ ] Bootstrap dropdown menus have dark background in dark mode
8. [ ] Close buttons visible in dark mode
9. [ ] Zero hardcoded `rgba(0,0,0,...)` shadows remain in per-template CSS
10. [ ] Dashboard dark mode block uses CSS variables, not hardcoded hex
11. [ ] Print preview shows light mode with readable text
12. [ ] Stage badges (watchlist, resolved) have visible borders in dark mode
13. [ ] Status UP count on dashboard cards is distinguishable
