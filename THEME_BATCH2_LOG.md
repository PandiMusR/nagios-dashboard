# Batch 2 Theme Fix Log

**Branch:** `fix/theme-p0-breakages`  
**Date:** 2026-07-17  
**Scope:** P2 dark mode polish — text brightness, dashboard hex cleanup, print styles  

---

## Fixes Applied

### Fix 1 — Dark Mode `--text-primary` Brightness

**File:** `static/css/base.css`  
**Change:** `--text-primary` in `[data-theme="dark"]` from `#f1f5f9` to `#e2e8f0`

| Value | Hex | Contrast on `#0f172a` |
|---|---|---|
| Before | `#f1f5f9` | 16.30:1 |
| After | `#e2e8f0` | 14.48:1 |

Both values exceed WCAG AA 4.5:1. The new value reduces halation while remaining clearly readable.

---

### Fix 2 — Dashboard Hardcoded Hex Cleanup

**File:** `static/css/dashboard.css`  
**Change:** Replaced hardcoded `#eef2ff` in `.resource-item` gradient with `var(--color-primary-lighter)`.

| File:Line | Hardcoded Value | Replaced With |
|---|---|---|
| `static/css/dashboard.css:58` | `#eef2ff` | `var(--color-primary-lighter)` |

**Verification:** No hardcoded hex remains in `dashboard.css` or `dashboard.html`.

---

### Fix 3 — Add `@media print` Rules

**File:** `static/css/base.css`  
**Added:** Full `@media print` block at end of file that:
- Forces light theme variables for both `:root` and `[data-theme="dark"]`
- Hides non-essential UI (navbar, sidebar, theme toggle, modals, toasts)
- Sets white background + dark text
- Keeps table borders readable
- Preserves status badge colors (UP/DOWN/Warning/Unknown)
- Preserves stage badge colors (New/CS/Escalated/Watchlist/Resolved)
- Uses `print-color-adjust: exact` to ensure colors print

---

## Verification

| Check | Result |
|---|---|
| Dark `--text-primary` is `#e2e8f0` | ✅ PASS |
| `dashboard.css` has no hardcoded hex | ✅ PASS |
| `@media print` block exists | ✅ PASS |
| Print block overrides both `:root` and `[data-theme="dark"]` | ✅ PASS |
| Print block hides navbar/sidebar | ✅ PASS |
| Print block keeps status colors | ✅ PASS |

---

## Files Modified

- `static/css/base.css`
- `static/css/dashboard.css`
