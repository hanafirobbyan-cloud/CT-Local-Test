# Panduan Operasional Panitia

Panduan ini untuk admin/panitia yang menjalankan webinar. Semua menu ada di `/admin`.

## Sebelum pendaftaran dibuka

1. **Konten & Pengaturan** — periksa isi dari TOR, lalu lengkapi yang belum ada di TOR:
   nama penyelenggara, logo, foto & profil narasumber/moderator, poster (opsional). Tinjau teks
   **Kebijakan privasi** agar sesuai kebijakan lembaga Anda. Atur kuota bila akun Zoom terbatas
   (mis. 100/300/500 partisipan) dan batas waktu pendaftaran bila perlu.
2. **Sertifikat** — isi penandatangan (nama, jabatan, gambar tanda tangan PNG transparan), sesuaikan
   teks/warna/posisi atau unggah gambar latar desain sendiri (A4 landscape), lalu klik **Pratinjau**.
   Bila nama peserta bisa memakai huruf non-Latin, unggah font `.ttf` (mis. Noto Sans).
3. **Pesan → Edit template pesan** — sesuaikan teks (dipakai untuk email & Fonnte). Untuk Meta,
   ajukan template sesuai [WHATSAPP.md](WHATSAPP.md).
4. Pastikan dashboard menunjukkan **WhatsApp ✓ siap** dan **Worker ✓ aktif**.
5. Uji alur: daftar memakai nomor & email sendiri → cek pesan konfirmasi → hapus data uji.
6. Unduh **QR pendaftaran** di dashboard untuk poster (TOR: "Scan QR Code link pendaftaran resmi").

## Selama masa pendaftaran

- Pantau statistik di **Dashboard**; cari/filter/ekspor di **Peserta**.
- Perbaiki ejaan nama (untuk sertifikat) di detail peserta. Jika sertifikat sudah terbit, klik
  **Buat ulang PDF** setelah mengubah nama.
- Pesan gagal: **Pesan & Notifikasi → filter Gagal** — kolom *Keterangan* berisi alasan dari provider
  (mis. nomor tidak terdaftar di WhatsApp). Klik **Ulangi** atau **Ulangi semua yang gagal**.
- Pengingat: di **Pesan & Notifikasi → Jadwalkan pengingat**, pilih waktu (mis. H-1 pukul 16.00 WIB).

## Hari-H (Minggu, 01 November 2026)

| Waktu (WIB) | Tindakan |
|---|---|
| Sebelum 15.30 | Buat meeting di Zoom. Di menu **Link Zoom**, isi link, Meeting ID, passcode → **Simpan**. Link tersimpan rahasia (tidak tampil di situs). Opsional: centang *auto-publish*. |
| 15.30 | Jendela publikasi terbuka (30 menit sebelum acara). Klik **Publikasikan & kirim ke peserta** (atau otomatis bila auto-publish aktif). Link langsung dikirim via WhatsApp/email dan muncul di halaman peserta. Pantau status pengiriman di halaman yang sama. |
| Bila link berubah | Ubah di **Link Zoom** → Simpan → **Publikasikan ulang**. Pesan lama yang belum terkirim otomatis dibatalkan. |
| 16.00 – 17.45 | Menu **Presensi**: isi *Kode presensi* (mis. `GROWTH26`), centang *Presensi dibuka*, Simpan. Moderator mengumumkan kode; peserta mengisinya di halaman peserta. |
| Setelah acara | Tutup presensi (hapus centang). |

Publikasi sebelum 15.30 hanya bisa dengan mencentang *Publikasikan lebih awal* dan mengisi alasan;
tindakan ini tercatat di **Audit Log**.

## Setelah acara: verifikasi kehadiran & sertifikat

1. **Laporan Zoom** — di Zoom web: *Reports → Usage → (meeting) → Participants → Export*.
   Unggah CSV di menu **Presensi**. Peserta dicocokkan berdasarkan **email**, durasi beberapa sesi
   (re-join) dijumlahkan, dan hanya yang memenuhi *Durasi minimum* ditandai hadir. Hasil impor
   menampilkan: email yang tidak cocok, peserta Zoom tanpa email, dan yang di bawah durasi minimum —
   periksa manual dan tandai hadir di detail peserta bila memang hadir.
   *Tips:* minta peserta bergabung memakai email pendaftaran; aktifkan "Only authenticated users can
   join" atau registrasi Zoom agar email tercatat.
2. **Zoom API** (opsional) — bila `ZOOM_*` diisi, klik **Ambil laporan peserta** (meeting harus sudah selesai).
3. **Sertifikat** — dengan *Kirim sertifikat otomatis* aktif, mulai *waktu selesai + jeda* (default
   18.00 + 60 menit) worker menerbitkan dan mengirim tautan sertifikat ke setiap peserta yang hadir.
   Peserta yang kehadirannya diverifikasi belakangan juga otomatis menerima. Alternatif manual:
   **Terbitkan & kirim ke semua yang hadir**. Peserta yang tidak hadir tidak pernah mendapat sertifikat;
   membatalkan status hadir otomatis mencabut sertifikatnya.
4. **SKEM** — ekspor CSV dengan filter *Kategori = Mahasiswa* dan *Hadir* untuk laporan poin SKEM
   (berisi nama, NIM, prodi, institusi, nomor sertifikat).

## Konfigurasi Zoom API (opsional)
1. marketplace.zoom.us → *Develop → Build App* → **Server-to-Server OAuth**.
2. Scope: `report:read:list_meeting_participants:admin` (akun Zoom Pro ke atas, pembuat app harus admin).
3. Aktifkan app, salin Account ID, Client ID, Client Secret ke `.env` (`ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`).

## Email (opsional, disarankan)
Isi `SMTP_*` dan `MAIL_FROM` (Gmail Workspace dengan App Password, Brevo, Mailgun, SendGrid, dsb.).
Email dipakai bila *Kirim juga via email* aktif, dan selalu sebagai cadangan untuk peserta tanpa izin WA.
Gunakan domain dengan SPF/DKIM agar tidak masuk spam.

## Akun admin
- Admin baru / reset kata sandi: `flask create-admin <username>` (di server).
- Nonaktifkan: `flask deactivate-admin <username>`.
- 5 kali salah kata sandi → akun terkunci 15 menit (dapat diatur di `.env`).

## Backup & data pribadi
- Worker membuat backup otomatis setiap `BACKUP_INTERVAL_HOURS` (default 24 jam) ke `backups/`,
  menyimpan `BACKUP_RETENTION` file terakhir. Manual: `flask backup`. Salin backup ke penyimpanan
  terpisah (lihat [DEPLOYMENT.md](DEPLOYMENT.md)).
- Hapus data peserta yang meminta penghapusan lewat tombol **Hapus permanen** (tercatat di audit log).
- Setelah keperluan pelaporan selesai, panitia sebaiknya menghapus/menganonimkan data sesuai kebijakan privasi.

## Troubleshooting

| Gejala | Penyebab & solusi |
|---|---|
| Pesan tetap "Antre" | Worker tidak berjalan (dashboard: *Worker ✗*) → jalankan `flask worker`; atau provider belum siap → `flask check-config`. Tombol **Proses antrean sekarang** menjalankan satu siklus manual. |
| Status berhenti di "Terkirim" | Webhook provider belum dikonfigurasi / bukan HTTPS publik. |
| Gagal `[400/132001]` (Meta) | Nama template/bahasa tidak cocok atau template belum disetujui. |
| Gagal `[400/131030]` (Meta) | Nomor penerima belum masuk daftar nomor uji (akun masih mode uji). |
| Gagal `131026` | Nomor tidak memakai WhatsApp — hubungi via email/contact person. |
| Sertifikat tidak terkirim | Peserta belum ditandai hadir, auto-send nonaktif, atau belum lewat waktu kirim. |
| "Sesi formulir kedaluwarsa" | Token CSRF habis karena sesi berakhir; muat ulang halaman. |
| Login terkunci | Tunggu 15 menit atau `flask create-admin <username>` untuk reset. |
