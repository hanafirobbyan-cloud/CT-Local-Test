"""Pengaturan yang dapat diubah admin (konten acara, link Zoom, template pesan & sertifikat).

Nilai default di bawah diambil dari TOR "Kerangka Acuan Kerja Webinar". Detail yang tidak
ada di TOR (penyelenggara, penandatangan sertifikat, link Zoom, dsb.) dibiarkan kosong dan
diisi admin melalui dashboard — jangan mengisinya dengan data karangan.
"""
import json

from flask import g

from ..extensions import db
from ..models import Setting
from ..utils import timeutil

TOR_FAQ = """Siapa saja yang dapat mengikuti webinar ini?
Webinar terbuka untuk pelajar, mahasiswa, serta penggiat Startup dan pelaku UMKM.

Kapan dan di mana webinar dilaksanakan?
Minggu, 01 November 2026, pukul 16.00 WIB sampai selesai, secara online melalui Zoom Meeting.

Kapan saya menerima link Zoom?
Link Zoom tidak dipublikasikan secara umum. Link dikirim ke WhatsApp (dan/atau email) peserta terdaftar menjelang acara dimulai, dan juga dapat dilihat di halaman peserta Anda setelah dipublikasikan panitia.

Bagaimana cara mendapatkan e-certificate?
E-certificate resmi diberikan kepada peserta yang hadir dan tercatat dalam presensi. Tautan e-certificate dikirim setelah webinar selesai.

Apakah mahasiswa mendapatkan poin SKEM?
Poin SKEM (Sistem Kredit Kegiatan Mahasiswa) diberikan bagi mahasiswa. Pastikan nama lengkap, NIM, dan institusi diisi dengan benar saat mendaftar. Untuk ketentuan lebih lanjut, silakan hubungi contact person.

Apa yang saya dapatkan selain e-certificate?
Wawasan praktis serta template strategi growth yang siap diimplementasikan.

Saya sudah mendaftar tetapi tidak menerima pesan konfirmasi.
Gunakan menu "Cek Pendaftaran" untuk mengirim ulang konfirmasi ke WhatsApp/email terdaftar, atau hubungi contact person."""

TOR_AGENDA = """16.00 – 16.15 | 15 menit | Pembukaan dan pembacaan tata tertib | Moderator
16.15 – 17.15 | 60 menit | Pemaparan materi | Narasumber (Fadel Rasyid)
17.15 – 17.45 | 30 menit | Sesi tanya jawab dan diskusi interaktif | Moderator dan narasumber
17.45 – 17.50 | 5 menit | Sesi foto bersama | Panitia
17.50 – 18.00 | 10 menit | Penutup | Moderator"""

TOR_BENEFITS = """E-certificate resmi | Sertifikat elektronik untuk peserta yang hadir dan tercatat dalam presensi.
Poin SKEM | Poin Sistem Kredit Kegiatan Mahasiswa (SKEM) bagi mahasiswa.
Knowledge & Toolkit | Wawasan praktis serta template strategi growth yang siap diimplementasikan."""

PRIVACY_TEXT = """Data yang kami kumpulkan: nama lengkap, email, nomor WhatsApp, kategori peserta, institusi, serta NIM dan program studi (khusus mahasiswa, untuk keperluan poin SKEM).

Tujuan penggunaan: verifikasi pendaftaran, pengiriman informasi dan link Zoom webinar, pencatatan kehadiran, penerbitan e-certificate, dan pelaporan poin SKEM.

Pesan WhatsApp hanya dikirim kepada peserta yang memberikan persetujuan. Anda dapat berhenti menerima pesan kapan saja dengan membalas BERHENTI atau melalui halaman peserta.

Data tidak dijual atau dibagikan kepada pihak lain di luar keperluan penyelenggaraan webinar, dan hanya dapat diakses oleh panitia yang berwenang. Untuk permintaan akses, koreksi, atau penghapusan data, hubungi contact person."""

MSG_REGISTRATION = """Halo {nama}, pendaftaran Anda untuk webinar "{judul}" telah kami terima.

Tanggal: {tanggal}
Waktu: {waktu}
Platform: {platform}

Link Zoom akan dikirim menjelang acara dimulai. Halaman peserta Anda: {link_peserta}

Balas BERHENTI jika tidak ingin menerima pesan WhatsApp terkait webinar ini."""

MSG_ZOOM = """Halo {nama}, berikut link Zoom webinar "{judul}" ({tanggal}, {waktu}):

{link_zoom}
{detail_zoom}

Mohon tidak membagikan link ini kepada pihak lain. Isi presensi melalui halaman peserta: {link_peserta}"""

MSG_REMINDER = """Halo {nama}, mengingatkan webinar "{judul}" akan berlangsung pada {tanggal}, {waktu} via {platform}.

Link Zoom akan dikirim menjelang acara. Halaman peserta: {link_peserta}"""

MSG_CERTIFICATE = """Halo {nama}, terima kasih telah hadir di webinar "{judul}".

E-certificate Anda dapat diunduh di:
{link_sertifikat}"""

MSG_BROADCAST = """Halo {nama},

{pesan}

— Panitia webinar "{judul}\""""

# key -> (tipe, default). Tipe: str, text, bool, int, datetime (waktu lokal ISO), file
SCHEMA: dict[str, tuple[str, object]] = {
    # Konten acara (TOR)
    "event_title": ("str", "Penerapan Logika Digital untuk Membangun Startup dan UMKM"),
    "event_theme": ("str", "Growth Startup dan UMKM"),
    "event_start": ("datetime", "2026-11-01T16:00"),
    "event_end": ("datetime", "2026-11-01T18:00"),
    "event_time_label": ("str", "16.00 WIB – selesai"),
    "event_platform": ("str", "Online via Zoom Meeting"),
    "event_background": ("text", "Perkembangan ekosistem digital memberikan peluang besar bagi pelaku Startup dan UMKM untuk bertumbuh secara eksponensial. Memahami logika digital, strategi pertumbuhan (growth strategy), serta pemanfaatan teknologi secara sistematis menjadi kunci utama agar bisnis lokal dan pemula mampu bersaing di pasar modern."),
    "event_objective": ("text", "Menghimpun partisipasi aktif dari pelajar, mahasiswa, serta pelaku UMKM/Startup, sekaligus membekali mereka dengan wawasan praktis mengenai pemanfaatan logika digital untuk mengakselerasi pertumbuhan bisnis di era digital."),
    "audience_text": ("str", "Pelajar, mahasiswa, serta penggiat Startup dan pelaku UMKM"),
    "benefits": ("text", TOR_BENEFITS),
    "agenda": ("text", TOR_AGENDA),
    "faq": ("text", TOR_FAQ),
    "speaker_name": ("str", "Fadel Rasyid"),
    "speaker_role": ("str", "Narasumber"),
    "speaker_bio": ("text", "Menyampaikan pemaparan materi terkait Potensi Logika Digital serta strategi mendorong growth Startup dan UMKM."),
    "speaker_photo": ("file", ""),
    "moderator_name": ("str", "Nayla Tazkiyah Fadli"),
    "moderator_role": ("str", "Moderator"),
    "moderator_bio": ("text", "Memandu alur diskusi, memimpin sesi tanya jawab (Q&A), dan menyimpulkan poin materi."),
    "moderator_photo": ("file", ""),
    "contact_name": ("str", "Nayla"),
    "contact_phone": ("str", "082136190243"),
    "organizer_name": ("str", ""),
    "organizer_logo": ("file", ""),
    "poster_image": ("file", ""),
    "privacy_text": ("text", PRIVACY_TEXT),
    "consent_version": ("str", "2026-10"),

    # Pendaftaran
    "registration_open": ("bool", True),
    "registration_close_at": ("datetime", ""),
    "registration_capacity": ("int", 0),  # 0 = tanpa batas

    # Zoom
    "zoom_url": ("str", ""),
    "zoom_meeting_id": ("str", ""),
    "zoom_passcode": ("str", ""),
    "zoom_publish_lead_minutes": ("int", 30),
    "zoom_auto_publish": ("bool", False),
    "zoom_published_at": ("str", ""),  # ISO UTC; diisi sistem saat publikasi

    # Presensi
    "attendance_code": ("str", ""),
    "attendance_code_open": ("bool", False),
    "attendance_min_minutes": ("int", 0),

    # Notifikasi
    "notify_whatsapp": ("bool", True),
    "notify_email": ("bool", False),
    "send_registration_confirmation": ("bool", True),
    "msg_registration": ("text", MSG_REGISTRATION),
    "msg_zoom_link": ("text", MSG_ZOOM),
    "msg_reminder": ("text", MSG_REMINDER),
    "msg_certificate": ("text", MSG_CERTIFICATE),
    "msg_broadcast": ("text", MSG_BROADCAST),

    # Sertifikat
    "cert_auto_send": ("bool", True),
    "cert_send_after_minutes": ("int", 60),  # dihitung dari event_end
    "cert_number_format": ("str", "WLD-{tahun}-{urut:04d}"),
    "cert_heading": ("str", "SERTIFIKAT"),
    "cert_subheading": ("str", "Diberikan kepada"),
    "cert_body": ("text", 'atas partisipasinya sebagai Peserta dalam Webinar "{judul}" dengan tema "{tema}" yang diselenggarakan secara online pada {tanggal}.'),
    "cert_sign1_name": ("str", ""),
    "cert_sign1_role": ("str", ""),
    "cert_sign1_image": ("file", ""),
    "cert_sign2_name": ("str", ""),
    "cert_sign2_role": ("str", ""),
    "cert_sign2_image": ("file", ""),
    "cert_background": ("file", ""),
    "cert_font": ("file", ""),
    "cert_primary_color": ("str", "#1E3A8A"),
    "cert_accent_color": ("str", "#F59E0B"),
    "cert_heading_y": ("int", 38),
    "cert_name_y": ("int", 82),
    "cert_body_y": ("int", 104),
    "cert_sign_y": ("int", 150),
    "cert_show_qr": ("bool", True),

    # Sistem
    "worker_heartbeat": ("str", ""),
    "last_backup_at": ("str", ""),
}


PLACEHOLDER_HELP = ("Placeholder: {nama} {judul} {tema} {tanggal} {waktu} {platform} {link_peserta} "
                    "{link_zoom} {detail_zoom} {link_sertifikat} {kontak} {penyelenggara} {pesan}")

# key -> (label, bantuan) untuk form admin
LABELS: dict[str, tuple[str, str]] = {
    "event_title": ("Judul resmi", ""),
    "event_theme": ("Tema", ""),
    "event_start": ("Waktu mulai", "Dipakai untuk hitung mundur, jendela publikasi Zoom, dan presensi."),
    "event_end": ("Perkiraan waktu selesai", "TOR: 16.00 WIB – selesai. Dipakai untuk jadwal pengiriman sertifikat."),
    "event_time_label": ("Label waktu", "Teks waktu yang ditampilkan, mis. 16.00 WIB – selesai"),
    "event_platform": ("Platform", ""),
    "event_background": ("Latar belakang", ""),
    "event_objective": ("Tujuan webinar", ""),
    "audience_text": ("Sasaran peserta", ""),
    "benefits": ("Benefit", "Satu benefit per baris: Judul | Deskripsi"),
    "agenda": ("Rundown", "Satu sesi per baris: Waktu | Durasi | Sesi | Penanggung jawab"),
    "faq": ("FAQ", "Baris pertama = pertanyaan, baris berikutnya = jawaban. Pisahkan tiap FAQ dengan satu baris kosong."),
    "speaker_name": ("Nama narasumber", ""),
    "speaker_role": ("Peran narasumber", ""),
    "speaker_bio": ("Deskripsi narasumber", "TOR hanya memuat tugas narasumber; tambahkan profil resmi bila tersedia."),
    "speaker_photo": ("Foto narasumber", "PNG/JPG, opsional"),
    "moderator_name": ("Nama moderator", ""),
    "moderator_role": ("Peran moderator", ""),
    "moderator_bio": ("Deskripsi moderator", ""),
    "moderator_photo": ("Foto moderator", "PNG/JPG, opsional"),
    "contact_name": ("Nama contact person", ""),
    "contact_phone": ("Nomor contact person", ""),
    "organizer_name": ("Nama penyelenggara", "Tidak tercantum di TOR — wajib diisi panitia. Tampil di footer & sertifikat."),
    "organizer_logo": ("Logo penyelenggara", "PNG/JPG, tampil di header & sertifikat"),
    "poster_image": ("Poster acara", "PNG/JPG, opsional, tampil di halaman utama"),
    "registration_open": ("Pendaftaran dibuka", ""),
    "registration_close_at": ("Pendaftaran ditutup otomatis pada", "Kosongkan bila tidak ada batas waktu."),
    "registration_capacity": ("Kuota peserta", "0 = tanpa batas. Sesuaikan dengan kapasitas akun Zoom."),
    "privacy_text": ("Kebijakan privasi", "Tinjau dan sesuaikan dengan kebijakan penyelenggara."),
    "consent_version": ("Versi persetujuan", "Ubah bila teks kebijakan privasi diubah secara material."),
    "attendance_code": ("Kode presensi", "Diumumkan moderator saat acara, diisi peserta di halaman peserta."),
    "attendance_code_open": ("Presensi dibuka", "Peserta hanya dapat mengisi setelah acara dimulai."),
    "attendance_min_minutes": ("Durasi minimum (menit)", "Untuk impor laporan Zoom. 0 = cukup tercatat masuk."),
    "notify_whatsapp": ("Kirim via WhatsApp", "Hanya ke peserta yang memberi izin dan belum berhenti berlangganan."),
    "notify_email": ("Kirim juga via email", "Email selalu dipakai sebagai cadangan bila WA tidak tersedia (butuh SMTP)."),
    "send_registration_confirmation": ("Kirim konfirmasi pendaftaran", ""),
    "msg_registration": ("Pesan konfirmasi pendaftaran", PLACEHOLDER_HELP),
    "msg_zoom_link": ("Pesan link Zoom", PLACEHOLDER_HELP),
    "msg_reminder": ("Pesan pengingat", PLACEHOLDER_HELP),
    "msg_certificate": ("Pesan e-sertifikat", PLACEHOLDER_HELP),
    "msg_broadcast": ("Pesan pengumuman", PLACEHOLDER_HELP + " — {pesan} berisi teks pengumuman."),
    "cert_auto_send": ("Kirim sertifikat otomatis", "Setelah acara selesai + jeda, sertifikat diterbitkan & dikirim ke peserta yang hadir."),
    "cert_send_after_minutes": ("Jeda setelah acara selesai (menit)", ""),
    "cert_number_format": ("Format nomor sertifikat", "Wajib memuat {urut}. Tersedia {tahun} {bulan} {urut:04d}"),
    "cert_heading": ("Judul sertifikat", ""),
    "cert_subheading": ("Teks sebelum nama", ""),
    "cert_body": ("Teks isi", "Placeholder: {judul} {tema} {tanggal} {penyelenggara} {nama}"),
    "cert_sign1_name": ("Penandatangan 1 — nama", ""),
    "cert_sign1_role": ("Penandatangan 1 — jabatan", ""),
    "cert_sign1_image": ("Penandatangan 1 — gambar tanda tangan", "PNG transparan disarankan"),
    "cert_sign2_name": ("Penandatangan 2 — nama", "Opsional"),
    "cert_sign2_role": ("Penandatangan 2 — jabatan", ""),
    "cert_sign2_image": ("Penandatangan 2 — gambar tanda tangan", ""),
    "cert_background": ("Gambar latar sertifikat", "A4 landscape (mis. 3508×2480 px). Bila diisi, bingkai bawaan tidak digambar."),
    "cert_font": ("Font kustom (.ttf)", "Opsional — wajib bila nama peserta memakai aksara non-Latin."),
    "cert_primary_color": ("Warna utama", "Hex, mis. #1E3A8A"),
    "cert_accent_color": ("Warna aksen", "Hex, mis. #F59E0B"),
    "cert_heading_y": ("Posisi judul (mm dari atas)", ""),
    "cert_name_y": ("Posisi nama (mm)", ""),
    "cert_body_y": ("Posisi teks isi (mm)", ""),
    "cert_sign_y": ("Posisi garis tanda tangan (mm)", ""),
    "cert_show_qr": ("Tampilkan QR verifikasi", ""),
}


def _cache() -> dict:
    if "settings_cache" not in g:
        g.settings_cache = {s.key: s.value for s in db.session.query(Setting).all()}
    return g.settings_cache


def get(key: str):
    if key not in SCHEMA:
        raise KeyError(f"Pengaturan tidak dikenal: {key}")
    raw = _cache().get(key)
    if raw is None:
        return SCHEMA[key][1]
    try:
        return json.loads(raw)
    except ValueError:
        return SCHEMA[key][1]


def get_all() -> dict:
    return {key: get(key) for key in SCHEMA}


def set_many(values: dict, actor: str = "system") -> None:
    for key, value in values.items():
        if key not in SCHEMA:
            raise KeyError(f"Pengaturan tidak dikenal: {key}")
        row = db.session.get(Setting, key)
        encoded = json.dumps(value, ensure_ascii=False)
        if row is None:
            db.session.add(Setting(key=key, value=encoded, updated_by=actor))
        else:
            row.value = encoded
            row.updated_by = actor
        _cache()[key] = encoded
    db.session.commit()


def coerce(key: str, raw):
    """Ubah input form (string) menjadi tipe yang sesuai skema."""
    kind = SCHEMA[key][0]
    if kind == "bool":
        return raw in (True, "1", "on", "true", "yes", "ya")
    if kind == "int":
        try:
            return max(0, int(str(raw).strip() or 0))
        except ValueError:
            return SCHEMA[key][1]
    text = "" if raw is None else str(raw)
    if kind == "str":
        return text.strip()[:500]
    if kind == "datetime":
        text = text.strip()
        return text if not text or timeutil.parse_local(text) else SCHEMA[key][1]
    return text.replace("\r\n", "\n").strip()[:20000]


# ---- Helper turunan --------------------------------------------------------

def event_start():
    return timeutil.parse_local(get("event_start"))


def event_end():
    return timeutil.parse_local(get("event_end")) or event_start()


def zoom_published_at():
    value = get("zoom_published_at")
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def zoom_publish_window_opens():
    from datetime import timedelta
    start = event_start()
    return start - timedelta(minutes=get("zoom_publish_lead_minutes")) if start else None


def agenda_items() -> list[dict]:
    items = []
    for line in get("agenda").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if not parts[0]:
            continue
        parts += [""] * (4 - len(parts))
        items.append({"time": parts[0], "duration": parts[1], "session": parts[2], "pic": parts[3]})
    return items


def benefit_items() -> list[dict]:
    items = []
    for line in get("benefits").splitlines():
        title, _, desc = line.partition("|")
        if title.strip():
            items.append({"title": title.strip(), "desc": desc.strip()})
    return items


def faq_items() -> list[dict]:
    items = []
    for block in get("faq").replace("\r\n", "\n").split("\n\n"):
        lines = [line for line in block.strip().splitlines() if line.strip()]
        if lines:
            items.append({"q": lines[0].strip(), "a": " ".join(line.strip() for line in lines[1:])})
    return items


def registration_state() -> tuple[bool, str]:
    """(terbuka?, alasan bila tertutup)."""
    from ..models import Participant
    if not get("registration_open"):
        return False, "Pendaftaran sedang ditutup oleh panitia."
    close_at = timeutil.parse_local(get("registration_close_at"))
    if close_at and timeutil.utcnow() >= close_at:
        return False, "Masa pendaftaran telah berakhir."
    capacity = get("registration_capacity")
    if capacity:
        count = db.session.query(Participant).filter_by(status="registered").count()
        if count >= capacity:
            return False, "Kuota peserta sudah terpenuhi."
    return True, ""


def setup_warnings() -> list[str]:
    """Detail yang belum diisi admin (tidak tersedia di TOR)."""
    warnings = []
    if not get("organizer_name"):
        warnings.append("Nama penyelenggara belum diisi (tidak tercantum di TOR) — dipakai di sertifikat & footer.")
    if not get("cert_sign1_name"):
        warnings.append("Penandatangan sertifikat belum diisi.")
    if not get("zoom_url"):
        warnings.append("Link Zoom belum diisi.")
    return warnings
