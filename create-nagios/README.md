# Nagios Docker dengan LDAP Authentication

Docker setup untuk Nagios + Apache LDAP auth. Volume base: `/svr/<name>/` (sengaja hardcoded di ops ini).

## Struktur

```
create-nagios/
├── Dockerfile
├── nagios.conf
├── cgi.cfg
├── docker-compose.yml
├── build.sh
└── README.md
```

## Cara pakai

### Opsi 1: `build.sh` (recommended)

```bash
cd /svr/create-nagios   # atau path setara di environment
./build.sh <nama-container> <port>
# contoh: ./build.sh Adiarsa 81
```

Script: build image, buat `/svr/<nama>/etc/`, jalankan container.

### Opsi 2: Docker Compose

```bash
cd /svr/create-nagios
docker-compose up -d
```

### Opsi 3: Manual

```bash
docker build -t nagios-ldap:latest .
mkdir -p /svr/nagios1/etc/
docker run -d --name nagios1 \
  -v /svr/nagios1/etc/:/opt/nagios/etc/ \
  -p 0.0.0.0:81:80 \
  nagios-ldap:latest
```

## Akses & LDAP

- URL: `http://<host>:<port>/nagios`
- LDAP (default template): `ldap://172.17.0.1:1389`, base `ou=users,dc=bnet,dc=id`, group `cn=nagiosadmins,ou=groups,dc=bnet,dc=id`
- Prod Docker biasanya butuh `sudo` (user `rif`)

```bash
docker logs -f <nama>
docker stop <nama> && docker rm <nama>
```
