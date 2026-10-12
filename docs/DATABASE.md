# Database

Didukung: **SQLite** (default, `instance/webinar.db`) dan **PostgreSQL** (produksi). Skema dikelola
dengan migrasi Alembic di `migrations/`; referensi DDL PostgreSQL ada di [schema.sql](schema.sql).
Semua waktu disimpan dalam **UTC** dan ditampilkan dalam `APP_TIMEZONE` (default Asia/Jakarta).

## Tabel

| Tabel | Isi |
|---|---|
| `participants` | Data peserta. `email` & `phone` (E.164 tanpa `+`) **unik** → mencegah pendaftaran ganda. `access_token` = tautan halaman peserta; `public_id` = ID untuk API. Menyimpan bukti persetujuan (`privacy_consent_at`, `consent_version`, `wa_consent`, `wa_consent_at`, `wa_opted_out_at`), status (`registered`/`cancelled`) dan kehadiran (`attended`, `attendance_method`, `attendance_minutes`, `attended_at`). IP disimpan sebagai HMAC (`registered_ip_hash`). |
| `messages` | Antrean & riwayat pesan WA/email: `purpose`, `channel`, `status`, `attempts`, `next_attempt_at`, `provider_message_id` (untuk mencocokkan webhook), `last_error`, waktu sent/delivered/read/failed. `dedupe_key` unik mencegah pesan ganda. |
| `campaigns` | Pengiriman massal terjadwal (link Zoom, pengingat, pengumuman, sertifikat) beserta audiensnya. |
| `certificates` | Satu per peserta: `sequence`/`number` unik, `verify_code` (QR verifikasi), `download_token`, `file_name`, `revoked_at`. |
| `settings` | Pasangan key → nilai JSON untuk konten acara, link Zoom, template pesan & sertifikat. Daftar key dan default (dari TOR) ada di `app/services/settings_service.py`. |
| `admin_users` | Akun admin (hash scrypt, penguncian, `session_nonce` untuk mencabut sesi saat ganti sandi). |
| `audit_logs` | Jejak aksi admin, sistem, API, dan peserta (opt-out). |
| `integration_events` | Antrean webhook keluar untuk integrasi pihak ketiga. |

## Migrasi

```bash
flask db upgrade                       # terapkan semua migrasi
# setelah mengubah app/models.py:
flask db migrate -m "tambah kolom x"   # buat file migrasi baru, periksa isinya
flask db upgrade
flask db downgrade                     # mundur satu versi
```
Migrasi dibuat dengan `render_as_batch=True` agar kompatibel dengan SQLite.

## Pindah dari SQLite ke PostgreSQL
1. Buat database PostgreSQL kosong, set `DATABASE_URL`, jalankan `flask db upgrade`.
2. Ekspor/impor data, misalnya dengan [`pgloader`](https://pgloader.io): `pgloader instance/webinar.db postgresql://...`
   (lakukan sebelum pendaftaran ramai), atau mulai langsung dengan PostgreSQL sejak awal.
