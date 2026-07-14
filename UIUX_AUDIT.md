# UI/UX Audit Report — Nagios Dashboard

**Auditor:** Hermes Agent (Automated)
**Date:** 2026-07-14
**Project:** `/root/apps/nagiosDashboard`
**Stack:** Flask + Jinja2, Bootstrap 5.3, Vanilla JS, Font Awesome 6.4, Inter font
**Audience:** NOC engineers (8+ hours/day, incident-driven use)

---

## Executive Summary

**Overall Score: 6.5 / 10**

### Top 3 Strengths
1. **Consistent visual language** — Every page shares the same gradient header (`#4f46e5 → #06b6d4`), rounded cards, and hover micro-interactions. The design system feels intentional despite being inline.
2. **Real-time monitoring UX** — Auto-refresh with visible countdown, toast notifications for DOWN/UP changes, and alarm sounds give NOC engineers situational awareness without manual polling.
3. **Dark mode infrastructure** — CSS variables are defined for both themes (base.html:11–82), JS toggle works (base.html:451–476), and comprehensive dark overrides exist (base.html:648–799). The foundation is solid.

### Top 3 Pain Points
1. **CSS variable system is a facade** — `var(--...)` is used only in `base.html` (37 occurrences). All 14 child templates hardcode hex colors (`background: white`, `color: #1e293b`). Dark mode will break on every content page when enabled.
2. **Zero accessibility** — 0 `aria-*` attributes, 0 `lang` attributes on `<html>` (except active_users.html), no viewport meta on base.html. Screen reader users cannot use this dashboard.
3. **Massive style duplication** — 18 `<style>` blocks across 17 templates, 321 inline `style=` attributes, 638 hardcoded hex color values. Each page re-defines `.btn-primary`, `.form-group`, `.section-card` with slightly different values.

---

## Phase 1: Screen Inventory

### Route → Template Mapping

| Route | Blueprint | Template | Purpose | Status |
|-------|-----------|----------|---------|--------|
| `/login` | auth.py:71 | login.html | Authentication | Primary |
| `/setup` | auth.py:146 | setup.html | First-time admin creation | One-time |
| `/dashboard` | dashboard.py:21 | dashboard.html | Server health overview | **Primary (home)** |
| `/monitoring/<page>` | monitoring.py:94 | monitoring.html | Host down/unreachable list | **Primary (ops)** |
| `/monitoring-intens` | monitoring_intens.py:23 | monitoring_intens.html | Uptime Kuma monitors | Primary |
| `/host-manager` | host_manager.py:278 | host_manager.html | Host CRUD + backup | Admin |
| `/nagios/<server>` | nagios_proxy.py:38 | nagios_view.html | Embedded Nagios UI | Primary |
| `/servers` | servers.py:54 | servers.html | Docker container mgmt | Admin |
| `/servers/edit-config/<name>` | servers.py:512 | edit_config.html | Config file editor | Admin |
| `/users` | users.py:41 | users.html | LDAP user management | Admin |
| `/user-permissions` | users.py:94 | user_permissions.html | Permission matrix | Admin |
| `/monitoring-settings` | monitoring_settings.py:47 | monitoring_settings.html | Alarm/category config | Admin |
| `/global-settings` | global_settings.py:61 | global_settings.html | System-wide config | Admin |
| `/stage-history` | auth.py:290 | stage_history.html | Stage change audit log | Audit |
| `/activity-logs` | auth.py:309 | activity_logs.html | System activity log | Audit |
| `/active-users` | auth.py:268 | active_users.html | Online user list | Admin |

### ASCII Sitemap

```
┌─────────────┐
│   /login    │──→ /dashboard (after auth)
└─────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  /dashboard (Home)                                      │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Sidebar                                          │    │
│  │  ├─ /monitoring/<category>  (dynamic submenu)   │    │
│  │  ├─ /monitoring-intens      (Uptime Kuma)       │    │
│  │  ├─ /host-manager           (Host CRUD)         │    │
│  │  ├─ /nagios/<server>        (iframe embed)      │    │
│  │  ├─ /servers                (Docker mgmt)       │    │
│  │  │   └─ /servers/edit-config/<name>             │    │
│  │  ├─ /users                  (LDAP users)        │    │
│  │  ├─ /user-permissions       (Permission matrix) │    │
│  │  ├─ /monitoring-settings    (Alarm config)      │    │
│  │  ├─ /global-settings        (System config)     │    │
│  │  └─ Audit                                       │    │
│  │      ├─ /stage-history      (Stage audit)       │    │
│  │      └─ /activity-logs      (Activity log)      │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

---

## Phase 2: Visual Consistency

### Color System

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| CSS variables defined in `:root` and `[data-theme="dark"]` — 37 var() usages | ✅ Positive | base.html:11–82 | Good foundation |
| **All 14 child templates hardcode hex colors instead of using CSS vars** | **Critical** | All child templates | Migrate hardcoded colors to `var(--text-primary)`, `var(--card-bg)`, etc. |
| `background: white` hardcoded in 12+ templates instead of `var(--card-bg)` | Major | servers.html:85, monitoring.html:39, users.html:27, host_manager.html:27, global_settings.html:28, monitoring_settings.html:29, etc. | Replace with `var(--card-bg)` |
| `color: #1e293b` hardcoded for headings in 10+ templates instead of `var(--text-primary)` | Major | servers.html:32, monitoring.html:89, users.html:34, host_manager.html:36, etc. | Replace with `var(--text-primary)` |
| `color: #64748b` hardcoded for secondary text in 12+ templates instead of `var(--text-secondary)` | Major | dashboard.html:101, monitoring.html:56, servers.html:179, etc. | Replace with `var(--text-secondary)` |
| `border: 1px solid #e2e8f0` hardcoded in 15+ templates instead of `var(--border-color)` | Major | servers.html:54, monitoring.html:61, users.html:57, etc. | Replace with `var(--border-color)` |
| `background: #f8fafc` for table headers hardcoded instead of `var(--table-header-bg)` | Minor | servers.html:130, monitoring.html:112, stage_history.html:97 | Replace with CSS var |
| Login page uses different gradient (`#667eea → #764ba2`) than dashboard (`#4f46e5 → #06b6d4`) | Minor | login.html:19 | Consistent brand, but two different primary colors |
| `edit_config.html` uses `#1e3a8a` and `#333` — completely different palette | Minor | edit_config.html:16,12 | Align with design system |
| `setup.html` uses `#3b82f6` as primary — different from `#4f46e5` | Minor | setup.html:62 | Align with design system |
| 321 inline `style=` attributes across all templates | Major | All templates | Extract to CSS classes |
| Top offenders: host_manager.html (99 inline styles), monitoring.html (73), monitoring_settings.html (39), servers.html (34) | Major | — | Prioritize refactoring these files |

### Typography

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| Inter font declared via Google Fonts CDN in base.html and login.html | ✅ Positive | base.html:9, login.html:9 | Good |
| `font-family: 'Inter', sans-serif` set on body in base.html | ✅ Positive | base.html:85 | Good |
| setup.html uses `font-family: Arial, sans-serif` — no Inter | Minor | setup.html:14 | Add Inter font import |
| active_users.html uses `font-family: 'Inter', -apple-system, sans-serif` but loads no Google Fonts | Minor | active_users.html:9 | Add font import or extend base.html |
| Font sizes consistent: 0.85rem (small), 0.9rem (body), 0.95rem (inputs), 1.75rem (h1), 1.25rem (h2) | ✅ Positive | All templates | Good scale |
| Header font size inconsistent: `2rem` on dashboard.html:15 vs `1.75rem` on all others | Minor | dashboard.html:15 | Standardize |

### Spacing & Layout

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| CSS Grid used extensively for responsive layouts | ✅ Positive | dashboard.html:88,164, monitoring.html:46, servers.html:39, host_manager.html:133 | Good pattern |
| `padding: 2rem` consistent on section cards across templates | ✅ Positive | All templates | Good |
| `border-radius: 16px` consistent on cards/headers | ✅ Positive | All templates | Good |
| `margin-bottom: 2rem` consistent between sections | ✅ Positive | All templates | Good |
| `gap: 1.5rem` consistent in grid layouts | ✅ Positive | All templates | Good |
| Base.html has extra closing `</div>` at line 446 — potential DOM nesting issue | Minor | base.html:446 | Verify template structure |

### Component Reuse

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| **Each page defines its own `.btn-primary` with different padding/sizing** | **Major** | servers.html:64, users.html:108, host_manager.html:47, global_settings.html:93, monitoring_settings.html:83, user_permissions.html:72 | Extract to base.html as shared utility classes |
| `.btn-sm` defined differently in monitoring.html:297 vs servers.html:108 vs host_manager.html:258 vs users.html:159 | Major | Multiple files | Unify in base.html |
| `.form-group` redefined in 8 templates with slight variations | Major | monitoring.html:272, servers.html:42, users.html:42, host_manager.html:103, global_settings.html:39, monitoring_settings.html:50, stage_history.html:31 | Move to base.html |
| `.section-card` redefined in 7 templates | Major | users.html:22, host_manager.html:23, global_settings.html:22, monitoring_settings.html:22, activity_logs.html:14, stage_history.html:14, user_permissions.html:22 | Move to base.html |
| `.modal` redefined in 5 templates with inconsistent styles | Major | monitoring.html:213, servers.html:182, user_permissions.html:87, host_manager.html:159, monitoring_settings.html:265 | Create shared modal in base.html |
| `.status-badge` defined in dashboard.html:127 AND monitoring.html:141 AND servers.html:153 — different styles | Major | 3 files | Unify in base.html |
| Page gradient header redefined in every template (same gradient, different class name) | Major | All child templates | Create `.page-header` in base.html |
| `@keyframes fadeIn` and `@keyframes slideUp` duplicated in 4 templates | Minor | dashboard.html:46, monitoring.html:328, servers.html:207, host_manager.html:207 | Move to base.html |

### Iconography

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| Font Awesome 6.4 loaded via CDN | ✅ Positive | base.html:8 | Good |
| Consistent use of `fas fa-*` (solid) icons throughout | ✅ Positive | All templates | Good |
| Emoji used for stage indicators (🔴🔵🟠🟣✅) — mixed with FA icons | Minor | monitoring.html:450–454, 794–799 | Consider using FA colored circles for consistency |

### Dark Mode

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| Dark mode toggle button is **commented out** | Major | base.html:349–353 | Uncomment when ready |
| Dark mode CSS exists as a "nuclear wildcard" override (150+ lines) using `!important` | Major | base.html:648–799 | Refactor to use CSS variables properly |
| **Dark mode will NOT work on child template content** because children hardcode light colors, not CSS vars | **Critical** | All child templates | Must migrate to CSS variables first |
| `[data-theme="dark"] .content *` forces ALL elements to `#1e293b` background — will break colored badges, status indicators | Major | base.html:656–665 | More targeted selectors needed |
| Dark mode overrides for dashboard cards are comprehensive | ✅ Positive | base.html:746–798 | Good attention to detail |

---

## Phase 3: Usability

### Information Hierarchy (Dashboard)

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| Dashboard shows server cards with CPU, Memory, Host/Service status counts | ✅ Positive | dashboard.html:180–296 | Good overview |
| DOWN hosts shown in red badges, UP in green — high contrast | ✅ Positive | dashboard.html:146–149, 248–260 | Good |
| **Dashboard has no global summary** — no total hosts down across all servers at top | Major | dashboard.html:180–196 | Add "Total: X hosts down" prominently at top |
| Auto-refresh countdown visible to user | ✅ Positive | dashboard.html:184–189 | Good |
| Last update timestamp shown | ✅ Positive | dashboard.html:188 | Good |
| **No "down since" duration on dashboard** — only on monitoring page | Minor | dashboard.html | Add duration to dashboard cards |

### Scanability

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| Monitoring page shows total_down count in header stat | ✅ Positive | monitoring.html:390–396 | Good |
| Monitoring page has filterable/sortable table with stage indicators | ✅ Positive | monitoring.html:464–493 | Good |
| **Dashboard cards don't highlight critical servers** — all cards look the same whether all hosts are UP or DOWN | Major | dashboard.html:225–286 | Add red border/glow for servers with DOWN hosts |
| Stage badges with emoji + color coding are highly scannable | ✅ Positive | monitoring.html:165–169 | Good |

### Navigation Clicks

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| Dashboard → Monitoring page: 1 click (sidebar or card "Open Nagios") | ✅ Positive | — | Good |
| **Monitoring → Acknowledge a host: 2 clicks** (click "Stage" button → select stage → submit) | ✅ Positive | monitoring.html:819 | Reasonable |
| **Batch acknowledge: 3 clicks** (select hosts → Batch Set Stage → select stage → submit) | ✅ Positive | monitoring.html:467 | Acceptable for batch ops |
| Sidebar submenu auto-expands for current page | ✅ Positive | base.html:495–504 | Good |
| **No keyboard shortcut for common actions** (e.g., refresh, acknowledge) | Minor | — | Add keyboard shortcuts for power users |

### Data Density

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| Dashboard server cards use generous padding (1.5rem) with resource grid | Minor | dashboard.html:38,93–96 | Consider a compact mode for NOC wall displays |
| Monitoring table rows use `padding: 1.25rem 1rem` — somewhat spacious | Minor | monitoring.html:138 | Consider tighter rows for more data on screen |
| **No "compact view" option** for high-density monitoring | Minor | — | Add toggle for compact/comfortable spacing |
| Host manager has excellent pagination (10/20/50/100/ALL) | ✅ Positive | host_manager.html:409–413 | Good |

### Loading States

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| Dashboard shows spinner while loading servers | ✅ Positive | dashboard.html:193–196 | Good |
| Monitoring table shows "Loading..." with spinner icon | ✅ Positive | monitoring.html:486–489 | Good |
| Monitoring Intens shows spinner during load | ✅ Positive | monitoring_intens.html:211–214 | Good |
| Servers page has full loading overlay for server creation | ✅ Positive | servers.html:537–544 | Good |
| **Host Manager table body is empty on initial load** — no loading indicator | Minor | host_manager.html:439–440 | Add loading state |
| Global settings backup list shows spinner | ✅ Positive | global_settings.html:292 | Good |

### Error Handling

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| Dashboard shows error message on fetch failure | ✅ Positive | dashboard.html:211–213 | Good |
| **Monitoring page only `console.error`s on fetch failure** — user sees nothing | Major | monitoring.html:660 | Show error toast/banner to user |
| **50 `alert()` calls across templates** for error/success feedback | Major | servers.html (14), global_settings.html (10), monitoring.html (8), host_manager.html (7), monitoring_settings.html (5), etc. | Replace with in-app toast notifications |
| 13 `confirm()` calls for destructive actions | ✅ Positive | Multiple files | Good for safety, but consider custom confirm modals |
| Monitoring Intens has robust error handling (HTTP errors, JSON parse errors, empty states) | ✅ Positive | monitoring_intens.html:222–267 | Excellent pattern — adopt elsewhere |

### Empty States

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| Dashboard: "No servers found" with icon | ✅ Positive | dashboard.html:221 | Good |
| Monitoring: "No hosts with issues found" | ✅ Positive | monitoring.html:763 | Good |
| Servers: "No servers found" with icon | ✅ Positive | servers.html:464–470 | Good |
| Users: "No users found" | ✅ Positive | users.html:331 | Good |
| Stage History: "Belum ada stage history" with icon | ✅ Positive | stage_history.html:189–192 | Good |
| Activity Logs: "Belum ada activity log" with icon | ✅ Positive | activity_logs.html:156–159 | Good |
| Monitoring Settings: "No categories found yet." with dashed border | ✅ Positive | monitoring_settings.html:466–469 | Good |
| **Mixed language** — some empty states in English, some in Indonesian | Minor | Multiple files | Standardize to one language |

---

## Phase 4: Responsive & Accessibility

### Responsive Design

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| 14 `@media` queries across templates (mostly `max-width: 768px`) | ✅ Positive | Multiple files | Good baseline |
| base.html collapses sidebar to 80px on mobile | ✅ Positive | base.html:330–335 | Good |
| Login page has `@media (min-width: 992px)` for branding section | ✅ Positive | login.html:41–45 | Good |
| Host Manager has `@media (max-width: 480px)` breakpoint | ✅ Positive | host_manager.html:321–369 | Good — rare 3-breakpoint approach |
| **Dashboard server grid doesn't break to single column below 380px** | Minor | dashboard.html:164 | Add smaller breakpoint |
| Monitoring table has `overflow-x: auto` wrapper | ✅ Positive | monitoring.html:469 | Good |
| **`<meta name="viewport">` missing from base.html** — mobile rendering may be inconsistent | Major | base.html:1–6 | Add viewport meta tag |
| **`<meta name="viewport">` missing from setup.html** | Minor | setup.html:1–4 | Add viewport meta |

### Accessibility

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| **0 `aria-*` attributes in entire codebase** | **Critical** | All templates | Add aria-label, aria-live, role attributes |
| **`<html>` tag has no `lang` attribute** in base.html, login.html, setup.html | Critical | base.html:2, login.html:2, setup.html:2 | Add `lang="en"` |
| Only active_users.html has `lang="en"` | ✅ Positive | active_users.html:2 | — |
| Login form has proper `<label for="...">` with matching `id` | ✅ Positive | login.html:287–293 | Good |
| **Many form inputs lack `<label for="...">` association** — labels exist but use `<label>` without `for` attribute | Major | servers.html:327,334, host_manager.html:398,407,417, monitoring.html:430,436,446,457 | Add `for` attributes |
| **Checkboxes in monitoring table have no accessible label** | Major | monitoring.html:473 | Add `aria-label="Select all"` and per-row labels |
| **Sidebar menu links use `<a>` without `role` for submenu toggles** | Minor | base.html:374,396,422 | Add `role="button"` and `aria-expanded` |
| Images have alt text | ✅ Positive | base.html:344, login.html:271 | Good |
| **Color-only status indicators** — DOWN/UP distinguished only by color + text, but text IS present | ✅ Positive | dashboard.html:248–260 | Acceptable (text provides non-color info) |
| **No focus indicators** on custom buttons (outline removed, no replacement) | Major | base.html:323–327 | Add visible focus styles |
| **No skip-to-content link** | Minor | — | Add for keyboard navigation |
| Password form labels are in **Indonesian** while rest of UI is English | Minor | base.html:614,622,627,632 | Standardize language |

---

## Phase 5: Performance

### External Dependencies (CDN)

| Dependency | File:Line | Size (approx) |
|-----------|-----------|---------------|
| Bootstrap 5.3 CSS | base.html:7 | ~190 KB |
| Font Awesome 6.4 CSS | base.html:8 | ~100 KB |
| Google Fonts (Inter, 6 weights) | base.html:9 | ~60 KB |
| Bootstrap 5.3 JS Bundle | base.html:448 | ~80 KB |
| **Total CDN payload** | — | **~430 KB** |

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| All CDN resources loaded on every page including login | Minor | base.html:7–9 | Login page loads Bootstrap/FA/Inter separately — OK |
| **No `loading="lazy"` on any resources** | Minor | — | Not critical for this payload size |
| **No `defer`/`async` on Bootstrap JS** | Minor | base.html:448 | Add `defer` for faster paint |
| Font Awesome loads ALL icons (~100KB) — only ~30 icons used | Minor | base.html:8 | Consider FA subset or SVG sprites |
| **No service worker or caching headers configured** (Flask default) | Minor | — | Add cache headers for static assets |

### Inline CSS/JS Duplication

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| **18 `<style>` blocks** across 17 templates | Major | All templates | Extract shared styles to static CSS file |
| **12 `<script>` blocks** across templates | Major | All templates | Extract to static JS files |
| base.html has 2 `<style>` blocks (lines 10–337 and 648–799) — 500+ lines of CSS | Major | base.html:10–337, 648–799 | Split into `base.css` and `dark-mode.css` |
| monitoring.html has ~370 lines of inline CSS + ~750 lines of inline JS | Major | monitoring.html:4–371, 627–1351 | Extract to `monitoring.css` and `monitoring.js` |
| servers.html has ~310 lines of inline CSS + ~350 lines of inline JS | Major | servers.html:4–314, 546–899 | Extract to static files |
| host_manager.html has ~370 lines of inline CSS + ~700 lines of inline JS | Major | host_manager.html:4–370, 501+ | Extract to static files |
| Dashboard template JS generates HTML via template literals — no XSS escaping | Minor | dashboard.html:225–286 | Use textContent or escape HTML |
| `edit_config.html` is the only template with no `<style>` block — uses base.html styles | ✅ Positive | edit_config.html | — but styles don't match (uses `#333`, `#ddd`) |

### Image Optimization

| Finding | Severity | File:Line | Recommendation |
|---------|----------|-----------|----------------|
| Only 1 image: `/static/assets/img/icon.png` (favicon + logo) | ✅ Positive | base.html:5, login.html:7 | Minimal image usage |
| No image dimensions specified (`width`/`height` attributes) | Minor | base.html:344, login.html:101 | Add dimensions to prevent layout shift |

---

## Priority Action Items (Sorted by Impact)

| # | Action | Impact | Effort | Files Affected |
|---|--------|--------|--------|----------------|
| 1 | **Migrate child templates from hardcoded colors to CSS variables** | 🔴 Critical | High | All 14 child templates |
| 2 | **Add `aria-*` attributes, `lang="en"`, `<label for>`, focus styles** | 🔴 Critical | Medium | All 17 templates |
| 3 | **Add `<meta name="viewport">` to base.html** | 🔴 Critical | Trivial | base.html:2 |
| 4 | **Extract shared CSS (`.btn-primary`, `.form-group`, `.section-card`, `.modal`, `.page-header`) to base.html or static CSS** | 🟠 Major | High | base.html + all child templates |
| 5 | **Replace `alert()` calls with toast notifications** (50 occurrences) | 🟠 Major | Medium | 8 templates |
| 6 | **Add error UI to monitoring page** (currently only console.error on fetch failure) | 🟠 Major | Low | monitoring.html:660 |
| 7 | **Add loading state to host manager table** | 🟡 Minor | Low | host_manager.html:439 |
| 8 | **Add global "total hosts down" summary to dashboard header** | 🟠 Major | Low | dashboard.html:180–196 |
| 9 | **Highlight critical servers on dashboard** (red border for servers with DOWN hosts) | 🟠 Major | Low | dashboard.html:225–286 |
| 10 | **Refactor dark mode from "nuclear wildcard" to CSS variable-based approach** | 🟠 Major | Medium | base.html:648–799 + all child templates |
| 11 | **Extract inline `<style>` and `<script>` blocks to static files** | 🟡 Minor | Medium | All templates |
| 12 | **Standardize language** (mixed Indonesian/English throughout) | 🟡 Minor | Low | base.html, monitoring.html, activity_logs.html, stage_history.html |
| 13 | **Uncomment dark mode toggle** (after completing items 1 and 10) | 🟡 Minor | Trivial | base.html:349–353 |
| 14 | **Add keyboard shortcuts for common NOC actions** | 🟡 Minor | Low | monitoring.html |
| 15 | **Consolidate page gradient header into single `.page-header` class in base.html** | 🟡 Minor | Low | base.html + all child templates |

---

## Summary Statistics

| Metric | Count |
|--------|-------|
| Total templates | 17 |
| Templates extending base.html | 13 |
| Standalone templates (login, setup, active_users) | 3 |
| Total inline `style=` attributes | 321 |
| Total hardcoded hex color values | 638 |
| `var(--...)` CSS variable usages | 37 (all in base.html only) |
| `<style>` blocks | 18 |
| `<script>` blocks | 12 |
| `alert()` calls | 50 |
| `confirm()` calls | 13 |
| `aria-*` attributes | 0 |
| `@media` queries | 14 |
| `lang` attributes on `<html>` | 1 / 4 pages |
| CDN dependencies | 4 (Bootstrap CSS/JS, FA, Google Fonts) |
| External images | 1 (icon.png) |
