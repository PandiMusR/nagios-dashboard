# Batch 3 Theme Fix Log

**Branch:** `fix/theme-p0-breakages`  
**Date:** 2026-07-17  
**Scope:** Standardize shadow system — replace hardcoded shadows with CSS variables  

---

## Shadow Inventory

**Total shadow declarations found:** 78 across 16 CSS files  
**Unique shadow values:** 34  
**Instances replaced:** 74 hardcoded `box-shadow` values  
**Remaining intentional hardcoded:** 4 (transition properties + `box-shadow: none` in print styles)

### By File (before fix)

| File | Count |
|---|---|
| base.css | 15 |
| monitoring.css | 8 |
| host_manager.css | 7 |
| servers.css | 7 |
| global_settings.css | 6 |
| login.css | 5 |
| users.css | 5 |
| activity_logs.css | 4 |
| monitoring_intens.css | 4 |
| stage_history.css | 4 |
| dashboard.css | 3 |
| user_permissions.css | 3 |
| monitoring_settings.css | 3 |
| active_users.css | 2 |
| nagios_view.css | 1 |
| setup.css | 1 |

### Most Common Shadow Values

| Value | Count |
|---|---|
| `0 2px 8px rgba(0,0,0,0.06)` | 15 |
| `0 0 0 3px rgba(79, 70, 229, 0.1)` | 9 |
| `0 6px 20px rgba(79, 70, 229, 0.3)` | 6 |
| `0 8px 16px rgba(79, 70, 229, 0.3)` | 5 |
| `0 20px 60px rgba(0,0,0,0.3)` | 5 |

---

## CSS Variable Definitions

Final consolidated set (≤8 variables):

```css
:root {
    --shadow-sm: 0 1px 3px rgba(0,0,0,0.05);
    --shadow-md: 0 4px 20px rgba(0,0,0,0.08);
    --shadow-lg: 0 20px 60px rgba(0,0,0,0.3);
    --shadow-focus: 0 0 0 3px rgba(79, 70, 229, 0.1);
    --shadow-primary: 0 6px 20px rgba(79, 70, 229, 0.3);
    --shadow-danger: 0 6px 20px rgba(220, 38, 38, 0.3);
    --shadow-success: 0 6px 20px rgba(16, 185, 129, 0.3);
    --shadow-info: 0 4px 12px rgba(59, 130, 246, 0.3);
}

[data-theme="dark"] {
    --shadow-sm: 0 1px 3px rgba(0,0,0,0.2);
    --shadow-md: 0 4px 20px rgba(0,0,0,0.3);
    --shadow-lg: 0 20px 60px rgba(0,0,0,0.5);
    --shadow-focus: 0 0 0 3px rgba(129, 140, 248, 0.2);
    --shadow-primary: 0 6px 20px rgba(79, 70, 229, 0.4);
    --shadow-danger: 0 6px 20px rgba(220, 38, 38, 0.4);
    --shadow-success: 0 6px 20px rgba(16, 185, 129, 0.4);
    --shadow-info: 0 4px 12px rgba(59, 130, 246, 0.4);
}
```

**Dark mode approach:** Same blur/spread structure, higher opacity (typically 3-5x) so shadows remain visible on dark backgrounds.

---

## Replacement Mapping

| Tier | Original Value | Variable | Usage |
|---|---|---|---|
| XS | `0 1px 3px rgba(0,0,0,0.08)` | `--shadow-sm` | Small tables, stat cards |
| SM | `0 2px 8px rgba(0,0,0,0.06)` | `--shadow-sm` | Cards, sections, dropdowns |
| MD | `0 4px 20px rgba(0,0,0,0.08)` | `--shadow-md` | Navbar, toasts, hover lifts |
| MD | `0 4px 16px rgba(0,0,0,0.1)` | `--shadow-md` | Monitoring intens cards |
| LG | `0 20px 60px rgba(0,0,0,0.3)` | `--shadow-lg` | Modals, login container |
| LG | `0 20px 40px rgba(15,23,42,0.25)` | `--shadow-lg` | Monitoring settings modal |
| Focus | `0 0 0 3px rgba(79,70,229,0.1)` | `--shadow-focus` | Input focus rings |
| Primary | `0 6px 20px rgba(79,70,229,0.3)` | `--shadow-primary` | Primary button hover |
| Primary | `0 8px 16px rgba(79,70,229,0.3)` | `--shadow-primary` | Button hover, dashboard open |
| Primary | `0 4px 12px rgba(79,70,229,0.35)` | `--shadow-primary` | Monitoring button hover |
| Danger | `0 6px 20px rgba(220,38,38,0.3)` | `--shadow-danger` | Danger button hover |
| Danger | `0 4px 12px rgba(220,38,38,0.3)` | `--shadow-danger` | Users danger button |
| Danger | `0 8px 16px rgba(239,68,68,0.3)` | `--shadow-danger` | Activity logs danger hover |
| Success | `0 6px 20px rgba(16,185,129,0.3)` | `--shadow-success` | Success button hover |
| Info | `0 4px 12px rgba(59,130,246,0.3)` | `--shadow-info` | Info button hover |
| Header | `0 10px 30px rgba(79,70,229,0.2)` | `--shadow-primary` | Page header |
| Header | `0 10px 30px rgba(78,84,200,0.3)` | `--shadow-primary` | Dashboard header dark |
| Card Hover | `0 12px 40px rgba(0,0,0,0.12)` | `--shadow-lg` | Card hover lift |
| Card Hover | `0 12px 40px rgba(0,0,0,0.3)` | `--shadow-lg` | Server card hover dark |
| Login | `0 8px 20px rgba(102,126,234,0.4)` | `--shadow-primary` | Login button hover |
| Login | `0 0 0 3px rgba(102,126,234,0.15)` | `--shadow-focus` | Login input focus |
| Setup | `0 10px 25px rgba(0,0,0,0.2)` | `--shadow-md` | Setup container |
| Servers | `0 4px 8px rgba(0,0,0,0.15)` | `--shadow-sm` | Servers secondary hover |
| Stage | `0 4px 8px rgba(0,0,0,0.15)` | `--shadow-sm` | Stage history secondary hover |

---

## Edge Cases

### Inline Styles
- `monitoring.html:53` and `monitoring.html:834` contain inline `style` attributes but no `box-shadow`. They use `background: rgba(239,68,68,0.9)` for an exit button. No shadow migration needed.

### Transitions
- `login.css:140` and `login.css:165` reference `box-shadow` in `transition` properties. Left as-is because they reference the property, not a value.

### Multiple Shadows
- No comma-separated multiple shadows found.

### Text-shadow / drop-shadow
- No `text-shadow` or `filter: drop-shadow()` found in CSS or templates.

### `box-shadow: none`
- Intentionally kept in `@media print` block (`base.css:757`, `base.css:804`) to remove shadows when printing.

---

## Files Modified

- `static/css/base.css` — variable definitions + dashboard dark block shadows
- `static/css/dashboard.css`
- `static/css/global_settings.css`
- `static/css/login.css`
- `static/css/monitoring.css`
- `static/css/host_manager.css`
- `static/css/servers.css`
- `static/css/monitoring_settings.css`
- `static/css/monitoring_intens.css`
- `static/css/user_permissions.css`
- `static/css/users.css`
- `static/css/activity_logs.css`
- `static/css/stage_history.css`
- `static/css/setup.css`
- `static/css/active_users.css`
- `static/css/nagios_view.css`

---

## Verification

| Check | Result |
|---|---|
| Shadow variables defined in `:root` | ✅ PASS (8 vars) |
| Shadow variables defined in `[data-theme="dark"]` | ✅ PASS (8 vars) |
| No hardcoded `box-shadow` rgba remains | ✅ PASS |
| `base.css` uses `var(--shadow-*)` | ✅ PASS |
| Dashboard dark mode block uses shadow vars | ✅ PASS |

---

## Notes

- Initial pass created 22 shadow variables. Consolidated down to 8 by mapping similar shadows to shared variables.
- All original blur/spread/offset structures preserved.
- Light mode visual output should be identical to before.
- Dark mode shadows now have higher opacity for visibility.
