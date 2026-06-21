# Nagios Docker dengan LDAP Authentication

Docker setup untuk Nagios dengan Apache LDAP authentication.

## Struktur File

```
create-nagios/
├── Dockerfile
├── nagios.conf
├── cgi.cfg
├── docker-compose.yml
├── build.sh
└── README.md
```

## Cara Menggunakan

### Opsi 1: Menggunakan build.sh (Recommended)

```bash
cd /svr/create-nagios
./build.sh <nama-container> <port>
```

Contoh:
```bash
./build.sh nagios1 81
./build.sh nagios2 82
./build.sh monitoring-prod 8080
```

Script akan otomatis:
- Build Docker image
- Membuat folder `/svr/<nama-container>/etc/`
- Menjalankan container dengan nama dan port yang ditentukan

### Opsi 2: Menggunakan Docker Compose

```bash
cd /svr/create-nagios
docker-compose up -d
```

### Opsi 3: Manual Build dan Run

```bash
cd /svr/create-nagios

# Build image
docker build -t nagios-ldap:latest .

# Create volume directory
mkdir -p /svr/nagios1/etc/

# Run container
docker run -d \
  --name nagios1 \
  -v /svr/nagios1/etc/:/opt/nagios/etc/ \
  -p 0.0.0.0:81:80 \
  nagios-ldap:latest
```

## Akses Nagios

- URL: http://localhost:81/nagios
- URL Alternatif: http://localhost:81/nagios_adiarsa

## Konfigurasi LDAP

- LDAP Server: ldap://172.17.0.1:1389
- Base DN: ou=users,dc=bnet,dc=id
- Bind DN: cn=admin,dc=bnet,dc=id
- Required Group: cn=nagiosadmins,ou=groups,dc=bnet,dc=id

## Menghentikan Container

```bash
docker stop nagios1
docker rm nagios1
```

## Melihat Logs

```bash
docker logs -f nagios1
```
