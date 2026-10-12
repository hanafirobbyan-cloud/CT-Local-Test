# Sistem Pendaftaran Webinar — *Penerapan Logika Digital untuk Membangun Startup dan UMKM*

Website pendaftaran webinar **open-source** (MIT) yang lengkap end-to-end: halaman acara, formulir
pendaftaran, notifikasi WhatsApp otomatis, publikasi link Zoom yang aman, verifikasi kehadiran,
e-sertifikat PDF otomatis, dan dashboard admin.

| Detail acara (dari TOR) | |
|---|---|
| Tema | Growth Startup dan UMKM |
| Waktu | Minggu, 01 November 2026 · 16.00 WIB – selesai |
| Platform | Online via Zoom Meeting |
| Narasumber | Fadel Rasyid |
| Moderator | Nayla Tazkiyah Fadli |
| Sasaran | Pelajar, mahasiswa, penggiat Startup & pelaku UMKM |
| Benefit | E-certificate resmi, poin SKEM (mahasiswa), knowledge & toolkit strategi growth |
| Contact person | Nayla (082136190243) |

Semua konten di atas tersimpan sebagai **pengaturan yang dapat diubah admin**. Detail yang tidak ada
di TOR (nama penyelenggara, logo, foto & profil lengkap pembicara, penandatangan sertifikat, link Zoom)
sengaja dikosongkan dan diisi panitia lewat dashboard. Dashboard menampilkan peringatan sampai detail itu diisi.

---

## Fitur

**Peserta (Bahasa Indonesia, mobile-first)**
- Landing page: detail acara, latar belakang & tujuan, pembicara, rundown, benefit, FAQ, kontak, hitung mundur.
- Formulir pendaftaran dengan validasi server-side, normalisasi nomor WA (`0812…`, `+62 812…` → `62812…`),
  pencegahan pendaftaran ganda (email **dan** nomor WA unik), honeypot anti-bot, rate limit, CSRF.
- Persetujuan eksplisit: kebijakan privasi (wajib) dan izin WhatsApp (opsional, terpisah).
- **Halaman peserta pribadi** (tautan rahasia): konfirmasi, link Zoom (setelah dipublikasikan),
  presensi dengan kode, unduh e-sertifikat, berhenti/aktifkan notifikasi WA.
- "Cek pendaftaran": kirim ulang konfirmasi ke kontak terdaftar tanpa membocorkan data.
- Verifikasi keaslian sertifikat via QR code.

**Admin**
- Login aman (hash scrypt, penguncian akun setelah gagal berulang, sesi kedaluwarsa, audit log).
- Statistik: pendaftar, kategori, tren harian, kehadiran, status pengiriman pesan, sertifikat, status worker.
- Peserta: cari, filter, ekspor CSV (aman dari formula injection), ubah, batalkan, hapus, tandai hadir.
- Link Zoom: disimpan rahasia → dipublikasikan mulai **30 menit sebelum acara** (manual atau otomatis),
  langsung dikirim via WhatsApp/email. Publikasi lebih awal hanya dengan alasan tercatat di audit log.
- Presensi: kode presensi saat acara, impor laporan peserta Zoom (CSV), atau tarik via Zoom API.
- Pesan: antrean dengan retry/backoff, status `queued → sent → delivered → read / failed` dari webhook,
  ulangi pesan gagal, jadwalkan pengingat/pengumuman, edit template pesan.
- Sertifikat: template dapat dikustomisasi (teks, warna, posisi, latar, logo, tanda tangan, font TTF),
  pratinjau PDF, terbit & kirim otomatis **hanya untuk peserta yang hadir**.
- Konten situs, audit log, ganti kata sandi, QR code pendaftaran resmi.

**Integrasi**
- WhatsApp: **WhatsApp Business Platform (Cloud API) resmi Meta**, atau Fonnte sebagai alternatif.
- Email SMTP (cadangan otomatis untuk peserta tanpa izin WA).
- Zoom Server-to-Server OAuth (laporan peserta).
- REST API `/api/v1` + webhook keluar bertanda tangan HMAC untuk bot & layanan pihak ketiga.

## Teknologi

Python 3.11+ · Flask 3 · SQLAlchemy 2 + Alembic (SQLite/PostgreSQL) · fpdf2 (PDF) · Jinja2 + CSS/JS murni
(tanpa build step) · pytest. Tanpa layanan berbayar wajib selain provider WhatsApp pilihan Anda.

## Mulai cepat (lokal)

```bash
git clone <repo-anda> webinar-logika-digital && cd webinar-logika-digital
python -m venv .venv
# Windows: .venv\Scripts\activate    |   Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # Windows: copy .env.example .env
# isi SECRET_KEY:  python -c "import secrets; print(secrets.token_hex(32))"
flask db upgrade                 # buat tabel
flask create-admin admin         # buat akun admin (min. 12 karakter)
flask run                        # http://localhost:5000  (admin: /admin)
```

Di terminal kedua jalankan **worker** (wajib — semua pengiriman pesan, jadwal, auto-publish Zoom,
sertifikat otomatis, dan backup dijalankan di sini):

```bash
flask worker
```

Untuk mencoba alur pesan tanpa akun WhatsApp, set `WHATSAPP_PROVIDER=console` di `.env`: pesan hanya
ditulis ke `logs/app.log` (mode ini otomatis nonaktif di produksi dan diberi label jelas di dashboard).
`flask seed-demo` membuat peserta contoh (khusus development).

> **Windows dengan Smart App Control:** jika muncul `DLL load failed ... Application Control policy`
> saat import SQLAlchemy, pasang ulang SQLAlchemy versi murni Python:
> `set DISABLE_SQLALCHEMY_CEXT=1` lalu `pip install --force-reinstall --no-binary sqlalchemy sqlalchemy==2.1.4`.

## Dokumentasi

| Dokumen | Isi |
|---|---|
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | **Panduan operasional panitia**: persiapan, hari-H, setelah acara, troubleshooting |
| [docs/WHATSAPP.md](docs/WHATSAPP.md) | Setup Meta Cloud API, teks template yang harus diajukan, webhook, Fonnte, kebijakan WhatsApp |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Deploy ke VPS (Docker/Nginx), PaaS, HTTPS, backup & restore, checklist produksi |
| [docs/API.md](docs/API.md) · [docs/openapi.yaml](docs/openapi.yaml) | REST API & webhook keluar untuk bot/integrasi |
| [docs/DATABASE.md](docs/DATABASE.md) · [docs/schema.sql](docs/schema.sql) | Skema database & migrasi |
| [docs/TESTING.md](docs/TESTING.md) | Menjalankan test otomatis & uji manual end-to-end |

## Struktur proyek

```
app/
  __init__.py          factory Flask, header keamanan, error handler
  config.py            semua konfigurasi dari environment (.env)
  models.py            model database
  cli.py               perintah: create-admin, worker, run-tasks, backup, check-config, seed-demo
  blueprints/          public.py (situs), admin.py (dashboard), api.py (REST), webhooks.py (WA masuk)
  services/            logika bisnis — dapat dipakai ulang oleh bot/CLI/API
    registration.py    validasi & pendaftaran          notifications.py  antrean pesan & kampanye
    zoom.py            simpan/publikasi link & Zoom API attendance.py     presensi & impor laporan Zoom
    certificates.py    PDF & penerbitan sertifikat      settings_service.py konten acara (default dari TOR)
    whatsapp/          provider: meta_cloud, fonnte, console (+ tambah provider sendiri)
    email_service.py   SMTP                            integrations.py   webhook keluar
    scheduler.py       satu siklus worker              backup.py         backup + retensi
  templates/, static/  tampilan (Jinja2, CSS, JS)
migrations/            migrasi Alembic
tests/                 pytest (38 test)
docs/                  dokumentasi
```

## Keamanan (ringkas)

Rahasia hanya di environment variable · CSRF di semua form · Content-Security-Policy ketat (tanpa
inline script) · cookie sesi HttpOnly/SameSite/Secure · rate limit pendaftaran, login, presensi, API ·
penguncian akun admin · tanda tangan HMAC untuk webhook Meta & webhook keluar · token acak 256-bit untuk
halaman peserta & unduhan sertifikat · link Zoom tidak pernah dirender di halaman publik · IP disimpan
sebagai hash · validasi isi file unggahan · audit log semua aksi penting · backup otomatis berkala.

## Lisensi

MIT — lihat [LICENSE](LICENSE). Silakan fork dan sesuaikan untuk acara Anda.
