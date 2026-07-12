# Nagios Trends Dummy Injection Guide

Panduan untuk membuat data Trends palsu di Nagios untuk keperluan demo. Teknik ini meng-inject log entries ke archive logs Nagios sehingga `trends.cgi` menampilkan history seolah-olah host sudah monitored selama periode tertentu.

---

## Cara Kerja Nagios Trends

`trends.cgi` membangun grafik timeline dari **2 sumber data**:

1. **Archive logs** (`/opt/nagios/var/archives/nagios-MM-DD-YYYY-00.log`)
   - `CURRENT HOST STATE: hostname;state;state_type;attempt;plugin_output` — snapshot semua host saat log rotation (tengah malam)
   - `HOST ALERT: hostname;state;state_type;attempt;plugin_output` — perubahan state terjadi di hari itu

2. **status.dat / retention.dat** — data state saat ini
   - `current_state` — 0=UP, 1=DOWN, 2=UNREACHABLE
   - `last_state_change` — epoch timestamp state terakhir berubah
   - `last_hard_state_change` — epoch timestamp hard state terakhir berubah

**Prinsip:** Log entries menentukan **history**, status.dat menentukan **state saat ini**.

---

## Prasyarat

- SSH access ke production server
- Docker sudo access (user `rif`)
- Nama container Nagios (misal: `Adiarsa`, `Bhome`)
- Nama host yang sudah ada di config Nagios

---

## Script Lengkap

Script Python berikut melakukan semua langkah sekaligus:
- Backup semua file sebelum edit
- Inject `CURRENT HOST STATE` ke archive logs
- Inject `HOST ALERT` untuk state transition
- Update `status.dat` dan `retention.dat`
- Backup disimpan di `/opt/nagios/var/*.bak`

### Skenario: UP lalu DOWN

Host UP dari awal log rotation, lalu DOWN di waktu tertentu, sampai sekarang.

```python
# Simpan sebagai inject_trends.py, jalankan di dalam container

import os, shutil

# ============================================================
# KONFIGURASI — SESUAIKAN
# ============================================================
HOST = "Nama Host Sesuai Config"        # persis seperti di host_name Nagios
STATE_CHANGE_EPOCH = 1782738963         # epoch saat host DOWN (gunakan converter)
ARCHIVE_DIR = "/opt/nagios/var/archives"

# Archive files yang perlu di-inject (sesuaikan tanggal)
ARCHIVE_FILES = [
    "nagios-06-30-2026-00.log",  # hari pertama UP → DOWN di hari ini
    "nagios-07-01-2026-00.log",  # hari berikutnya: DOWN terus
    "nagios-07-02-2026-00.log",
    "nagios-07-03-2026-00.log",
]
NAGIOS_LOG = "/opt/nagios/var/nagios.log"
# ============================================================

EXACT_MARKER = f"CURRENT HOST STATE: {HOST};"

def get_rotation_ts(filepath):
    """Ambil timestamp rotasi dari baris pertama log."""
    with open(filepath) as f:
        for line in f:
            if line.startswith("["):
                return line.split("]")[0].strip("[")
    return None

def inject_archive(filepath, is_first_day, rotation_ts):
    """Inject entries ke satu archive file."""
    with open(filepath) as f:
        lines = f.readlines()

    if any(EXACT_MARKER in line for line in lines):
        print(f"  SKIP (sudah ada): {os.path.basename(filepath)}")
        return

    last_idx = -1
    for i, line in enumerate(lines):
        if "CURRENT HOST STATE:" in line:
            last_idx = i

    if last_idx == -1:
        print(f"  SKIP (tidak ada block): {os.path.basename(filepath)}")
        return

    if is_first_day:
        # Hari pertama: UP di awal, DOWN alert di tengah hari
        up_line = f"[{rotation_ts}] CURRENT HOST STATE: {HOST};UP;HARD;1;PING OK - Packet loss = 0%, RTA = 1.50 ms"
        down_line = f"[{STATE_CHANGE_EPOCH}] HOST ALERT: {HOST};DOWN;HARD;5;PING CRITICAL - Packet loss = 100%"
        lines.insert(last_idx + 1, up_line + "\n")
        lines.insert(last_idx + 2, down_line + "\n")
    else:
        # Hari berikutnya: DOWN di awal
        down_state = f"[{rotation_ts}] CURRENT HOST STATE: {HOST};DOWN;HARD;5;PING CRITICAL - Packet loss = 100%"
        lines.insert(last_idx + 1, down_state + "\n")

    with open(filepath, "w") as f:
        f.writelines(lines)

    action = "UP + DOWN alert" if is_first_day else "DOWN"
    print(f"  OK: {os.path.basename(filepath)} ({action})")

def update_dat_file(filepath, line_map):
    """Update field di status.dat / retention.dat berdasarkan line number."""
    with open(filepath) as f:
        lines = f.readlines()
    for ln, val in line_map.items():
        idx = ln - 1
        if idx < len(lines):
            ws = lines[idx][:len(lines[idx]) - len(lines[idx].lstrip())]
            lines[idx] = ws + val + "\n"
    with open(filepath, "w") as f:
        f.writelines(lines)

def find_line_numbers(host_name, filepath):
    """Cari line number untuk field yang perlu di-update."""
    with open(filepath) as f:
        lines = f.readlines()
    result = {}
    in_block = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s == f"host_name={host_name}":
            in_block = True
        elif in_block and s.startswith("host_name="):
            break
        elif in_block:
            for key in ["current_state=", "last_state_change=", "last_hard_state_change=", "plugin_output=", "state_type="]:
                if s.startswith(key):
                    result[key.rstrip("=")] = i + 1  # 1-indexed
    return result

# ============================================================
# EKSEKUSI
# ============================================================

print(f"Host: {HOST}")
print(f"DOWN epoch: {STATE_CHANGE_EPOCH}")
print()

# 1. Inject archive logs
print("[1/3] Inject archive logs:")
for i, fname in enumerate(ARCHIVE_FILES):
    fpath = os.path.join(ARCHIVE_DIR, fname)
    if not os.path.exists(fpath):
        print(f"  SKIP (tidak ada): {fname}")
        continue
    shutil.copy2(fpath, fpath + ".bak")
    ts = get_rotation_ts(fpath)
    inject_archive(fpath, i == 0, ts)

# 2. Inject nagios.log
print("[2/3] Inject nagios.log:")
shutil.copy2(NAGIOS_LOG, NAGIOS_LOG + ".bak")
with open(NAGIOS_LOG) as f:
    lines = f.readlines()
if not any(EXACT_MARKER in line for line in lines):
    last_idx = -1
    for i, line in enumerate(lines):
        if "CURRENT HOST STATE:" in line:
            last_idx = i
    if last_idx >= 0:
        ts = get_rotation_ts(os.path.join(ARCHIVE_DIR, ARCHIVE_FILES[-1]))
        down_state = f"[{ts}] CURRENT HOST STATE: {HOST};DOWN;HARD;5;PING CRITICAL - Packet loss = 100%"
        lines.insert(last_idx + 1, down_state + "\n")
        with open(NAGIOS_LOG, "w") as f:
            f.writelines(lines)
        print(f"  OK: nagios.log (DOWN)")
else:
    print("  SKIP: sudah ada")

# 3. Update status.dat + retention.dat
print("[3/3] Update status.dat + retention.dat:")
for dat_file in ["/opt/nagios/var/status.dat", "/opt/nagios/var/retention.dat"]:
    shutil.copy2(dat_file, dat_file + ".bak")
    line_nums = find_line_numbers(HOST, dat_file)
    if not line_nums:
        print(f"  SKIP: {HOST} tidak ditemukan di {dat_file}")
        continue
    updates = {}
    if "current_state" in line_nums:
        updates[line_nums["current_state"]] = "current_state=1"
    if "plugin_output" in line_nums:
        updates[line_nums["plugin_output"]] = "plugin_output=PING CRITICAL - Packet loss = 100%"
    if "last_state_change" in line_nums:
        updates[line_nums["last_state_change"]] = f"last_state_change={STATE_CHANGE_EPOCH}"
    if "last_hard_state_change" in line_nums:
        updates[line_nums["last_hard_state_change"]] = f"last_hard_state_change={STATE_CHANGE_EPOCH}"
    if "state_type" in line_nums:
        updates[line_nums["state_type"]] = "state_type=1"
    update_dat_file(dat_file, updates)
    print(f"  OK: {os.path.basename(dat_file)}")

print()
print("Selesai! Restart container untuk menerapkan:")
print(f"  echo '<pass>' | sudo -S docker restart <container_name>")
```

---

## Cara Pakai

### 1. Hitung Epoch Timestamp

Gunakan Python untuk konversi tanggal ke epoch:

```python
from datetime import datetime
# Contoh: 30 Juni 2026, 13:16:03 WIB (UTC+8)
dt = datetime(2026, 6, 30, 13, 16, 3)
epoch = int(dt.timestamp())
print(epoch)  # → 1782738963
```

Atau via command line:

```python
python3 -c "from datetime import datetime; print(int(datetime(2026,6,30,13,16,3).timestamp()))"
```

### 2. Cari Line Numbers

Sebelum menjalankan script utama, cari line numbers untuk host yang ingin di-edit:

```bash
ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker exec <container> grep -n 'host_name=Nama Host' /opt/nagios/var/status.dat"
```

### 3. Jalankan Script

**Opsi A: Pipe langsung dari dev ke container**

```bash
cat inject_trends.py | ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker exec -i <container> python3"
```

**Opsi B: Copy ke container, lalu jalankan**

```bash
# Copy
ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker cp inject_trends.py <container>:/tmp/"

# Jalankan
ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker exec <container> python3 /tmp/inject_trends.py"
```

**Opsi C: Inline langsung via SSH**

```bash
ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker exec <container> python3 -c '
HOST = \"Nama Host\"
D = \"epoch_value\"
# ... (script inline)
'"
```

### 4. Restart Container

```bash
ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker restart <container>"
```

### 5. Verifikasi

Cek di Nagios UI → Host Information → Trends untuk host tersebut.

---

## Skenario Lain

### UP Stabil (tanpa DOWN)

Tidak perlu `HOST ALERT`. Hanya inject `CURRENT HOST STATE: UP` di setiap archive:

```python
# Untuk setiap archive file:
up_line = f"[{rotation_ts}] CURRENT HOST STATE: {HOST};UP;HARD;1;PING OK - Packet loss = 0%, RTA = 1.50 ms"
# Insert setelah baris CURRENT HOST STATE terakhir
```

### DOWN lalu Recovery (UP)

```python
# Archive hari pertama: DOWN di awal
down_line = f"[{rotation_ts}] CURRENT HOST STATE: {HOST};DOWN;HARD;5;PING CRITICAL..."

# Archive hari recovery: DOWN di awal + UP alert di tengah hari
down_line = f"[{rotation_ts}] CURRENT HOST STATE: {HOST};DOWN;HARD;5;PING CRITICAL..."
up_alert = f"[{recovery_epoch}] HOST ALERT: {HOST};UP;HARD;1;PING OK..."

# Archive hari berikutnya: UP di awal
up_line = f"[{rotation_ts}] CURRENT HOST STATE: {HOST};UP;HARD;1;PING OK..."
```

### Flapping (UP/DOWN Bergantian)

```python
# Di archive hari yang sama, tambah beberapa HOST ALERT:
f"[{ts1}] HOST ALERT: {HOST};DOWN;HARD;5;PING CRITICAL..."
f"[{ts2}] HOST ALERT: {HOST};UP;HARD;1;PING OK..."
f"[{ts3}] HOST ALERT: {HOST};DOWN;HARD;5;PING CRITICAL..."
```

---

## Rollback

Backup disimpan dengan suffix `.bak`:

```bash
# Restore archive
ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker exec <container> sh -c '
cp /opt/nagios/var/archives/nagios-06-30-2026-00.log.bak /opt/nagios/var/archives/nagios-06-30-2026-00.log
cp /opt/nagios/var/status.dat.bak /opt/nagios/var/status.dat
cp /opt/nagios/var/retention.dat.bak /opt/nagios/var/retention.dat
'"

# Restart
ssh -p 2325 rif@103.73.74.98 "echo '<pass>' | sudo -S docker restart <container>"
```

---

## Troubleshooting

| Masalah | Penyebab | Solusi |
|---|---|---|
| Trends tidak berubah | Nagios overwrite status.dat karena host aktif UP | Ganti IP host ke dummy unreachable (misal `10.255.255.1`) |
| `last_state_change` ke-reset | Nagios detect state change UP→DOWN, update timestamp | Update retention.dat + restart lagi. Setelah DOWN stabil, timestamp akan persist |
| `state_type=0` (SOFT) | Nagios masih dalam retry cycle | Tunggu beberapa menit sampai HARD (`state_type=1`) |
| Host tidak muncul di Trends | Host belum ada di config Nagios | Tambah host dulu via dashboard/API sebelum inject |
| Archive file tidak ditemukan | Rotasi log belum sampai tanggal tersebut | Cek `ls /opt/nagios/var/archives/` untuk tanggal yang tersedia |
