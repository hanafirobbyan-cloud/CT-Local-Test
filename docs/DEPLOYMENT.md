# Panduan Deployment

Aplikasi terdiri dari **dua proses** yang memakai database yang sama:

| Proses | Perintah | Fungsi |
|---|---|---|
| web | `gunicorn wsgi:app` | Situs, dashboard admin, API, webhook |
| worker | `flask worker` | Pengiriman WA/email, kampanye terjadwal, auto-publish Zoom, sertifikat otomatis, webhook keluar, backup |

Keduanya **wajib berjalan**. Folder `instance/` (unggahan & PDF sertifikat) harus dapat diakses kedua
proses dan bersifat persisten. Gunakan **PostgreSQL** di produksi (SQLite cukup untuk satu server
kecil dengan satu proses web).

## Checklist produksi
- [ ] `APP_ENV=production`, `SECRET_KEY` acak 64 karakter heksadesimal
- [ ] `PUBLIC_BASE_URL=https://domain-anda` (dipakai di semua tautan WA/email & QR sertifikat)
- [ ] HTTPS aktif; `TRUST_PROXY=1` bila di belakang reverse proxy
- [ ] `DATABASE_URL` PostgreSQL; `RATELIMIT_STORAGE_URI=redis://...` bila >1 proses web
- [ ] Provider WhatsApp dikonfigurasi & template disetujui; webhook terpasang ([WHATSAPP.md](WHATSAPP.md))
- [ ] `flask db upgrade`, `flask create-admin <username>`, `flask check-config` semua hijau
- [ ] Worker berjalan sebagai service (restart otomatis)
- [ ] Backup disalin ke luar server (lihat di bawah)

## Opsi 1 — VPS dengan Docker Compose (direkomendasikan)

Prasyarat: VPS Linux (1 vCPU / 1–2 GB RAM cukup), Docker + Docker Compose, domain mengarah ke IP VPS.

```bash
git clone <repo-anda> /opt/webinar && cd /opt/webinar
cp .env.example .env && nano .env      # isi APP_ENV=production, SECRET_KEY, PUBLIC_BASE_URL,
                                       # POSTGRES_PASSWORD, WhatsApp, SMTP, dst.
docker compose up -d --build
docker compose exec web flask create-admin admin
docker compose exec web flask check-config
```

Compose menjalankan `db` (PostgreSQL 16), `redis` (rate limit), `web` (gunicorn di port 8000) dan
`worker`. Migrasi otomatis dijalankan saat container start.

### HTTPS dengan Caddy (paling sederhana)
```
# /etc/caddy/Caddyfile
webinar.domain-anda.id {
    reverse_proxy 127.0.0.1:8000
}
```
`sudo systemctl reload caddy` — sertifikat Let's Encrypt otomatis.

### Atau Nginx + Certbot
```nginx
server {
    server_name webinar.domain-anda.id;
    client_max_body_size 6m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
lalu `sudo certbot --nginx -d webinar.domain-anda.id`. Setelah HTTPS aktif, ubah port compose web
menjadi `"127.0.0.1:8000:8000"` agar tidak terbuka langsung ke internet.

### Pembaruan versi
```bash
git pull && docker compose up -d --build
```

## Opsi 2 — VPS tanpa Docker (systemd)

```bash
sudo apt install python3.12-venv postgresql nginx
sudo -u postgres createuser -P webinar && sudo -u postgres createdb -O webinar webinar
cd /opt/webinar && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # DATABASE_URL=postgresql://webinar:PASS@localhost:5432/webinar
.venv/bin/flask db upgrade && .venv/bin/flask create-admin admin
```

`/etc/systemd/system/webinar-web.service`
```ini
[Unit]
Description=Webinar web
After=network.target postgresql.service
[Service]
User=webinar
WorkingDirectory=/opt/webinar
ExecStart=/opt/webinar/.venv/bin/gunicorn wsgi:app --bind 127.0.0.1:8000 --workers 2 --threads 4
Restart=always
[Install]
WantedBy=multi-user.target
```
`/etc/systemd/system/webinar-worker.service` — sama, dengan
`ExecStart=/opt/webinar/.venv/bin/flask worker`.

```bash
sudo systemctl enable --now webinar-web webinar-worker
journalctl -u webinar-worker -f
```

## Opsi 3 — PaaS (Render, Railway, Fly.io, Heroku-like)
- Gunakan `Procfile` (proses `web`, `worker`, `release: flask db upgrade`).
- Tambahkan add-on PostgreSQL (`DATABASE_URL` otomatis dibaca, termasuk format `postgres://`).
- **Penting:** sediakan *persistent disk/volume* yang di-mount ke `instance/` dan dapat diakses web &
  worker; tanpa itu file unggahan/sertifikat hilang saat redeploy. Bila platform tidak mendukung disk
  bersama, jalankan web+worker di satu mesin/VPS.
- Set `TRUST_PROXY=1`.

## Windows (uji/lokal)
Gunicorn tidak berjalan di Windows. Untuk penggunaan lokal: `flask run` + `flask worker`. Untuk server
Windows, gunakan `pip install waitress` lalu `waitress-serve --port=8000 wsgi:app`, dan jalankan
`flask worker` sebagai service (mis. NSSM) atau `flask run-tasks` via Task Scheduler tiap menit.

## Backup & restore
Backup otomatis (`backups/backup-YYYYMMDD-HHMMSS.zip`) berisi database (SQLite: salinan file;
PostgreSQL: `pg_dump`) + folder unggahan & sertifikat. Salin ke luar server, misalnya cron harian:
```bash
0 3 * * * rclone copy /opt/webinar/backups remote:webinar-backups --max-age 48h
```
(Docker: backup ada di volume `backups`; `docker compose cp worker:/app/backups ./backups`.)

**Restore PostgreSQL**
```bash
unzip backup-XXXX.zip -d restore
psql "$DATABASE_URL" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
psql "$DATABASE_URL" -f restore/webinar.sql
cp -r restore/uploads restore/certificates instance/
```
**Restore SQLite:** hentikan web & worker, salin `restore/webinar.db` ke `instance/webinar.db`, salin folder, start ulang.

## Monitoring
- `GET /healthz` → `{"status":"ok"}` untuk uptime monitor (UptimeRobot, dsb.).
- Dashboard menampilkan status worker (heartbeat) dan provider.
- Log aplikasi: `logs/app.log` (rotasi otomatis), audit di menu **Audit Log**.
