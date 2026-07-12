# Nagios Dashboard — Action Plan

> Derived from `AUDIT_TRIAGE.md` and `AUDIT_REPORT.md`.  
> Branch strategy: one branch per phase (`audit/phase-1-security-p0`, `audit/phase-2-high-p1`, dst.)

---

## Phase 1: Critical Security Fixes (P0)

**Goal:** Tutup semua celah privilege escalation, hardcoded credentials, dan CSRF — bikin app minimal aman untuk production.

**Prerequisites:**
- [ ] Git branch `audit/phase-1-security-p0` dibuat dari `main`
- [ ] Backup `config/` directory: `cp -r config/ config.backup-$(date +%Y%m%d)/`
- [ ] Pastikan `LDAP_ADMIN_PASSWORD` environment variable sudah diset di dev & prod (sebelum deploy Task 1.2)
- [ ] Install Flask-WTF: `pip install flask-wtf` (untuk Task 1.5)

---

### Task 1.1 — Hapus hardcoded LDAP admin password default

| Item | Detail |
|---|---|
| **Files** | `services/config.py:19` |
| **Effort** | S (5 min) |
| **Triage** | #2 |

**Apa yang diubah:**
```
# BEFORE (line 19):
LDAP_ADMIN_PASSWORD = os.environ.get('LDAP_ADMIN_PASSWORD', 'admin')

# AFTER:
LDAP_ADMIN_PASSWORD = os.environ['LDAP_ADMIN_PASSWORD']
```
Hapus fallback `'admin'`. App akan crash saat startup jika env var tidak diset — ini BY DESIGN, lebih baik crash than insecure.

**Verification:**
```bash
# Test: tanpa env var, harus error
unset LDAP_ADMIN_PASSWORD
python3 -c "from services.config import LDAP_ADMIN_PASSWORD" 2>&1 | grep -q "KeyError" && echo "PASS"

# Test: dengan env var, harus ok
export LDAP_ADMIN_PASSWORD="secret123"
python3 -c "from services.config import LDAP_ADMIN_PASSWORD; print('PASS' if LDAP_ADMIN_PASSWORD == 'secret123' else 'FAIL')"
```

---

### Task 1.2 — Hapus fallback credentials `nagiosadmin:nagiosadmin`

| Item | Detail |
|---|---|
| **Files** | `proxy.py:67`, `blueprints/host_manager.py:165-166` |
| **Effort** | S (15 min) |
| **Triage** | #3 |

**Apa yang diubah di `proxy.py` (~line 67):**
Cari blok yang baca `nagios_creds_<server>.json`, lalu fallback ke `nagiosadmin:nagiosadmin`.  
Ganti: jika creds file tidak ada, **jangan return default credentials — return 401 Unauthorized.**

```python
# BEFORE (konseptual):
creds = load_creds(server) or {'username': 'nagiosadmin', 'password': 'nagiosadmin'}

# AFTER:
creds = load_creds(server)
if creds is None:
    return jsonify({'error': 'Credentials not configured'}), 401
```

**Apa yang diubah di `blueprints/host_manager.py` (~line 165-166):**
```python
# BEFORE:
username = 'nagiosadmin'
password = 'nagiosadmin'

# AFTER: baca dari encrypted creds file, return error jika tidak ada
creds = load_nagios_creds(server_name)
if not creds:
    return jsonify({'error': f'No credentials found for server {server_name}'}), 400
username = creds['username']
password = creds['password']
```

**Verification:**
```bash
# Hapus sementara creds file untuk satu server (jangan di prod!)
# Test proxy: curl -I http://localhost:<proxy_port>/nagios/ harus return 401
# Test host_manager: POST /host-manager/host-status/<server> harus return 400/401
```

---

### Task 1.3 — Buat decorator `@permission_required` untuk mencegah omission di masa depan

| Item | Detail |
|---|---|
| **Files** | `utils/permissions.py` (tambah fungsi) |
| **Effort** | S (15 min) |
| **Triage** | #1 (prerequisite) |

**Apa yang ditambahkan di `utils/permissions.py` setelah `check_permission()`:**
```python
from functools import wraps
from flask import abort

def permission_required(permission: str):
    """Decorator: require specific permission. Admin bypasses all checks."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'username' not in session:
                abort(401)
            if not check_permission(permission):
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator
```

**Verification:**
```bash
python3 -c "from utils.permissions import permission_required; print('PASS')"
```

---

### Task 1.4 — Tambah `check_permission()` ke 25+ route yang belum diproteksi

| Item | Detail |
|---|---|
| **Files** | `blueprints/servers.py`, `blueprints/monitoring_settings.py`, `blueprints/host_manager.py`, `blueprints/monitoring.py`, `blueprints/global_settings.py` |
| **Effort** | M (2-3 jam) |
| **Triage** | #1 |
| **Depends on** | Task 1.3 |

**Daftar lengkap route + permission yang harus ditambah:**

#### `blueprints/servers.py`
| Route (line) | Permission |
|---|---|
| `batch_start_servers` (155) | `servers` |
| `batch_restart_servers` (218) | `servers` |
| `batch_delete_servers` (237) | `servers` |
| `start_all_containers` (289) | `servers` |
| `start_all_proxies` (313) | `servers` |
| `start_all_servers` (347) | `servers` |
| `delete_server` (400) | `servers` |
| `restart_server` (417) | `servers` |
| `stop_server` (432) | `servers` |
| `edit_server_config` (447) | `servers` |
| `list_plugins` (487) | `servers` |
| `upload_plugin` (510) | `servers` |
| `delete_plugin` (539) | `servers` |
| `start_server` (557) | `servers` |
| `start_proxy` (572) | `servers` |
| `stop_proxy` (623) | `servers` |
| `restart_proxy` (642) | `servers` |

**Cara ubah:** Setelah blok `if 'username' not in session: return redirect(...)`, tambah:
```python
if not check_permission('servers'):
    abort(403)
```
Atau gunakan decorator `@permission_required('servers')`.

#### `blueprints/monitoring_settings.py`
| Route (line) | Permission |
|---|---|
| `edit_monitoring_category` (54) | `monitoring_settings` |
| `delete_monitoring_category` (140) | `monitoring_settings` |
| `map_server_to_category` (162) | `monitoring_settings` |
| `update_monitoring_config` (198) | `monitoring_settings` |
| `unmap_server_from_category` (346) | `monitoring_settings` |

#### `blueprints/host_manager.py`
| Route (line) | Permission |
|---|---|
| `backup_localhost_cfg` (32) | `host_manager` |
| `list_localhost_backups` (68) | `host_manager` |
| `restore_localhost_cfg` (94) | `host_manager` |
| `delete_localhost_backup` (120) | `host_manager` |
| `get_host_status_endpoint` (137) | `host_manager` |

#### `blueprints/monitoring.py`
| Route (line) | Permission |
|---|---|
| `acknowledge_host` (385) | `monitoring` |

#### `blueprints/global_settings.py`
| Route (line) | Permission |
|---|---|
| `get_activity_logs` (347) | `global_settings` |

**CATATAN UNTUK servers.py:** Route `add_server` (line 57) SUDAH punya `check_permission`. Route `servers` GET (line 16) SUDAH punya. Jangan disentuh.

**Verification untuk setiap file:**
```bash
grep -B5 "check_permission\|abort(403)" blueprints/servers.py | grep "def \|@.*route" | wc -l
# Harus return >= 22 (semua route handlers harus punya check)
```

**Manual smoke test:** Login sebagai user non-admin tanpa permission `servers`. Akses:
- `POST /servers/batch-start` → harus 403
- `POST /servers/delete/<name>` → harus 403
- `POST /monitoring-settings/edit-category` → harus 403

---

### Task 1.5 — Implement CSRF protection global

| Item | Detail |
|---|---|
| **Files** | `app.py`, `templates/base.html`, 18 templates dengan `<form>`, `blueprints/api.py` |
| **Effort** | M (2-3 jam) |
| **Triage** | #4 |

**Sub-task 1.5a: Setup Flask-WTF di `app.py`**
```python
# Tambah di import:
from flask_wtf.csrf import CSRFProtect

# Setelah app = Flask(__name__):
csrf = CSRFProtect(app)
```

**Sub-task 1.5b: Tambah `{{ csrf_token() }}` ke semua template dengan `<form>`**

Cari semua template yang punya `<form method="POST">`:
```bash
grep -rn '<form.*method="POST"' templates/ --include="*.html"
```

Untuk setiap template, tambah `{{ csrf_token() }}` sebagai element pertama di dalam `<form>`:
```html
<form method="POST" action="...">
    {{ csrf_token() }}
    <!-- existing fields -->
</form>
```

Template yang perlu diedit (perkiraan):
- `templates/servers.html`
- `templates/host_manager.html`
- `templates/monitoring.html`
- `templates/monitoring_settings.html`
- `templates/users.html`
- `templates/user_permissions.html`
- `templates/global_settings.html`
- `templates/setup.html`
- `templates/login.html`

**Sub-task 1.5c: Exempt API endpoints dari CSRF**

API endpoint di `blueprints/api.py` tidak pakai session-based auth (pakai API key), jadi harus exempt:
```python
from flask_wtf.csrf import CSRFProtect

# Di app.py, setelah csrf = CSRFProtect(app):
csrf.exempt(api_bp)
```

**Sub-task 1.5d: Handle AJAX POST endpoints**

Route yang dipanggil via `fetch()` dari JavaScript (misalnya set-stage, acknowledge) perlu CSRF token di header. Di `base.html`, tambah meta tag:
```html
<meta name="csrf-token" content="{{ csrf_token() }}">
```

Lalu di JavaScript yang melakukan fetch POST, tambah header:
```javascript
fetch(url, {
    method: 'POST',
    headers: {
        'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
})
```

**Verification:**
```bash
# Start Flask app
python3 app.py &
sleep 2

# Test: POST tanpa CSRF token harus return 400
curl -X POST http://localhost:5000/login -d "username=test&password=test" -s | grep -q "CSRF" && echo "PASS: CSRF enforced"

# Test: form GET dengan token
curl http://localhost:5000/login -s | grep -q "csrf_token" && echo "PASS: CSRF token in form"

kill %1
```

---

### Phase 1 Exit Criteria

- [ ] `LDAP_ADMIN_PASSWORD` env var required — app crash tanpa itu
- [ ] Tidak ada fallback `nagiosadmin:nagiosadmin` di `proxy.py` atau `host_manager.py`
- [ ] `permission_required` decorator exists dan importable
- [ ] Semua 25+ route di `servers.py`, `monitoring_settings.py`, `host_manager.py`, `monitoring.py`, `global_settings.py` punya `check_permission()`
- [ ] User tanpa permission `servers` tidak bisa start/stop/delete/restart container
- [ ] User tanpa permission `host_manager` tidak bisa backup/restore host config
- [ ] User tanpa permission `monitoring_settings` tidak bisa edit/delete category
- [ ] CSRF token ada di semua `<form>`
- [ ] POST tanpa CSRF token ditolak (400)
- [ ] App start normal, login/logout normal, monitoring data fetch normal
- [ ] Tidak ada regression di fungsionalitas existing

---

## Phase 2: High Priority Fixes (P1)

**Goal:** Enkripsi credential at-rest, tutup path traversal, validasi file upload, hardcoded username fix.

**Prerequisites:**
- [ ] Git branch `audit/phase-2-high-p1` dibuat dari `audit/phase-1-security-p0` (setelah Phase 1 merged)
- [ ] Phase 1 semua task verified

---

### Task 2.1 — Enkripsi password Nextcloud & Uptime Kuma di `global_config.json`

| Item | Detail |
|---|---|
| **Files** | `blueprints/global_settings.py:243-274` (update_nextcloud), `blueprints/global_settings.py:307-345` (update_uptime_kuma), `services/encryption.py` (existing) |
| **Effort** | S (30 min) |
| **Triage** | #5, #6 |

**Apa yang diubah:**

Di `update_nextcloud_config()` (~line 262):
```python
# BEFORE: nyimpan password plaintext
config['nextcloud_password'] = password

# AFTER: nyimpan encrypted
from services.encryption import encrypt_value
config['nextcloud_password'] = encrypt_value(password)
```

Di `update_uptime_kuma()` (~line 333):
```python
# BEFORE:
config['password'] = password

# AFTER:
config['password'] = encrypt_value(password)
```

Saat READ (di `nextcloud.py` dan `uptime_kuma.py`), decrypt dulu:
```python
from services.encryption import decrypt_value
password = decrypt_value(config.get('password', ''))
```

**MIGRASI DATA EXISTING:** Buat script satu kali untuk enkripsi existing plaintext password di `config/global_config.json`:
```python
# migrate_encrypt_global_config.py
from services.config import GLOBAL_CONFIG_PATH
from services.encryption import encrypt_value, decrypt_value
import json

with open(GLOBAL_CONFIG_PATH) as f:
    config = json.load(f)

if config.get('nextcloud_password') and not config['nextcloud_password'].startswith('__ENC__'):
    config['nextcloud_password'] = encrypt_value(config['nextcloud_password'])
if config.get('password') and not config['password'].startswith('__ENC__'):
    config['password'] = encrypt_value(config['password'])

with open(GLOBAL_CONFIG_PATH, 'w') as f:
    json.dump(config, f, indent=2)
```

**Verification:**
```bash
# Setelah migrasi, cek isi global_config.json
cat config/global_config.json | grep -E "password|nextcloud_password"
# Harus start dengan "__ENC__"

# Test: Monitoring Intens tetap bisa konek ke Uptime Kuma
# Test: Backup ke Nextcloud tetap jalan
```

---

### Task 2.2 — Fix `tar.extractall()` path traversal

| Item | Detail |
|---|---|
| **Files** | `blueprints/global_settings.py:161` |
| **Effort** | S (10 min) |
| **Triage** | #7 |

**Apa yang diubah:**

Python 3.12+ approach (dev server runs 3.12):
```python
# BEFORE:
tar.extractall('/tmp/restore_temp')

# AFTER (Python 3.12+):
tar.extractall('/tmp/restore_temp', filter='data')
```

Jika harus kompatibel dengan Python 3.8 (prod Alpine mungkin 3.8), fallback manual:
```python
# AFTER (compatible 3.8+):
import os
def safe_extract(tar, dest):
    for member in tar.getmembers():
        member_path = os.path.join(dest, member.name)
        if not os.path.realpath(member_path).startswith(os.path.realpath(dest) + os.sep):
            raise ValueError(f"Path traversal attempt: {member.name}")
    tar.extractall(dest)

safe_extract(tar, '/tmp/restore_temp')
```

Karena dev VPS pakai Python 3.12 (cek `python3 --version`), pakai `filter='data'` saja — lebih simpel.

**Verification:**
```bash
# Buat malicious tar untuk test
mkdir -p /tmp/test_evil
echo "evil" > /tmp/test_evil/hacked
tar -cf /tmp/test_evil.tar -C /tmp/test_evil hacked
# Manual: pastikan extractall() hanya extract ke /tmp/restore_temp, bukan ke /tmp/
```

---

### Task 2.3 — Fix hardcoded `'admin'` di Uptime Kuma login

| Item | Detail |
|---|---|
| **Files** | `blueprints/monitoring_intens.py:79` |
| **Effort** | S (5 min) |
| **Triage** | #8 |

**Apa yang diubah:**
```python
# BEFORE (line 79):
auth_data = {'username': 'admin', 'password': password}

# AFTER:
auth_data = {'username': config.get('username', 'admin'), 'password': password}
```

Cek juga apakah field `username` sudah ada di `global_config.json`. Jika belum, tambahkan default `'admin'` di form global_settings.html (tapi tetap BACA dari config, bukan hardcode).

**Verification:**
```bash
# Test: jika config.username = "admin2", login harus pakai "admin2"
# Manual test: login ke Monitoring Intens page, harus tetap bisa fetch data
```

---

### Task 2.4 — Whitelist extension untuk sound file upload

| Item | Detail |
|---|---|
| **Files** | `blueprints/monitoring_settings.py:239-247` |
| **Effort** | S (10 min) |
| **Triage** | #9 |

**Apa yang diubah di sekitar line 239-247:**

Cari `if 'alarm_sound' in request.files:` dan tambah validasi extension setelah `sound_file.filename`:
```python
ALLOWED_SOUND_EXTENSIONS = {'.wav', '.mp3', '.ogg', '.m4a', '.aac'}

if sound_file and sound_file.filename:
    ext = os.path.splitext(sound_file.filename)[1].lower()
    if ext not in ALLOWED_SOUND_EXTENSIONS:
        flash(f'Invalid sound file type. Allowed: {", ".join(ALLOWED_SOUND_EXTENSIONS)}', 'danger')
        return redirect(url_for('monitoring_settings.monitoring_settings'))
    # lanjut save
```

**Verification:**
```bash
# Upload file .php sebagai alarm sound → harus ditolak
# Upload file .mp3 → harus diterima
```

---

### Task 2.5 — `secure_filename()` untuk plugin upload

| Item | Detail |
|---|---|
| **Files** | `blueprints/servers.py:526` |
| **Effort** | S (10 min) |
| **Triage** | #10 |

**Apa yang diubah di `upload_plugin()`:**

```python
# BEFORE (sekitar line 526):
plugin_path = os.path.join(plugin_dir, plugin_file.filename)

# AFTER:
from werkzeug.utils import secure_filename
safe_name = secure_filename(plugin_file.filename)
if not safe_name:
    flash('Invalid filename', 'danger')
    return redirect(...)
plugin_path = os.path.join(plugin_dir, safe_name)
```

**Verification:**
```bash
# Upload file dengan nama "../../../etc/passwd" → harus disimpan dengan nama aman
# Upload file normal → harus tetap jalan
```

---

### Task 2.6 — Validasi container name sebelum `rm -rf`

| Item | Detail |
|---|---|
| **Files** | `blueprints/servers.py:256` (batch-delete) |
| **Effort** | S (15 min) |
| **Triage** | #11 |

**Apa yang diubah:**
```python
# BEFORE (sekitar line 256):
for server in servers:
    subprocess.run(['rm', '-rf', f'/svr/{server}'])

# AFTER:
from services.shared_helpers import get_nagios_servers
valid_servers = get_nagios_servers()
for server in servers:
    if server not in valid_servers:
        flash(f'Unknown server: {server}', 'danger')
        continue
    subprocess.run(['rm', '-rf', f'/svr/{server}'])
```

**Verification:**
```bash
# Coba delete server dengan nama "../../etc" → harus ditolak
# Coba delete server yang valid → harus tetap jalan
```

---

### Phase 2 Exit Criteria

- [ ] Password di `global_config.json` terenkripsi (prefixed `__ENC__`)
- [ ] Restore backup tidak bisa path traversal
- [ ] Uptime Kuma login pakai username dari config, bukan hardcode `'admin'`
- [ ] Upload file `.php` sebagai alarm sound ditolak
- [ ] Upload file dengan nama `../../../` sebagai plugin ditolak
- [ ] Batch delete hanya bisa hapus container yang valid
- [ ] Semua fitur existing tetap jalan: backup, monitoring intens, alarm sound, plugin management

---

## Phase 3: Medium Priority Improvements (P2)

**Goal:** Perbaikan code quality, error handling, race condition fix, LDAP injection fix.

**Prerequisites:**
- [ ] Git branch `audit/phase-3-medium-p2` dibuat dari `audit/phase-2-high-p1`
- [ ] Phase 1 & 2 verified dan merged

---

### Task 3.1 — Hapus debug `print()` dan error disclosure

| Item | Detail |
|---|---|
| **Files** | `blueprints/dashboard.py:22`, `blueprints/dashboard.py:158-159`, `blueprints/servers.py:167` |
| **Effort** | S (15 min) |
| **Triage** | #19, #22 |

**Sub-task 3.1a: Hapus debug print**
```python
# DELETE line di dashboard.py:22:
print(f"DEBUG - Session: role={session.get('role')}, permissions={session.get('permissions')}")
```

**Sub-task 3.1b: Ganti `str(e)` di error responses**
```python
# BEFORE (dashboard.py:158-159):
except Exception as e:
    return {'success': False, 'error': str(e)}, 500

# AFTER:
except Exception as e:
    import logging
    logging.getLogger(__name__).error(f"Dashboard fetch error: {e}", exc_info=True)
    return {'success': False, 'error': 'Internal server error'}, 500
```

Lakukan yang sama untuk `servers.py:167`.

**Verification:**
```bash
# Cek tidak ada lagi "DEBUG - Session" di stdout saat akses /dashboard
# Force error (misal matikan Docker daemon), cek response tidak mengandung path filesystem
```

---

### Task 3.2 — Fix silent exception swallowing

| Item | Detail |
|---|---|
| **Files** | `blueprints/dashboard.py:154-155`, `services/ldap_service.py:72-83`, `blueprints/auth.py:107-118` |
| **Effort** | S (20 min) |
| **Triage** | #21, #24 |

**Sub-task 3.2a: ThreadPoolExecutor error logging (`dashboard.py:154-155`)**
```python
# BEFORE:
except Exception:
    continue

# AFTER:
import logging
logger = logging.getLogger(__name__)

# Di dalam for loop future:
except Exception as e:
    logger.warning(f"Container fetch failed: {e}")
    continue
```

**Sub-task 3.2b: LDAP setup errors (`ldap_service.py:72-83`)**
```python
# BEFORE:
except Exception:
    pass

# AFTER:
import logging
logger = logging.getLogger(__name__)

except Exception as e:
    logger.warning(f"LDAP OU/group creation failed (may already exist): {e}")
```

Sama untuk `auth.py:107-118` di `setup()` route.

**Verification:**
```bash
# Jalankan app dengan logging DEBUG
# Check log output — LDAP setup errors sekarang visible
```

---

### Task 3.3 — Fix LDAP injection via escape filter chars

| Item | Detail |
|---|---|
| **Files** | `services/ldap_service.py:173` |
| **Effort** | S (10 min) |
| **Triage** | #18 |

**Apa yang diubah:**
```python
# BEFORE:
search_filter = f'(member={user_dn})'

# AFTER:
from ldap3.utils.conv import escape_filter_chars
search_filter = f'(member={escape_filter_chars(user_dn)})'
```

**Verification:**
```bash
# Test dengan username mengandung karakter spesial LDAP: *, (, ), \
# Pastikan tidak menyebabkan injection atau error unexpected
```

---

### Task 3.4 — Hapus duplicate `get_nagios_servers` / `get_monitoring_categories`

| Item | Detail |
|---|---|
| **Files** | `blueprints/monitoring.py:22-82` |
| **Effort** | S (20 min) |
| **Triage** | #16 |

**Apa yang diubah:**

Di `blueprints/monitoring.py`, hapus dua fungsi lokal (lines 22-82), ganti dengan import:
```python
# DELETE:
def get_nagios_servers() -> list[str]:
    ...  # (lines 22-28)
def get_monitoring_categories() -> list[str]:
    ...  # (lines 29-82)

# ADD import di atas file:
from services.shared_helpers import get_nagios_servers, get_monitoring_categories
```

**Perhatian:** Fungsi `get_monitoring_categories()` di `monitoring.py` punya parsing logic yang lebih detail dari yang di `shared_helpers.py`. Sebelum hapus, PASTIKAN versi `shared_helpers.py` sudah mencakup semua behaviour yang dibutuhkan oleh `monitoring.py`. Jika tidak, merge logic-nya dulu ke `shared_helpers.py`, BARU hapus duplicate-nya.

**Verification:**
```bash
# Bandingkan output keduanya sebelum merge
python3 -c "
from blueprints.monitoring import get_monitoring_categories as local
from services.shared_helpers import get_monitoring_categories as shared
local_result = local()
shared_result = shared()
print('Local:', local_result)
print('Shared:', shared_result)
print('MATCH' if local_result == shared_result else 'MISMATCH - merge logic first')
"
```

---

### Task 3.5 — Fix race condition di stage tracking

| Item | Detail |
|---|---|
| **Files** | `blueprints/monitoring.py:171` |
| **Effort** | M (1 jam) |
| **Triage** | #17 |

**Apa yang diubah:**

Cari semua tempat di `_fetch_monitoring_hosts()` yang baca/tulis `host_stages` di luar context manager `host_stages_transaction()`. Bungkus dengan:
```python
from services.stage_service import host_stages_transaction

# BEFORE (baca di luar lock):
stages = load_host_stages()

# AFTER (baca dalam lock):
with host_stages_transaction() as stages:
    stages_data = dict(stages)  # copy untuk diproses
```

**Perhatian:** Ini sensitive — stage logic menentukan kapan host resolved/unresolved. Test menyeluruh diperlukan. Bikin test scenario dulu kalau bisa:
1. Dua request `/monitoring/<page>/data` concurrent
2. Pastikan stage update tidak ada yang hilang

**Verification:**
```bash
# Manual: buka dua browser tab ke page monitoring yang sama, refresh barengan, cek stage konsisten
# Structured: pakai ab (Apache Bench) atau wrk untuk send 10 concurrent requests, cek host_stages.json tidak corrupt
```

---

### Task 3.6 — Pre-save validation untuk Nagios config editor

| Item | Detail |
|---|---|
| **Files** | `blueprints/servers.py:456-459` |
| **Effort** | M (1 jam) |
| **Triage** | #23 |

**Apa yang diubah:**

Sebelum write ke file config, validasi dengan `nagios -v` di container:
```python
# BEFORE write:
with tempfile.NamedTemporaryFile(mode='w', suffix='.cfg') as tmp:
    tmp.write(config_content)
    tmp.flush()
    # Copy ke container & run nagios -v
    result = subprocess.run(
        ['docker', 'cp', tmp.name, f'{container_name}:/tmp/check.cfg'],
        capture_output=True
    )
    check = subprocess.run(
        ['docker', 'exec', container_name, '/opt/nagios/bin/nagios', '-v', '/tmp/check.cfg'],
        capture_output=True
    )
    if check.returncode != 0:
        flash(f'Config validation failed:\n{check.stderr.decode()}', 'danger')
        return redirect(...)
# Baru save ke actual config
```

**Verification:**
```bash
# Edit config dengan syntax yang salah → harus ditolak sebelum save
# Edit config dengan syntax benar → harus diterima
```

---

### Task 3.7 — Extract config-loading utility

| Item | Detail |
|---|---|
| **Files** | `services/shared_helpers.py` (tambah fungsi), semua blueprint yang load JSON config |
| **Effort** | M (1.5 jam) |
| **Triage** | #20 |

**Apa yang ditambahkan di `services/shared_helpers.py`:**
```python
def load_json_config(path: str, default=None):
    """Load JSON config file with error handling. Returns default on failure."""
    import json
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError, PermissionError):
        pass
    return default if default is not None else {}
```

**Lalu ganti semua pattern ini:**
```python
try:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
except (json.JSONDecodeError, OSError):
    config = {}
```
...dengan:
```python
from services.shared_helpers import load_json_config
config = load_json_config(CONFIG_PATH, {})
```

File yang perlu di-update: `blueprints/global_settings.py:26-52`, `blueprints/monitoring_settings.py:26-42`, dan 6+ lokasi lainnya.

**Verification:**
```bash
# Hapus salah satu config file → app harus tetap start (pakai default)
# Config file corrupt (invalid JSON) → app harus tetap start (pakai default)
grep -r "except.*json.JSONDecodeError.*OSError" blueprints/ | wc -l
# Harus berkurang signifikan
```

---

### Task 3.8 — Extract duplicated host definition builder

| Item | Detail |
|---|---|
| **Files** | `services/nagios_config.py` (NEW), `blueprints/host_manager.py:313-335`, `blueprints/api.py:66-104` |
| **Effort** | M (1.5 jam) |
| **Triage** | #15 |

**Apa yang dibuat:**

File baru `services/nagios_config.py`:
```python
"""Nagios config generation utilities."""

def build_host_definition(host_name: str, alias: str, address: str, 
                         parents: str = '', use_template: str = 'generic-host') -> str:
    """Build Nagios 'define host' block."""
    ...

def build_service_definition(host_name: str, service_plugin: str, 
                            service_args: str = '') -> str:
    """Build Nagios 'define service' block."""
    ...
```

Lalu update import di `host_manager.py` dan `api.py` untuk pakai fungsi baru, hapus duplikasi.

**Verification:**
```bash
# Test: add host lewat host_manager → config harus sama dengan sebelumnya
# Test: add host lewat API → config harus sama dengan sebelumnya
python3 -c "
from services.nagios_config import build_host_definition
result = build_host_definition('test', 'Test Host', '192.168.1.1')
assert 'define host{' in result
assert 'host_name\ttest' in result
print('PASS')
"
```

---

### Task 3.9 — Connection pooling untuk Nagios CGI API

| Item | Detail |
|---|---|
| **Files** | `blueprints/dashboard.py:57-58`, `blueprints/monitoring.py:103-104`, `proxy.py` |
| **Effort** | L (4 jam) |
| **Triage** | #25 |

**Apa yang dibuat:**

File baru `services/http_client.py`:
```python
"""Shared HTTP session with connection pooling."""
import requests

_session = None

def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20,
            pool_maxsize=20,
            max_retries=1
        )
        _session.mount('http://', adapter)
        _session.mount('https://', adapter)
    return _session
```

Ganti semua `requests.get(url, ...)` dengan `get_session().get(url, ...)` di:
- `blueprints/dashboard.py` (di dalam `_fetch_container_stats`)
- `blueprints/monitoring.py` (di `_fetch_container_data`)
- `blueprints/host_manager.py` (di `get_host_status_endpoint`)

**JANGAN ubah `proxy.py`** — dia sudah pakai `requests.Session()` sendiri.

**Verification:**
```bash
# Benchmark: 100 request ke /dashboard/stats, catat latency sebelum/sesudah
# Pastikan tidak ada connection leak
```

---

### Phase 3 Exit Criteria

- [ ] Tidak ada `print()` debug di production path
- [ ] Error responses tidak leak internal info (`str(e)`)
- [ ] `except Exception: pass` diganti dengan `logger.warning(...)`
- [ ] LDAP filter di-escape
- [ ] `monitoring.py` pakai `get_nagios_servers` / `get_monitoring_categories` dari `shared_helpers`
- [ ] Stage mutation dibungkus `host_stages_transaction()`
- [ ] Config editor validasi syntax sebelum save
- [ ] Semua JSON config load pakai `load_json_config()` utility
- [ ] Host definition builder di-sentralisasi di `services/nagios_config.py`
- [ ] HTTP connection pooling aktif untuk semua Nagios API call
- [ ] Semua fitur existing tetap jalan (monitoring, dashboard stats, host manager)

---

## Phase 4: Low Priority Cleanup (P3)

**Goal:** Test coverage, CI/CD, dependency upgrade, code style alignment, housekeeping.

**Prerequisites:**
- [ ] Git branch `audit/phase-4-cleanup-p3` dibuat dari `audit/phase-3-medium-p2`
- [ ] Phase 1-3 verified dan merged

---

### Task 4.1 — Pin dependencies & upgrade requests

| Item | Detail |
|---|---|
| **Files** | `requirements.txt` |
| **Effort** | S (15 min) |
| **Triage** | #28, #31 |

**Apa yang diubah di `requirements.txt`:**
```
# BEFORE:
requests==2.31.0
cryptography>=41.0.0

# AFTER:
requests==2.32.3
cryptography==44.0.0
```

Jalankan `pip freeze > requirements.txt` setelah upgrade untuk pin semua dependency ke versi exact.

**Verification:**
```bash
pip install -r requirements.txt
python3 -c "import requests; print(requests.__version__)"
# Harus >= 2.32.0
python3 app.py &
sleep 2 && curl -s http://localhost:5000/health && kill %1
```

---

### Task 4.2 — Buat `.env.example`

| Item | Detail |
|---|---|
| **Files** | `.env.example` (NEW) |
| **Effort** | S (5 min) |
| **Triage** | #32 |

**Content:**
```bash
# Nagios Dashboard environment variables
# Copy this to .env and fill in your values

APP_PORT=5000
LDAP_ADMIN_PASSWORD=change-me
```

**Verification:**
```bash
test -f .env.example && echo "PASS"
```

---

### Task 4.3 — Hapus deprecated `*_old.html` templates

| Item | Detail |
|---|---|
| **Files** | `templates/global_settings_old.html`, `templates/host_manager_old.html`, `templates/monitoring_settings_old.html`, `templates/user_permissions_old.html`, `templates/users_old.html` |
| **Effort** | S (5 min) |
| **Triage** | #35 |

```bash
git rm templates/*_old.html
git commit -m "chore: remove deprecated _old.html templates"
```

**Verification:**
```bash
ls templates/*_old.html 2>&1 | grep -q "No such file" && echo "PASS"
```

---

### Task 4.4 — Hapus `TRENDS_DUMMY_GUIDE.md`

| Item | Detail |
|---|---|
| **Files** | `TRENDS_DUMMY_GUIDE.md` |
| **Effort** | S (2 min) |
| **Triage** | #36 |

```bash
git rm TRENDS_DUMMY_GUIDE.md
# Atau pindahkan ke docs/internal/ jika masih dibutuhkan
```

**Verification:**
```bash
test ! -f TRENDS_DUMMY_GUIDE.md && echo "PASS"
```

---

### Task 4.5 — Extract magic number `PROXY_PORT_OFFSET`

| Item | Detail |
|---|---|
| **Files** | `services/config.py` (tambah constant), `blueprints/servers.py` (ganti 8+ lokasi) |
| **Effort** | S (15 min) |
| **Triage** | #33 |

**Di `services/config.py`:**
```python
PROXY_PORT_OFFSET = 1000
```

**Di `blueprints/servers.py`**, ganti semua:
```python
proxy_port = 1000 + int(port)
# menjadi:
from services.config import PROXY_PORT_OFFSET
proxy_port = PROXY_PORT_OFFSET + int(port)
```

**Verification:**
```bash
grep "1000 + int" blueprints/servers.py | wc -l
# Harus 0
grep "PROXY_PORT_OFFSET" blueprints/servers.py | wc -l
# Harus >= 8
```

---

### Task 4.6 — Set up linting dengan ruff

| Item | Detail |
|---|---|
| **Files** | `pyproject.toml` (NEW), semua `*.py` (auto-fix) |
| **Effort** | M (1 jam) |
| **Triage** | #29, #30 |

**Sub-task 4.6a: Buat `pyproject.toml`:**
```toml
[tool.ruff]
line-length = 100
target-version = "py38"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "B", "SIM"]
ignore = ["E501"]

[tool.mypy]
python_version = "3.8"
ignore_missing_imports = true
```

**Sub-task 4.6b: Install & run ruff:**
```bash
pip install ruff mypy
ruff check --fix .
ruff format .
```

**Sub-task 4.6c: Fix remaining lint errors manual.**
Focus pada error yang impactful — jangan refactor hanya untuk satisfy linter.

**Verification:**
```bash
ruff check . && echo "PASS: no lint errors"
# mypy mungkin masih banyak error — target adalah 0 ERROR (warning ok untuk sekarang)
```

---

### Task 4.7 — Tulis unit tests untuk service layer

| Item | Detail |
|---|---|
| **Files** | `tests/__init__.py`, `tests/conftest.py`, `tests/test_encryption.py`, `tests/test_stage_service.py`, `tests/test_permissions.py` |
| **Effort** | M-L (4-6 jam) |
| **Triage** | #26 (partial) |

**Test files yang harus dibuat:**

`tests/conftest.py`:
```python
import pytest
import os
import tempfile
from app import create_app

@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-key'
    return app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def temp_config_dir():
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get('CONFIG_DIR')
        os.environ['CONFIG_DIR'] = tmp  # override kalau configurable
        yield tmp
        if old:
            os.environ['CONFIG_DIR'] = old
```

`tests/test_encryption.py` — test:
- `encrypt_value()` + `decrypt_value()` roundtrip
- `save_encrypted_json()` + `load_encrypted_json()` roundtrip
- Invalid encrypted string → exception handled

`tests/test_stage_service.py` — test:
- `load_host_stages()` dengan empty file
- `save_host_stages()` write + re-read
- `host_stages_transaction()` commit & rollback

`tests/test_permissions.py` — test:
- `check_permission()` untuk admin (selalu True)
- `check_permission()` untuk user dengan/tanpa permission
- `get_default_permissions()` struktur benar

**Verification:**
```bash
pip install pytest
python3 -m pytest tests/ -v
# Target: 20+ tests passing
```

---

### Task 4.8 — Buat GitHub Actions CI

| Item | Detail |
|---|---|
| **Files** | `.github/workflows/ci.yml` (NEW) |
| **Effort** | M (1 jam) |
| **Triage** | #27 |
| **Depends on** | Task 4.6, 4.7 |

**Content `.github/workflows/ci.yml`:**
```yaml
name: CI
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install ruff
      - run: ruff check .
      - run: ruff format --check .
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt pytest
      - run: python3 -m pytest tests/ -v
```

**Verification:**
- Push branch ke GitHub, check Actions tab — harus hijau.

---

### Task 4.9 — Fix sisa minor items

| # | Task | File(s) | Effort |
|---|---|---|---|
| 4.9a | Fix `APP_PORT` default di `config.py:7` dari `'5000'` ke `'80'` (sesuai AGENTS.md) | `services/config.py` | S |
| 4.9b | Standardize path construction ke `os.path.join()` | `ldap_service.py:13`, dll. | S |
| 4.9c | API docs: tambah docstring OpenAPI-compatible atau README API reference | `blueprints/api.py` | M |

---

### Phase 4 Exit Criteria

- [ ] `requirements.txt` semua pin ke exact version
- [ ] `requests>=2.32.0` (fix CVE-2024-35195)
- [ ] `.env.example` exists
- [ ] Tidak ada `*_old.html` templates di repo
- [ ] `TRENDS_DUMMY_GUIDE.md` dihapus
- [ ] `PROXY_PORT_OFFSET = 1000` constant di `config.py`
- [ ] `ruff check .` passing
- [ ] 20+ unit tests passing
- [ ] CI/CD pipeline aktif di GitHub Actions
- [ ] `APP_PORT` default konsisten dengan AGENTS.md

---

## Rollback Plan

### Per-task rollback

| Task | Rollback method |
|---|---|
| 1.1 (LDAP password) | Revert ke `os.environ.get('LDAP_ADMIN_PASSWORD', 'admin')`. Set env var di production. |
| 1.2 (nagiosadmin fallback) | Revert ke hardcoded fallback. Kembalikan creds file yang dihapus dari backup. |
| 1.3 (permission decorator) | Hapus decorator, revert import. |
| 1.4 (permission checks) | Revert seluruh file blueprint dari git (`git checkout -- blueprints/`). |
| 1.5 (CSRF) | Uninstall Flask-WTF, hapus `{{ csrf_token() }}`, revert `app.py` CSRF setup. |
| 2.1 (encrypt passwords) | Restore `global_config.json` dari backup (`config.backup-*`). |
| 2.2-2.6 (path traversal, upload) | Revert individual file dari git. |
| 3.x (code quality) | Revert per-file. Aman — tidak mengubah behaviour. |
| 4.x (cleanup) | Revert individual file. |

### Full rollback

Jika semua Phase 1 gagal di production:

1. SSH ke production server
2. Stop service: `rc-service nagios-dashboard stop`
3. Restore dari backup: `cp -r /svr/dashboard-nagios/config.backup-YYYYMMDD/* /svr/dashboard-nagios/config/`
4. Git revert: `cd /svr/dashboard-nagios && git checkout main`
5. Restart proxy daemons: jalankan script proxy restart
6. Start service: `rc-service nagios-dashboard start`
7. Health check: `curl http://localhost/health`

---

## Estimated Total Timeline

| Phase | Task Count | Total Effort | Target |
|---|---|---|---|
| Phase 1 (P0) | 5 | ~1 hari | Hari 1-2 |
| Phase 2 (P1) | 6 | ~3 jam | Hari 2-3 |
| Phase 3 (P2) | 9 | ~2-3 hari | Hari 3-6 |
| Phase 4 (P3) | 9 | ~2-3 hari | Hari 7-10 |
| **Total** | **29** | **~7-10 hari** | 2 minggu |

### Git branch strategy

```
main
  └── audit/phase-1-security-p0     (branch dari main, merge ke main setelah verified)
        └── audit/phase-2-high-p1   (branch dari phase-1, merge setelah verified)
              └── audit/phase-3-medium-p2  (branch dari phase-2)
                    └── audit/phase-4-cleanup-p3  (branch dari phase-3)
```

Satu branch per phase, merge bertahap. Setiap merge ke `main` harus melalui:
1. Code review (baca diff)
2. Test di dev VPS (`curl` smoke tests)
3. Deploy ke production via `deploy_from_dev.sh`
4. Health check production

**JANGAN skip Phase 1.** Tanpa permission check dan CSRF, app tidak aman bahkan untuk internal network.
