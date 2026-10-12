"""Validasi & penyimpanan pendaftaran peserta."""
import re
import unicodedata

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Participant
from ..utils import timeutil
from ..utils.phone import normalize_phone
from . import integrations, notifications
from . import settings_service as settings

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
NAME_PUNCT = set(" .,'-")
INFO_SOURCES = {
    "instagram": "Instagram", "whatsapp": "Grup/teman WhatsApp", "kampus": "Kampus/sekolah",
    "poster": "Poster/QR code", "lainnya": "Lainnya",
}


class DuplicateRegistration(Exception):
    def __init__(self, field: str):
        super().__init__(field)
        self.field = field


def clean_text(value, max_len: int) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")  # buang karakter kontrol
    return re.sub(r"\s+", " ", text).strip()[:max_len]


def _valid_name(name: str) -> bool:
    return 3 <= len(name) <= 120 and any(c.isalpha() for c in name) and \
        all(c.isalpha() or c in NAME_PUNCT for c in name)


def validate(form) -> tuple[dict, dict]:
    """Kembalikan (data_bersih, errors). errors berisi pesan per field (Bahasa Indonesia)."""
    errors: dict[str, str] = {}
    data = {
        "full_name": clean_text(form.get("full_name"), 120),
        "email": clean_text(form.get("email"), 254).lower(),
        "phone_raw": clean_text(form.get("phone"), 25),
        "category": clean_text(form.get("category"), 20),
        "institution": clean_text(form.get("institution"), 150),
        "student_id": clean_text(form.get("student_id"), 30),
        "study_program": clean_text(form.get("study_program"), 120),
        "city": clean_text(form.get("city"), 80),
        "info_source": clean_text(form.get("info_source"), 40),
        "privacy_consent": form.get("privacy_consent") in ("1", "on", True, "true"),
        "wa_consent": form.get("wa_consent") in ("1", "on", True, "true"),
    }
    if not _valid_name(data["full_name"]):
        errors["full_name"] = "Isi nama lengkap (3–120 huruf) sesuai yang akan tercetak di sertifikat."
    if not EMAIL_RE.match(data["email"]):
        errors["email"] = "Format email tidak valid."
    data["phone"] = normalize_phone(data["phone_raw"])
    if not data["phone"]:
        errors["phone"] = "Nomor WhatsApp tidak valid. Contoh: 081234567890."
    if data["category"] not in Participant.CATEGORIES:
        errors["category"] = "Pilih kategori peserta."
    if len(data["institution"]) < 2:
        errors["institution"] = "Isi nama sekolah/kampus/usaha/instansi."
    if data["category"] == "mahasiswa":
        if not re.fullmatch(r"[A-Za-z0-9.\-/]{3,30}", data["student_id"]):
            errors["student_id"] = "NIM wajib diisi untuk mahasiswa (keperluan poin SKEM)."
        if len(data["study_program"]) < 2:
            errors["study_program"] = "Program studi wajib diisi untuk mahasiswa."
    else:
        data["student_id"] = ""
        data["study_program"] = ""
    if data["info_source"] and data["info_source"] not in INFO_SOURCES:
        data["info_source"] = "lainnya"
    if not data["privacy_consent"]:
        errors["privacy_consent"] = "Anda perlu menyetujui kebijakan privasi untuk mendaftar."
    return data, errors


def find_existing(email: str, phone: str) -> Participant | None:
    return db.session.query(Participant).filter(
        or_(Participant.email == email, Participant.phone == phone)).first()


def register(data: dict, ip_hash: str | None = None, source: str = "web") -> Participant:
    existing = find_existing(data["email"], data["phone"])
    if existing:
        raise DuplicateRegistration("email" if existing.email == data["email"] else "phone")
    now = timeutil.utcnow()
    p = Participant(
        full_name=data["full_name"], email=data["email"], phone=data["phone"],
        category=data["category"], institution=data["institution"],
        student_id=data["student_id"] or None, study_program=data["study_program"] or None,
        city=data["city"] or None, info_source=data["info_source"] or None,
        privacy_consent_at=now, consent_version=settings.get("consent_version"),
        wa_consent=data["wa_consent"], wa_consent_at=now if data["wa_consent"] else None,
        registered_ip_hash=ip_hash,
    )
    db.session.add(p)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise DuplicateRegistration("email") from None
    if settings.get("send_registration_confirmation"):
        notifications.notify(p, "registration", dedupe_prefix=f"reg:{p.id}")
    integrations.emit("registration.created", {**integrations.participant_payload(p), "source": source})
    db.session.commit()
    return p


def resend_confirmation(identifier: str) -> None:
    """Kirim ulang konfirmasi ke kontak TERDAFTAR. Tidak membocorkan apakah data ada."""
    identifier = (identifier or "").strip()
    email = identifier.lower() if "@" in identifier else None
    phone = None if email else normalize_phone(identifier)
    if not email and not phone:
        return
    p = db.session.query(Participant).filter(
        Participant.email == email if email else Participant.phone == phone).first()
    if not p or p.status != "registered":
        return
    bucket = int(timeutil.utcnow().timestamp() // 900)  # maksimal sekali per 15 menit
    notifications.notify(p, "registration", dedupe_prefix=f"reg-resend:{p.id}:{bucket}")
    db.session.commit()
