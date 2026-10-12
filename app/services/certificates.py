"""Pembuatan e-sertifikat PDF (fpdf2) untuk peserta yang HADIR, serta pengirimannya."""
import io
import logging
import re
import unicodedata
from datetime import timedelta
from pathlib import Path

import segno
from flask import current_app
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from sqlalchemy import exists, func

from ..extensions import db
from ..models import Certificate, Message, Participant
from ..utils import timeutil
from . import audit, files, integrations, notifications
from . import settings_service as settings

log = logging.getLogger(__name__)
PAGE_W, PAGE_H = 297, 210
_NUMBER_TOKEN = re.compile(r"\{(\w+)(?::0(\d)d)?\}")
_LATIN_MAP = {"–": "-", "—": "-", "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...", "•": "-"}


def cert_dir() -> Path:
    path = Path(current_app.config["CERT_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def format_number(sequence: int, issued_at) -> str:
    local = timeutil.to_local(issued_at)
    values = {"tahun": local.year, "bulan": local.month, "urut": sequence}

    def repl(m):
        value = values.get(m.group(1))
        if value is None:
            return m.group(0)
        return str(value).zfill(int(m.group(2))) if m.group(2) else str(value)

    return _NUMBER_TOKEN.sub(repl, settings.get("cert_number_format") or "{urut}")[:80]


def verify_url(cert_or_code) -> str:
    code = cert_or_code if isinstance(cert_or_code, str) else cert_or_code.verify_code
    return f"{current_app.config['PUBLIC_BASE_URL']}/verifikasi/{code}"


def _rgb(hex_color: str, fallback=(30, 58, 138)) -> tuple[int, int, int]:
    value = (hex_color or "").lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    return fallback


def _latin(text: str) -> str:
    """Font bawaan PDF hanya mendukung Latin-1; unggah font TTF untuk aksara lain."""
    out = []
    for ch in text:
        ch = _LATIN_MAP.get(ch, ch)
        if len(ch) == 1 and ord(ch) > 255:
            ch = unicodedata.normalize("NFKD", ch).encode("latin-1", "ignore").decode("latin-1") or "?"
        out.append(ch)
    return "".join(out)


def render_pdf(name: str, number: str, verify_link: str) -> bytes:
    s = settings.get_all()
    primary, accent = _rgb(s["cert_primary_color"]), _rgb(s["cert_accent_color"], (245, 158, 11))
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_margins(0, 0, 0)
    pdf.add_page()

    font_path = files.path_for(s["cert_font"])
    if font_path:
        pdf.add_font("CertFont", "", str(font_path))
        family, bold, clean = "CertFont", "", (lambda t: t)
    else:
        family, bold, clean = "Helvetica", "B", _latin

    def text_line(y, text, size, style="", color=(55, 65, 81), spacing=0):
        pdf.set_font(family, style if style and bold else "", size)
        pdf.set_text_color(*color)
        pdf.set_char_spacing(spacing)
        pdf.set_xy(15, y)
        pdf.cell(PAGE_W - 30, size * 0.5, clean(text), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_char_spacing(0)

    background = files.path_for(s["cert_background"])
    if background:
        pdf.image(str(background), x=0, y=0, w=PAGE_W, h=PAGE_H)
    else:
        pdf.set_fill_color(*primary)
        pdf.rect(0, 0, PAGE_W, 7, style="F")
        pdf.set_fill_color(*accent)
        pdf.rect(0, PAGE_H - 7, PAGE_W, 7, style="F")
        pdf.set_draw_color(*primary)
        pdf.set_line_width(1.2)
        pdf.rect(12, 14, PAGE_W - 24, PAGE_H - 28)
        pdf.set_draw_color(*accent)
        pdf.set_line_width(0.4)
        pdf.rect(15, 17, PAGE_W - 30, PAGE_H - 34)

    logo = files.path_for(s["organizer_logo"])
    if logo:
        pdf.image(str(logo), x=PAGE_W / 2 - 11, y=s["cert_heading_y"] - 24, h=20, keep_aspect_ratio=True,
                  w=22)

    text_line(s["cert_heading_y"], s["cert_heading"], 34, "B", primary, spacing=3)
    text_line(s["cert_heading_y"] + 16, f"Nomor: {number}", 10, color=(107, 114, 128))
    text_line(s["cert_name_y"] - 13, s["cert_subheading"], 13)

    size = 30
    pdf.set_font(family, bold, size)
    while size > 16 and pdf.get_string_width(clean(name)) > 240:
        size -= 1
        pdf.set_font(family, bold, size)
    text_line(s["cert_name_y"], name, size, "B", primary)
    pdf.set_draw_color(*accent)
    pdf.set_line_width(0.8)
    pdf.line(PAGE_W / 2 - 75, s["cert_name_y"] + 17, PAGE_W / 2 + 75, s["cert_name_y"] + 17)

    ctx = {"judul": s["event_title"], "tema": s["event_theme"], "penyelenggara": s["organizer_name"],
           "tanggal": timeutil.format_indo_date(settings.event_start(), with_day=False), "nama": name}
    pdf.set_font(family, "", 13)
    pdf.set_text_color(55, 65, 81)
    pdf.set_xy(33, s["cert_body_y"])
    pdf.multi_cell(PAGE_W - 66, 7, clean(notifications.render(s["cert_body"], ctx)), align="C")

    signers = [(s[f"cert_sign{i}_name"], s[f"cert_sign{i}_role"], s[f"cert_sign{i}_image"]) for i in (1, 2)]
    signers = [sg for sg in signers if sg[0]]
    centers = {1: [PAGE_W / 2], 2: [PAGE_W * 0.3, PAGE_W * 0.7]}.get(len(signers), [])
    sign_y = s["cert_sign_y"]
    for (signer_name, role, image), cx in zip(signers, centers):
        img = files.path_for(image)
        if img:
            pdf.image(str(img), x=cx - 20, y=sign_y - 22, w=40, h=20, keep_aspect_ratio=True)
        pdf.set_draw_color(156, 163, 175)
        pdf.set_line_width(0.3)
        pdf.line(cx - 35, sign_y, cx + 35, sign_y)
        pdf.set_font(family, bold, 12)
        pdf.set_text_color(17, 24, 39)
        pdf.set_xy(cx - 45, sign_y + 2)
        pdf.cell(90, 6, clean(signer_name), align="C")
        pdf.set_font(family, "", 10)
        pdf.set_text_color(75, 85, 99)
        pdf.set_xy(cx - 45, sign_y + 8)
        pdf.cell(90, 5, clean(role), align="C")

    if s["organizer_name"]:
        text_line(PAGE_H - 26, f"Diselenggarakan oleh {s['organizer_name']}", 10, color=(75, 85, 99))

    if s["cert_show_qr"]:
        buf = io.BytesIO()
        segno.make(verify_link, error="m").save(buf, kind="png", scale=8, border=1)
        buf.seek(0)
        pdf.image(buf, x=22, y=PAGE_H - 46, w=22, h=22)
        pdf.set_font(family, "", 7)
        pdf.set_text_color(107, 114, 128)
        pdf.set_xy(46, PAGE_H - 33)
        pdf.multi_cell(80, 3.5, clean(f"Pindai untuk verifikasi keaslian:\n{verify_link}"))
    return bytes(pdf.output())


def preview_pdf() -> bytes:
    return render_pdf("Nama Peserta Contoh", format_number(1, timeutil.utcnow()), verify_url("contoh"))


def _write_file(cert: Certificate) -> None:
    pdf = render_pdf(cert.participant.full_name, cert.number, verify_url(cert))
    safe_number = re.sub(r"[^A-Za-z0-9_-]+", "-", cert.number)
    cert.file_name = f"{safe_number}-{cert.download_token[:8]}.pdf"
    (cert_dir() / cert.file_name).write_bytes(pdf)
    cert.generated_at = timeutil.utcnow()


def file_path(cert: Certificate) -> Path:
    path = cert_dir() / (cert.file_name or "")
    if not cert.file_name or not path.is_file():
        _write_file(cert)
        db.session.commit()
        path = cert_dir() / cert.file_name
    return path


def eligible_query():
    return db.session.query(Participant).filter(Participant.status == "registered",
                                                Participant.attended.is_(True))


def issue(p: Participant, actor: str, commit: bool = True) -> Certificate:
    if not (p.attended and p.status == "registered"):
        raise ValueError("Sertifikat hanya untuk peserta terdaftar yang hadir.")
    cert = p.certificate
    if cert and not cert.revoked_at:
        return cert
    if cert:  # pernah dicabut, kini hadir lagi -> aktifkan kembali
        cert.revoked_at = None
        cert.revoke_reason = None
    else:
        seq = (db.session.query(func.max(Certificate.sequence)).scalar() or 0) + 1
        now = timeutil.utcnow()
        cert = Certificate(participant=p, sequence=seq, number=format_number(seq, now), issued_at=now)
        db.session.add(cert)
        db.session.flush()
    _write_file(cert)
    audit.record(actor, "certificate.issue", "certificate", cert.number, {"participant": p.public_id},
                 commit=False)
    integrations.emit("certificate.issued", {**integrations.participant_payload(p), "number": cert.number,
                                             "verify_url": verify_url(cert)})
    if commit:
        db.session.commit()
    return cert


def issue_all(actor: str) -> int:
    count = 0
    for p in eligible_query().filter(~exists().where(
            (Certificate.participant_id == Participant.id) & Certificate.revoked_at.is_(None))).all():
        issue(p, actor, commit=False)
        count += 1
    db.session.commit()
    return count


def regenerate_all(actor: str) -> int:
    certs = db.session.query(Certificate).filter(Certificate.revoked_at.is_(None)).all()
    for cert in certs:
        _write_file(cert)
    audit.record(actor, "certificate.regenerate_all", details={"count": len(certs)}, commit=False)
    db.session.commit()
    return len(certs)


def revoke(cert: Certificate, reason: str, actor: str, commit: bool = True) -> None:
    cert.revoked_at = timeutil.utcnow()
    cert.revoke_reason = reason[:200]
    db.session.query(Message).filter_by(participant_id=cert.participant_id, purpose="certificate",
                                        status="queued").update({"status": "cancelled"})
    audit.record(actor, "certificate.revoke", "certificate", cert.number, {"reason": reason}, commit=False)
    if commit:
        db.session.commit()


def send_one(p: Participant, actor: str) -> int:
    cert = p.certificate
    if not cert or cert.revoked_at:
        return 0
    msgs = notifications.notify(p, "certificate",
                                dedupe_prefix=f"cert-manual:{cert.id}:{int(timeutil.utcnow().timestamp())}")
    audit.record(actor, "certificate.send", "certificate", cert.number, commit=False)
    db.session.commit()
    return len(msgs)


def auto_send_due() -> bool:
    end = settings.event_end()
    if not settings.get("cert_auto_send") or not end:
        return False
    return timeutil.utcnow() >= end + timedelta(minutes=settings.get("cert_send_after_minutes"))


def auto_tick() -> int:
    """Setelah acara + jeda: terbitkan & kirim sertifikat untuk setiap peserta hadir yang belum
    menerimanya. Peserta yang presensinya diverifikasi belakangan ikut diproses otomatis."""
    if not auto_send_due():
        return 0
    has_cert_msg = exists().where((Message.participant_id == Participant.id) &
                                  (Message.purpose == "certificate"))
    queued = 0
    for p in eligible_query().filter(~has_cert_msg).limit(500).all():
        cert = issue(p, "system:auto-certificate", commit=False)
        queued += len(notifications.notify(p, "certificate", dedupe_prefix=f"cert:{cert.id}"))
    db.session.commit()
    return queued


def stats() -> dict:
    issued = db.session.query(Certificate).filter(Certificate.revoked_at.is_(None)).count()
    sent = db.session.query(func.count(func.distinct(Message.participant_id))).filter(
        Message.purpose == "certificate", Message.status.in_(("sent", "delivered", "read"))).scalar()
    return {"eligible": eligible_query().count(), "issued": issued, "sent": sent,
            "revoked": db.session.query(Certificate).filter(Certificate.revoked_at.isnot(None)).count()}
