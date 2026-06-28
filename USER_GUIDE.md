# Nagios Dashboard — User Guide

Panduan lengkap penggunaan Nagios Dashboard untuk tim operasional.

---

## Daftar Isi

- [Login](#login)
- [Dashboard](#dashboard)
- [Monitoring](#monitoring)
  - [Filter & Pencarian](#filter--pencarian)
  - [Sistem Stage](#sistem-stage)
  - [Batch Set Stage](#batch-set-stage)
  - [View Only Mode](#view-only-mode)
  - [Export CSV](#export-csv)
  - [Stage History](#stage-history)
- [Host Manager](#host-manager)
  - [Menambahkan Host](#menambahkan-host)
  - [Mengedit Host](#mengedit-host)
  - [Menghapus Host](#menghapus-host)
  - [Batch Add](#batch-add)
  - [Backup & Restore](#backup--restore)
- [Servers](#servers)
  - [Menambahkan Server](#menambahkan-server)
  - [Mengelola Server](#mengelola-server)
  - [Plugin Manager](#plugin-manager)
- [Users & Permissions](#users--permissions)
  - [Menambahkan User](#menambahkan-user)
  - [Mengatur Permissions](#mengatur-permissions)
- [Monitoring Settings](#monitoring-settings)
  - [Refresh Interval](#refresh-interval)
  - [Alarm Settings](#alarm-settings)
  - [CR Auto-Reset](#cr-auto-reset)
  - [Kategori Monitoring](#kategori-monitoring)
  - [Server Mapping](#server-mapping)
- [Global Settings](#global-settings)
  - [Domain Configuration](#domain-configuration)
  - [Backup & Restore](#backup--restore-1)
  - [Uptime Kuma Integration](#uptime-kuma-integration)
  - [API Key](#api-key)
  - [Activity Logs](#activity-logs)
- [Monitoring Intens (Uptime Kuma)](#monitoring-intens-uptime-kuma)
- [Active Users](#active-users)
- [Audit](#audit)
  - [Stage History](#stage-history-1)
  - [Activity Logs](#activity-logs-1)
- [Tips & Trik](#tips--trik)

---

## Login

1. Buka aplikasi di browser
2. Masukkan **Username** dan **Password**
3. Klik **Login**

> Jika ini pertama kali aplikasi dijalankan, kamu akan diarahkan ke halaman **Setup** untuk membuat akun admin pertama.

---

## Dashboard

Halaman utama yang menampilkan ringkasan semua server Nagios secara real-time.

### Yang Ditampilkan

Setiap server menampilkan kartu dengan informasi:

| Informasi | Keterangan |
|---|---|
| **Server Name** | Nama container Nagios |
| **CPU** | Penggunaan CPU container |
| **Memory** | Penggunaan RAM container |
| **Hosts UP** | Jumlah host yang online (hijau) |
| **Hosts DOWN** | Jumlah host yang mati (merah) |
| **Hosts UNREACHABLE** | Jumlah host yang tidak terjangkau (kuning) |
| **Services OK/WARN/CRIT** | Status service checks |

### Fitur

- **Auto-refresh** setiap 30 detik — data selalu terbaru tanpa perlu refresh manual
- Klik **Open Nagios** untuk membuka panel Nagios asli di tab baru

---

## Monitoring

Halaman utama untuk memantau host yang bermasalah (DOWN/UNREACHable), dikelompokkan berdasarkan kategori (contoh: Prioritas, Bhome, OPD).

### Filter & Pencarian

Di bagian atas halaman terdapat filter untuk mempersempit data:

| Filter | Fungsi |
|---|---|
| **Server** | Filter berdasarkan server Nagios tertentu |
| **Status Info** | Filter berdasarkan jenis masalah (LOS, DyingGasp, PING, dll) |
| **Stage** | Filter berdasarkan stage (New, CR Verification, Escalated, Watchlist) |
| **Detail** | Pencarian bebas — ketik nama host, IP, atau kata kunci apapun |

Filter bisa dikombinasikan. Contoh: pilih server "Bhome" + stage "CR Verification" + ketik "Dyinggasp" di Detail → hanya menampilkan host yang sesuai semua kriteria.

### Sistem Stage

Setiap host yang DOWN/UNREACHable memiliki **stage** yang menunjukkan status penanganan:

| Stage | Warna | Keterangan |
|---|---|---|
| 🔴 **New / Unacknowledged** | Merah | Alert baru, belum ada tindakan |
| 🔵 **CR Verification** | Biru | Tim Customer Relation sedang mengecek |
| 🟠 **Escalated / Pending** | Oranye | Menunggu pihak lain (FE, PLN, dll) |
| 🟣 **Watchlist / Flapping** | Ungu | Host tidak stabil, naik-turun |
| ✅ **Resolved** | Hijau | Masalah selesai — ACK ke Nagios |

#### Cara Mengubah Stage

1. Klik tombol **Stage** di baris host yang diinginkan
2. Pilih stage baru
3. (Opsional) Tulis **Catatan** — misalnya "FU Dyinggasp", "Menunggu FE"
4. Klik **Set Stage**

> **Catatan Penting:**
> - Stage **selain Resolved** hanya mengubah data di dashboard, **tidak** mengirim apapun ke Nagios
> - Stage **Resolved** mengirim ACK ke Nagios dan host akan hilang dari daftar monitoring
> - Catatan bersifat **opsional** untuk semua stage, kecuali **Resolved** yang **wajib**

#### Contoh Penggunaan

| Situasi | Action |
|---|---|
| Host baru DOWN, belum dicek | Set stage → **New** (default) |
| Sudah dihubungi PIC, menunggu konfirmasi | Set stage → **CR Verification** + catatan "FU Dyinggasp" |
| Sudah dikirim ke tim teknis | Set stage → **Escalated** + catatan "Menunggu FE" |
| Host sering naik-turun | Set stage → **Watchlist** + catatan "LOS intermittent" |
| Masalah sudah selesai | Set stage → **Resolved** + catatan wajib → ACK ke Nagios |

### Batch Set Stage

Untuk mengubah stage beberapa host sekaligus:

1. **Centang** host yang diinginkan (klik di mana saja pada baris)
2. Klik tombol **Batch Set Stage** di bagian atas tabel
3. Pilih stage dan tulis catatan (berlaku untuk semua host yang dipilih)
4. Klik **Set Stage**

> Tips: Gunakan checkbox di header tabel untuk **Select All**.

### View Only Mode

Mode tampilan full-screen tanpa kontrol — cocok untuk layar NOC/monitoring room.

1. Klik tombol **View Only** di header monitoring
2. Tabel akan tampil full-screen dengan font besar
3. Untuk keluar, klik tombol **✕** merah di pojok kanan atas

> View Only hanya menampilkan host dengan stage **New** (belum ditangani).

### Export CSV

Download data monitoring ke file Excel/CSV:

1. Atur filter sesuai kebutuhan (opsional)
2. Klik tombol **Export CSV**
3. File otomatis ter-download

File CSV mencakup: Server, Host, IP, Status, Stage, Catatan, Duration, Last Check, Detail.

### Stage History

Melihat catatan lengkap semua perubahan stage:

1. Buka **Audit → Stage History** di sidebar (atau klik tombol **History** di header monitoring)
2. Gunakan filter: Host, Container, Limit (auto-submit saat ganti limit)
3. Tabel menampilkan: Timestamp, Host, Container, Perubahan Stage (dari → ke), User, Catatan

> Catatan: History bersifat **persisten** — tidak bisa dihapus dan tersimpan selamanya.

---

## Host Manager

Halaman untuk mengelola host di semua server Nagios — tambah, edit, hapus, backup.

### Menambahkan Host

1. Klik tombol **Add Host**
2. Isi form:
   - **Server** — pilih server Nagios tujuan
   - **Host Name** — nama unik host (contoh: `WP-SDN-Jaya-Makmur`)
   - **Alias** — nama tampilan (opsional)
   - **IP Address** — alamat IP host
   - **Parent** — host induk (opsional, untuk hierarki jaringan)
3. (Opsional) Centang **Monitor in Uptime Kuma** untuk menambahkan monitoring ping
4. (Opsional) Centang **Add Service/Plugin** untuk menambahkan service check (contoh: `check_ping`)
5. Klik **Add Host**

> Host akan langsung ditambahkan ke config Nagios dan container di-restart otomatis.

### Mengedit Host

1. Klik tombol **Edit** di baris host
2. Ubah field yang diinginkan
3. Klik **Save Changes**

### Menghapus Host

1. Klik tombol **Delete** di baris host
2. Konfirmasi penghapusan
3. Host dan semua service check terkait akan dihapus, container di-restart

> **Perhatian:** Jika host memiliki "anak" (child host), anak-anaknya juga akan ditampilkan untuk konfirmasi.

### Batch Add

Untuk menambahkan banyak host sekaligus:

1. Klik tombol **Batch Add**
2. Tambahkan baris dengan tombol **Add Row**
3. Isi Server, Hostname, IP, Parent untuk setiap baris
4. Klik **Add All Hosts**

### Backup & Restore

#### Membuat Backup

1. Pilih server di dropdown
2. Klik **Backup**
3. Backup tersimpan di daftar backup

#### Restore Backup

1. Cari backup yang diinginkan di daftar
2. Klik **Restore**
3. Config akan dikembalikan ke versi backup

#### Hapus Backup

- Klik tombol **Delete** di baris backup

---

## Servers

Halaman untuk mengelola container Nagios Docker.

### Menambahkan Server

1. Isi **Server Name** (contoh: `nagios-prod-01`)
2. Isi **Port** (contoh: `5001`) atau klik **Auto** untuk port otomatis
3. Klik **Create Server**

> Port harus unik dan belum digunakan. Proxy otomatis dibuat di port `1000 + port` (contoh: port 5001 → proxy 6001).

### Mengelola Server

| Action | Keterangan |
|---|---|
| **Start / Stop** | Nyalakan/matikan container |
| **Restart** | Restart container |
| **Delete** | Hapus container dan semua config-nya |
| **Config** | Edit config Apache Nagios |
| **Check** | Validasi config Nagios (cek error sebelum restart) |
| **Plugin** | Kelola check plugins |

#### Batch Actions

Centang beberapa server, lalu:
- **Start** — nyalakan semua
- **Restart** — restart semua
- **Delete** — hapus semua (dengan konfirmasi)

### Plugin Manager

1. Klik tombol **Plugin** di baris server
2. **Upload**: pilih file plugin, klik **Upload**
3. **Delete**: klik tombol **Delete** di baris plugin

---

## Users & Permissions

### Menambahkan User

1. Isi form di bagian atas:
   - **Username** — ID unik user
   - **Full Name** — nama lengkap
   - **Surname** — nama belakang
   - **Password**
   - **Role** — pilih **User** atau **Admin**
2. Jika role **User**, atur permissions (lihat [Mengatur Permissions](#mengatur-permissions))
3. Klik **Add User**

> User dengan role **Admin** memiliki akses penuh ke semua fitur.

### Mengatur Permissions

1. Buka halaman **User Permissions** (dari sidebar)
2. Klik **Edit** di baris user
3. Atur permissions:

| Permission | Fungsi |
|---|---|
| **Dashboard** | Akses halaman Dashboard |
| **Host Manager** | Akses kelola host |
| **Servers** | Akses kelola server |
| **Users** | Akses kelola user |
| **User Permissions** | Akses halaman ini |
| **Monitoring Settings** | Akses pengaturan monitoring |
| **Global Settings** | Akses pengaturan global |
| **CR View Only** | Batasi monitoring hanya tampil host stage CR Verification |

4. Atur akses per **Monitoring Category** dan **Nagios Server**
5. Klik **Save Permissions**

> **CR View Only** — gunakan untuk tim Customer Relation yang hanya perlu melihat host yang sudah di-assign ke mereka.

---

## Monitoring Settings

### Refresh Interval

Atur seberapa sering halaman monitoring auto-refresh:

1. Isi **Refresh Interval** (dalam detik, default: 30)
2. Klik **Update Interval**

### Alarm Settings

Atur notifikasi suara untuk setiap kategori monitoring:

1. Centang **Alarm on DOWN** untuk notifikasi saat host mati
2. Centang **Alarm on UP** untuk notifikasi saat host hidup kembali
3. Upload file suara untuk masing-masing (format: MP3, WAV, dll)
4. Klik **Test** untuk preview suara
5. Klik **Save Alarm Settings**

### CR Auto-Reset

Otomatis reset host CR Verification ke New pada jadwal tertentu:

| Field | Keterangan | Contoh |
|---|---|---|
| **Reset Hours** | Jam reset (format 24 jam) | `15` = jam 3 sore, `03,15` = jam 3 pagi & 3 sore |
| **Interval** | Berapa hari sekali | `1` = setiap hari, `4` = setiap 4 hari, `0` = nonaktif |
| **Grace Period** | Skip host yang baru di-set dalam X jam | `6` = host yang di-set CR Verif < 6 jam lalu tidak ikut reset |

> **Grace Period** mencegah host yang baru kamu set CR Verification langsung di-reset ke New saat scheduler berjalan.

### Kategori Monitoring

1. Klik **Add Category** untuk membuat kategori baru
2. Isi nama kategori dan pilih **Status Information Source**:
   - **Default** — menggunakan output host plugin
   - **Service Plugin Output** — menggunakan output service plugin
3. Klik **Add Category**

### Server Mapping

Kaitkan server Nagios ke kategori monitoring:

1. Pilih **Server** dan **Category**
2. Klik **Map Server**

Server yang sudah di-map akan muncul di halaman monitoring kategori tersebut.

---

## Global Settings

### Domain Configuration

Atur domain dasar untuk URL proxy:

1. Isi **Domain Name** (contoh: `nagios.example.com`)
2. Klik **Save Domain**

### Backup & Restore

#### Membuat Backup Sistem

1. Isi nama backup (opsional)
2. Klik **Create Backup**
3. File `.tar.gz` tersimpan di daftar backup

#### Upload Backup

1. Pilih file backup (`.tar.gz`)
2. Klik **Upload Backup**

#### Restore

1. Cari backup di daftar
2. Klik **Restore**

#### Download

- Klik **Download** untuk mengunduh file backup

### Uptime Kuma Integration

Hubungkan dashboard dengan Uptime Kuma untuk monitoring ping:

1. Isi **URL** (contoh: `http://localhost:3001`)
2. Isi **Username** dan **Password**
3. Centang **Enable Uptime Kuma Integration**
4. Klik **Save Uptime Kuma Config**

> Setelah aktif, kamu bisa menambahkan host ke Uptime Kuma saat menambah host di Host Manager.

### API Key

API Key digunakan untuk integrasi dengan server lain (misalnya: auto-add host dari sistem lain).

1. Klik **Generate New Key** untuk membuat API key baru
2. Klik **Copy** untuk menyalin ke clipboard
3. Gunakan di header `X-API-Key` atau query param `?api_key=YOUR_KEY`

> **Perhatian:** Generate key baru akan membatalkan key lama. Pastikan update semua integrasi.

### Activity Logs

Melihat log aktivitas semua user:

1. Klik **Refresh** untuk memuat log terbaru
2. Log menampilkan: timestamp, user, IP, aksi, detail
3. Klik **Clear Logs** untuk menghapus semua log

> Log tersimpan per bulan dan tidak dihapus otomatis.

---

## Monitoring Intens (Uptime Kuma)

Halaman untuk melihat status monitor Uptime Kuma secara real-time.

### Informasi Per Monitor

| Informasi | Keterangan |
|---|---|
| **Status** | UP (hijau), DOWN (merah), PENDING (kuning) |
| **Type** | Jenis monitor (PING, HTTP, DNS, TCP, dll) |
| **Hostname/IP** | Target monitoring |
| **Last Check** | Kapan terakhir dicek |
| **Uptime 24h** | Persentase uptime 24 jam terakhir |
| **Heartbeat Chart** | Grafik bar status 48 jam terakhir |
| **Avg Ping** | Rata-rata response time |

### Menghapus Monitor

Klik tombol **Remove Monitor** di kartu monitor.

---

## Active Users

Halaman untuk melihat user yang sedang online (admin only).

Akses via URL: `/active-users`

| Informasi | Keterangan |
|---|---|
| **Username** | Nama user |
| **Role** | Admin / User |
| **IP Address** | Alamat IP user |
| **Login At** | Waktu login |
| **Last Active** | Aktivitas terakhir |
| **Idle Time** | Lama tidak aktif |

> User dianggap aktif selama masih ada request (termasuk auto-refresh monitoring). User idle > 5 menit otomatis dihapus dari daftar.

---

## Audit

Menu **Audit** di sidebar menyediakan dua sub-halaman untuk tracking aktivitas sistem.

### Stage History

Catatan persisten semua perubahan stage host, tersimpan di `config/stage_history/` sebagai file JSONL bulanan.

**Akses:** Sidebar → **Audit → Stage History** (atau langsung ke `/stage-history`)

| Fitur | Keterangan |
|---|---|
| **Filter Host** | Cari berdasarkan nama host |
| **Filter Container** | Cari berdasarkan server Nagios |
| **Limit** | Jumlah entri (50/100/250/500), auto-submit saat diganti |
| **Data** | Timestamp, Host, Container, Perubahan Stage, User, Catatan |

> History bersifat **persisten** dan tidak bisa dihapus. Semua perubahan stage (manual, batch, auto-reset) tercatat.

### Activity Logs

Halaman standalone untuk melihat log aktivitas semua user di sistem.

**Akses:** Sidebar → **Audit → Activity Logs** (atau langsung ke `/activity-logs`)

| Fitur | Keterangan |
|---|---|
| **Limit** | Jumlah baris (100/250/500/1000), auto-submit saat diganti |
| **Refresh** | Muat ulang log terbaru |
| **Clear Logs** | Hapus semua log (admin only) |
| **Format** | Timestamp, User, IP, Aksi, Detail |

> Log tersimpan per bulan (`config/activity_logs/activity_log_YYYY_MM.txt`) dan tidak dihapus otomatis.

---

## Tips & Trik

### Monitoring

- **Klik di mana saja pada baris** untuk memilih host (tidak harus klik checkbox)
- **Kombinasikan filter** untuk menemukan host dengan cepat
- **Gunakan View Only** untuk layar NOC — tampilan bersih tanpa kontrol
- **Stage History** untuk audit — siapa mengubah stage kapan dan mengapa

### Host Manager

- **Magic wand** di form Add Host → generate nama otomatis format `NID-CID-Name`
- **Batch Add** untuk menambahkan banyak host sekaligus
- **Backup sebelum edit** — selalu buat backup sebelum perubahan besar

### Efficiency

- **Batch Set Stage** untuk menangani banyak host sekaligus
- **Export CSV** untuk laporan ke management
- **CR Auto-Reset** mengembalikan host ke New otomatis → tidak ada yang terlewat
- **Grace Period** melindungi host yang baru kamu assign dari auto-reset

### Shortcut

| Shortcut | Fungsi |
|---|---|
| Klik baris | Pilih/toggle host |
| Klik header kolom | Sort data |
| `/active-users` | Lihat user online (admin) |
| `/stage-history` | Lihat history stage |

---

## FAQ

**Q: Kenapa host yang sudah saya set CR Verification tiba-tiba kembali ke New?**
A: Kemungkinan CR Auto-Reset sudah aktif. Cek **Monitoring Settings → CR Auto-Reset** untuk jadwal dan grace period.

**Q: Apakah mengubah stage selain Resolved mempengaruhi Nagios?**
A: Tidak. Hanya **Resolved** yang mengirim ACK ke Nagios. Stage lain hanya di dashboard.

**Q: Bagaimana cara melihat host yang sudah di-ACK?**
A: Host yang sudah di-ACK (Resolved) akan hilang dari monitoring. Cek di **Stage History** untuk riwayatnya.

**Q: Apakah saya bisa menambah host dari luar dashboard?**
A: Ya, gunakan API endpoint `POST /api/hosts/add` dengan API Key. Lihat **Global Settings → API Key**.

**Q: Kenapa saya tidak bisa melihat menu tertentu?**
A: Akses dikontrol oleh permissions. Hubungi admin untuk mengatur permissions di **User Permissions**.

**Q: Bagaimana cara backup semua data?**
A: Buka **Global Settings → Backup & Restore → Create Backup**. Atau jalankan script `full_backup.sh` di server.

**Q: Apakah ada batasan jumlah host yang bisa di-batch?**
A: Tidak ada batasan teknis, tapi proses mungkin lambat jika > 100 host sekaligus karena container perlu di-restart.
