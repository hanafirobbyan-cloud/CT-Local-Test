# REST API v1 & Webhook Integrasi

Base URL: `https://domain-anda/api/v1`. Format JSON. Spesifikasi lengkap: [openapi.yaml](openapi.yaml)
(bisa dibuka di editor.swagger.io).

## Autentikasi
- Endpoint publik: tanpa token, dengan rate limit.
- Endpoint `/admin/*`: header `Authorization: Bearer <token>`. Token didefinisikan di `.env`:
  `API_TOKENS=telegram_bot:<token-acak-min-24-karakter>,crm:<token-lain>`. Nama sebelum `:` tercatat
  di audit log. Buat token: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## Endpoint publik

### `GET /event`
Detail acara (tanpa link Zoom).
```json
{"title": "Penerapan Logika Digital untuk Membangun Startup dan UMKM", "theme": "Growth Startup dan UMKM",
 "start": "2026-11-01T09:00:00Z", "time_label": "16.00 WIB – selesai", "platform": "Online via Zoom Meeting",
 "speaker": {"name": "Fadel Rasyid", "role": "Narasumber"}, "agenda": [...], "benefits": [...],
 "registration": {"open": true, "reason": null}}
```

### `POST /registrations`
Mendaftarkan peserta (dipakai bot WhatsApp/Telegram, form pihak ketiga). Validasi sama dengan situs.
Bot **harus** menanyakan persetujuan secara eksplisit kepada pengguna sebelum mengirim `true`.
```json
{"full_name": "Andi Saputra", "email": "andi@example.com", "phone": "081377778888",
 "category": "startup", "institution": "Startup X", "student_id": null, "study_program": null,
 "city": "Semarang", "info_source": "whatsapp", "privacy_consent": true, "wa_consent": true}
```
`category`: `pelajar | mahasiswa | startup | umkm | lainnya` (mahasiswa wajib `student_id` & `study_program`).

| Status | Arti |
|---|---|
| 201 | `{"id": "...", "status": "registered", "participant_url": "https://.../peserta/<token>"}` |
| 403 | Pendaftaran ditutup |
| 409 | Email/nomor WA sudah terdaftar |
| 422 | `{"error": "validation_error", "fields": {"email": "Format email tidak valid."}}` |
| 429 | Rate limit |

`participant_url` bersifat rahasia — kirimkan hanya kepada pendaftar itu sendiri.

## Endpoint admin (Bearer token)
| Metode | Path | Keterangan |
|---|---|---|
| GET | `/admin/stats` | Total pendaftar, hadir, per kategori, status pesan, sertifikat |
| GET | `/admin/participants?q=&category=&attended=true\|false&status=&page=&per_page=` | Daftar peserta (maks 200/halaman) |
| GET | `/admin/participants/{id}` | Detail peserta (`id` = `public_id`) |
| POST | `/admin/participants/{id}/attendance` | `{"attended": true, "minutes": 75}` — tandai hadir/batal |
| GET | `/admin/messages?status=failed&purpose=zoom_link&limit=100` | Log pesan |

Contoh:
```bash
curl -H "Authorization: Bearer $TOKEN" https://domain-anda/api/v1/admin/stats
```

## Webhook keluar (event)
Isi `INTEGRATION_WEBHOOK_URL` (dan `INTEGRATION_WEBHOOK_SECRET`). Worker mengirim POST JSON:
```json
{"event": "registration.created", "occurred_at": "2026-10-12T02:31:31Z",
 "data": {"id": "9f1c...", "full_name": "Rina", "category": "mahasiswa", "institution": "...", "attended": false, "source": "web"}}
```
Header: `X-Webinar-Event`, `X-Webinar-Signature: sha256=<HMAC-SHA256(body, secret)>`.
Event: `registration.created`, `attendance.marked`, `certificate.issued` (+ `number`, `verify_url`),
`zoom.published` (tanpa link), `campaign.enqueued`. Respons non-2xx dicoba ulang dengan backoff
eksponensial hingga 6 kali. Data kontak (email/WA) sengaja tidak dikirim; ambil via API admin bila perlu.

Verifikasi tanda tangan (Python):
```python
import hmac, hashlib
expected = "sha256=" + hmac.new(SECRET.encode(), request_body, hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, request.headers["X-Webinar-Signature"])
```

## Webhook masuk (provider WhatsApp)
| Path | Provider | Keamanan |
|---|---|---|
| `GET/POST /webhooks/whatsapp/meta` | Meta Cloud API | Verify token + `X-Hub-Signature-256` |
| `POST /webhooks/whatsapp/fonnte/status?token=` | Fonnte status | Token rahasia di query |
| `POST /webhooks/whatsapp/fonnte/incoming?token=` | Fonnte pesan masuk (opt-out) | Token rahasia di query |

## Lain-lain
- `GET /healthz` — health check.
- Logika bisnis ada di `app/services/*` dan dapat dipanggil langsung dari kode Python (mis. bot yang
  berjalan di proses yang sama): `registration.validate()` / `registration.register()`,
  `attendance.mark()`, `certificates.issue()`, `notifications.notify()`.
