# Batch 1 Theme Fix Log

**Branch:** `fix/theme-p0-breakages`  
**Date:** 2026-07-17  
**Scope:** Bootstrap `.dropdown-menu` dark mode + `.btn-close` inversion  

---

## Fixes Applied

### Fix 1: Bootstrap `.dropdown-menu` Dark Override

**File:** `static/css/base.css`  
**Added after scrollbar fix block:**

```css
/* Bootstrap dropdowns */
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
[data-theme="dark"] .dropdown-item.active,
[data-theme="dark"] .dropdown-item:active {
    background-color: var(--color-primary) !important;
    color: white !important;
}
[data-theme="dark"] .dropdown-divider {
    border-color: var(--border-color) !important;
}
[data-theme="dark"] .dropdown-header {
    color: var(--text-secondary) !important;
}
```

**Why direct properties (not `--bs-dropdown-*`):** The project uses custom `[data-theme="dark"]` instead of Bootstrap native `data-bs-theme="dark"`. Bootstrap's `--bs-dropdown-*` variables only take effect when `data-bs-theme` is set. Therefore, direct property overrides with `!important` are used.

### Fix 2: Bootstrap `.btn-close` Inversion

**File:** `static/css/base.css`

```css
/* Bootstrap close button */
[data-theme="dark"] .btn-close {
    filter: invert(1) grayscale(100%) brightness(200%);
}
```

**Why filter approach:** The project has both Bootstrap `.btn-close` elements (in `base.html` alert) and custom `.btn-close` classes (in `servers.html`, `monitoring.html` modals). The filter approach covers all of them without touching HTML. The alternative `--btn-close-color` variable only works for Bootstrap's native component.

**Custom `.btn-close` classes:** `servers.css` and `monitoring.css` already style custom `.btn-close` with `color: var(--text-secondary)`. They remain unaffected by this filter and continue to work in both modes.

---

## Verification

| Check | Result |
|---|---|
| `.dropdown-menu` dark bg override exists | ✅ PASS |
| `.dropdown-item` dark text override exists | ✅ PASS |
| `.dropdown-item` hover override exists | ✅ PASS |
| `.dropdown-divider` override exists | ✅ PASS |
| `.dropdown-header` override exists | ✅ PASS |
| `.btn-close` invert filter exists | ✅ PASS |

---

## Files Modified

- `static/css/base.css`

---

## Notes

- No HTML templates were modified.
- No `data-bs-theme` attribute was added — project continues using custom `[data-theme="dark"]`.
- Custom `.btn-close` classes in `servers.css` / `monitoring.css` remain unchanged and functional.
