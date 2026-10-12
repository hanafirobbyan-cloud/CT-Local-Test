# Pengujian

## Test otomatis

```bash
pip install -r requirements-dev.txt
pytest -q
```

38 test (database SQLite sementara, provider WhatsApp palsu, waktu dibekukan) mencakup:

| Area | Yang diuji |
|---|---|
| Pendaftaran | konten TOR tampil, sukses + halaman konfirmasi, validasi & sanitasi, NIM wajib untuk mahasiswa, duplikat email/WA (termasuk format nomor berbeda & huruf besar), honeypot, pendaftaran ditutup, "cek pendaftaran" tidak membocorkan data, normalisasi nomor |
| Zoom | link tidak muncul di halaman publik/peserta/API sebelum publikasi, jendela 30 menit, override wajib alasan, auto-publish oleh worker, validasi domain Zoom |
| Pesan | hanya ke peserta yang memberi izin, retry/backoff → gagal permanen → ulangi manual, opt-out, kampanye terjadwal, payload Meta Cloud API |
| Webhook | verifikasi token & tanda tangan Meta, status delivered/read tanpa turun status, failed dengan kode error, balasan BERHENTI |
| Presensi | aturan kode presensi, impor CSV Zoom (re-join dijumlahkan, durasi minimum, email tak dikenal, tanpa email) |
| Sertifikat | hanya untuk peserta hadir, PDF valid, unduh & verifikasi, pencabutan saat status hadir dibatalkan, auto-kirim setelah acara tanpa duplikasi, nama non-Latin |
| Admin & API | login wajib, penguncian akun + audit, semua halaman admin, aksi admin, ekspor CSV aman formula, API publik & token admin, CSRF aktif, migrasi Alembic, backup |

## Uji manual end-to-end (sebelum hari-H)

1. `.env`: `WHATSAPP_PROVIDER=console` (atau provider asli dengan nomor uji), jalankan `flask run` dan `flask worker`.
2. Buka `/` → cek detail acara, rundown, benefit, FAQ, tampilan mobile (DevTools ukuran 375 px).
3. `/daftar` → kirim form kosong (pesan error per field) → isi lengkap → halaman "Pendaftaran berhasil".
4. Daftar ulang dengan email/nomor yang sama → ditolak.
5. Pesan konfirmasi muncul di `logs/app.log` (console) atau WhatsApp Anda; status di **Pesan & Notifikasi**.
6. Admin `/admin` → **Link Zoom**: simpan link → pastikan link tidak muncul di `/` maupun halaman peserta.
   Untuk menguji publikasi sebelum hari-H, ubah sementara *Waktu mulai* di Pengaturan menjadi ±20 menit
   dari sekarang, atau gunakan *Publikasikan lebih awal* + alasan "uji coba". Halaman peserta kini
   menampilkan tombol Zoom, dan pesan link Zoom terkirim.
7. **Presensi**: isi kode & buka presensi (waktu mulai harus sudah lewat) → isi kode dari halaman peserta.
   Coba juga impor CSV contoh (lihat `tests/test_attendance_certificates.py`, konstanta `ZOOM_CSV`).
8. **Sertifikat**: Pratinjau → Terbitkan & kirim → unduh dari halaman peserta → pindai QR → halaman verifikasi.
9. Batalkan hadir peserta → sertifikat dicabut, tautan unduh 404.
10. **Kembalikan** waktu mulai acara ke 01-11-2026 16:00 dan hapus data uji sebelum publikasi resmi.

Uji webhook Meta secara lokal memakai tunnel HTTPS (cloudflared/ngrok) dan tombol *Test* di halaman
konfigurasi webhook Meta.
