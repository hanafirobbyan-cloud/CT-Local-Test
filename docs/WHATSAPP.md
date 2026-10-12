# Integrasi WhatsApp

Sistem mendukung dua provider (pilih lewat `WHATSAPP_PROVIDER` di `.env`):

| Provider | Status | Kapan dipakai |
|---|---|---|
| `meta` | **WhatsApp Business Platform (Cloud API) resmi Meta** | Direkomendasikan untuk produksi |
| `fonnte` | Gateway pihak ketiga (menautkan perangkat WhatsApp biasa) | Bila belum bisa memakai API resmi; ada risiko pemblokiran nomor |
| `console` | Hanya menulis ke log | Development/uji coba; ditolak otomatis di produksi |
| `disabled` | Tidak mengirim | Pesan tetap antre dan terkirim setelah provider diaktifkan |

## Cara kerja

1. Setiap notifikasi masuk ke tabel `messages` (status `queued`).
2. Worker (`flask worker`) mengirim, lalu menandai `sent` atau menjadwalkan ulang bila gagal sementara
   (backoff 1, 5, 15, 60 menit; maks. `MESSAGE_MAX_ATTEMPTS`). Gagal permanen → `failed`.
3. Webhook provider memperbarui status menjadi `delivered` / `read` / `failed`.
4. Admin melihat semuanya di **Pesan & Notifikasi** dan dapat mengulang pesan gagal.

WhatsApp **hanya** dikirim ke peserta yang mencentang izin WhatsApp dan belum berhenti berlangganan.
Peserta dapat berhenti kapan saja dengan membalas `BERHENTI`/`STOP` (diproses lewat webhook) atau
lewat tombol di halaman peserta. Peserta tanpa izin WA menerima email (bila SMTP aktif) dan tetap dapat
melihat semua informasi di halaman peserta.

## A. WhatsApp Business Platform (Meta Cloud API)

### 1. Persiapan akun
1. Buat/akses **Meta Business Portfolio** di business.facebook.com dan verifikasi bisnis (disarankan;
   tanpa verifikasi batas pengiriman awal rendah).
2. Di developers.facebook.com → **Create App** → tipe *Business* → tambahkan produk **WhatsApp**.
3. Di **WhatsApp → API Setup**: tambahkan nomor telepon bisnis Anda (nomor yang **belum** terdaftar di
   aplikasi WhatsApp biasa), verifikasi via SMS/telepon. Catat **Phone number ID**.
4. Buat **System User** (Business Settings → Users → System users), beri akses ke app & WhatsApp
   account, lalu **Generate token** dengan izin `whatsapp_business_messaging` dan
   `whatsapp_business_management`. Token ini permanen — jangan pakai token sementara 24 jam.
5. Catat **App Secret** (App settings → Basic).

Isi `.env`:
```
WHATSAPP_PROVIDER=meta
WA_META_PHONE_NUMBER_ID=1234567890
WA_META_ACCESS_TOKEN=EAAG...
WA_META_APP_SECRET=abcdef...
WA_META_VERIFY_TOKEN=<string acak buatan Anda>
```

### 2. Ajukan template pesan
Pesan yang dikirim lebih dulu oleh bisnis **wajib** memakai template yang disetujui Meta. Buat di
**WhatsApp Manager → Message templates**, kategori **Utility**, bahasa **Indonesian (id)**.
Nama dan urutan variabel **harus sama** dengan di bawah (atau ubah nama di `.env`). Meta tidak
mengizinkan variabel di awal/akhir isi pesan, karena itu setiap template diakhiri teks.

**`webinar_registrasi`** — konfirmasi pendaftaran
```
Halo {{1}}, pendaftaran Anda untuk webinar "{{2}}" telah kami terima.
Jadwal: {{3}}.
Link Zoom akan dikirim menjelang acara. Halaman peserta Anda: {{4}}
Simpan pesan ini sebagai bukti pendaftaran.
```
Footer: `Balas BERHENTI untuk berhenti menerima pesan.`
Contoh nilai: `Siti` · `Penerapan Logika Digital untuk Membangun Startup dan UMKM` · `Minggu, 01 November 2026, 16.00 WIB – selesai` · `https://domain-anda/peserta/abc`

**`webinar_link_zoom`** — link Zoom
```
Halo {{1}}, berikut link Zoom webinar "{{2}}" ({{3}}):
Link: {{4}}
Detail: {{5}}
Mohon tidak membagikan link ini kepada pihak lain. Sampai jumpa!
```
{{5}} berisi Meeting ID & passcode (atau "-" bila kosong).

**`webinar_pengingat`** — pengingat
```
Halo {{1}}, mengingatkan webinar "{{2}}" akan berlangsung pada {{3}}.
Halaman peserta: {{4}}
Sampai jumpa di acara!
```

**`webinar_sertifikat`** — e-sertifikat
```
Halo {{1}}, terima kasih telah hadir di webinar "{{2}}".
E-certificate Anda dapat diunduh di: {{3}}
Semoga bermanfaat!
```

**`webinar_pengumuman`** — pengumuman (opsional)
```
Halo {{1}}, informasi dari panitia webinar:
{{2}}
Terima kasih.
```
Catatan: parameter template tidak boleh berisi baris baru; sistem otomatis menggantinya dengan " · ".
Meta dapat mengklasifikasikan ulang template pengumuman sebagai *Marketing* (biaya berbeda).

### 3. Webhook status pengiriman & opt-out
Di **WhatsApp → Configuration → Webhook**:
- Callback URL: `https://domain-anda/webhooks/whatsapp/meta`
- Verify token: nilai `WA_META_VERIFY_TOKEN`
- Subscribe field: **messages**

Semua POST diverifikasi dengan header `X-Hub-Signature-256` (HMAC SHA-256 memakai App Secret);
tanpa `WA_META_APP_SECRET` webhook ditolak. Webhook wajib HTTPS publik — untuk uji lokal pakai
tunnel (mis. `cloudflared tunnel --url http://localhost:5000` atau ngrok).

### 4. Uji
`flask check-config` → `WhatsApp provider meta — siap`. Daftar dengan nomor Anda sendiri, jalankan
worker, lalu lihat status di dashboard. Saat nomor bisnis masih dalam mode uji, Meta hanya
mengizinkan pengiriman ke nomor yang terdaftar sebagai penerima uji.

### Kebijakan yang perlu dipatuhi
- Kirim hanya kepada peserta yang memberi persetujuan (opt-in) — formulir menyimpan waktu & versi persetujuan.
- Hormati permintaan berhenti (`BERHENTI`/`STOP`) — sistem memprosesnya otomatis.
- Gunakan template kategori yang sesuai (Utility untuk informasi acara), jangan kirim promosi tanpa izin.
- Perhatikan batas pengiriman (messaging limit) akun Anda; pantau *quality rating* di WhatsApp Manager.
- Biaya per percakapan/pesan mengikuti tarif Meta untuk Indonesia (cek halaman pricing Meta terbaru).

## B. Fonnte (alternatif)
1. Daftar di fonnte.com, tautkan perangkat (scan QR), salin **token** perangkat.
2. `.env`: `WHATSAPP_PROVIDER=fonnte`, `FONNTE_TOKEN=...`, `FONNTE_WEBHOOK_SECRET=<string acak>`.
3. Di dashboard Fonnte (pengaturan device) isi:
   - Webhook status: `https://domain-anda/webhooks/whatsapp/fonnte/status?token=<FONNTE_WEBHOOK_SECRET>`
   - Webhook pesan masuk: `https://domain-anda/webhooks/whatsapp/fonnte/incoming?token=<FONNTE_WEBHOOK_SECRET>`
4. Isi pesan memakai template teks yang dapat diedit di **Pesan → Edit template pesan**.

Risiko: Fonnte memakai akun WhatsApp biasa sehingga tidak tunduk pada jaminan WhatsApp Business
Platform; pengiriman massal berpotensi membuat nomor diblokir. Atur `WA_SEND_DELAY_MS` (mis. 3000–5000)
dan pastikan semua penerima telah memberi izin. Format payload webhook Fonnte dapat berubah — periksa
dokumentasi Fonnte terbaru bila status tidak terbarui.

## C. Menambah provider lain
Buat kelas di `app/services/whatsapp/` yang mewarisi `WhatsAppProvider` (metode `is_configured()` dan
`send(to, purpose, text, template_params)` → `SendResult`), daftarkan di `PROVIDERS` pada
`app/services/whatsapp/__init__.py`, lalu (opsional) tambahkan route webhook status di
`app/blueprints/webhooks.py` yang memanggil `notifications.apply_status(provider_message_id, status)`.
