"""Antrean notifikasi (WhatsApp & email), kampanye massal, dan pelacakan status pengiriman.

Alur: enqueue() menyimpan baris `messages` berstatus "queued" -> worker memanggil
process_queue() -> provider mengirim -> status menjadi sent/failed -> webhook provider
memperbarui menjadi delivered/read/failed.
"""
import logging
import re
import time
from datetime import timedelta

from flask import current_app
from sqlalchemy import func, update

from ..extensions import db
from ..models import Campaign, Message, Participant
from ..utils import timeutil
from . import audit, email_service, integrations
from . import settings_service as settings
from .whatsapp import get_provider

log = logging.getLogger(__name__)

PURPOSES = ("registration", "zoom_link", "reminder", "certificate", "broadcast")
TEMPLATE_SETTING = {
    "registration": "msg_registration", "zoom_link": "msg_zoom_link", "reminder": "msg_reminder",
    "certificate": "msg_certificate", "broadcast": "msg_broadcast",
}
SUBJECTS = {
    "registration": "Konfirmasi Pendaftaran Webinar",
    "zoom_link": "Link Zoom Webinar",
    "reminder": "Pengingat Webinar",
    "certificate": "E-Certificate Webinar",
    "broadcast": "Informasi Webinar",
}
BACKOFF_MINUTES = [1, 5, 15, 60, 180]
STATUS_RANK = {"queued": 0, "sending": 0, "sent": 1, "delivered": 2, "read": 3}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def render(template: str, ctx: dict) -> str:
    """Ganti {placeholder} secara aman (tanpa str.format agar tidak bisa mengakses atribut objek)."""
    return _PLACEHOLDER.sub(lambda m: str(ctx.get(m.group(1), m.group(0))), template or "")


def participant_url(p: Participant) -> str:
    return f"{current_app.config['PUBLIC_BASE_URL']}/peserta/{p.access_token}"


def certificate_url(cert) -> str:
    return f"{current_app.config['PUBLIC_BASE_URL']}/sertifikat/{cert.download_token}"


def zoom_is_published() -> bool:
    return bool(settings.zoom_published_at() and settings.get("zoom_url"))


def build_context(p: Participant, campaign: Campaign | None = None) -> dict:
    start = settings.event_start()
    ctx = {
        "nama": p.full_name,
        "judul": settings.get("event_title"),
        "tema": settings.get("event_theme"),
        "tanggal": timeutil.format_indo_date(start),
        "waktu": settings.get("event_time_label"),
        "platform": settings.get("event_platform"),
        "link_peserta": participant_url(p),
        "kontak": f"{settings.get('contact_name')} ({settings.get('contact_phone')})",
        "penyelenggara": settings.get("organizer_name"),
        "link_zoom": "",
        "detail_zoom": "",
        "link_sertifikat": "",
        "pesan": (campaign.custom_text if campaign else "") or "",
    }
    if zoom_is_published():
        ctx["link_zoom"] = settings.get("zoom_url")
        details = []
        if settings.get("zoom_meeting_id"):
            details.append(f"Meeting ID: {settings.get('zoom_meeting_id')}")
        if settings.get("zoom_passcode"):
            details.append(f"Passcode: {settings.get('zoom_passcode')}")
        ctx["detail_zoom"] = " | ".join(details)
    cert = p.certificate
    if cert and not cert.revoked_at:
        ctx["link_sertifikat"] = certificate_url(cert)
    return ctx


def render_text(purpose: str, ctx: dict) -> str:
    text = render(settings.get(TEMPLATE_SETTING[purpose]), ctx)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def template_params(purpose: str, ctx: dict) -> list[str]:
    """Urutan parameter template Meta ({{1}}, {{2}}, ...). Lihat docs/WHATSAPP.md."""
    when = f"{ctx['tanggal']}, {ctx['waktu']}"
    return {
        "registration": [ctx["nama"], ctx["judul"], when, ctx["link_peserta"]],
        "zoom_link": [ctx["nama"], ctx["judul"], when, ctx["link_zoom"], ctx["detail_zoom"] or "-"],
        "reminder": [ctx["nama"], ctx["judul"], when, ctx["link_peserta"]],
        "certificate": [ctx["nama"], ctx["judul"], ctx["link_sertifikat"]],
        "broadcast": [ctx["nama"], ctx["pesan"]],
    }[purpose]


def channels_for(p: Participant) -> list[str]:
    if p.status != "registered":
        return []
    channels = []
    wa_ok = settings.get("notify_whatsapp") and p.can_receive_whatsapp
    if wa_ok:
        channels.append("whatsapp")
    # Email dipakai bila diaktifkan, atau sebagai cadangan bila peserta tidak bisa dihubungi via WA.
    if email_service.is_configured() and (settings.get("notify_email") or not wa_ok):
        channels.append("email")
    return channels


def enqueue(p: Participant, purpose: str, channel: str, *, campaign: Campaign | None = None,
            scheduled_at=None, dedupe_key: str | None = None) -> Message | None:
    if dedupe_key and db.session.query(Message.id).filter_by(dedupe_key=dedupe_key).first():
        return None
    now = timeutil.utcnow()
    msg = Message(participant=p, purpose=purpose, channel=channel, campaign=campaign,
                  dedupe_key=dedupe_key, scheduled_at=scheduled_at or now,
                  next_attempt_at=scheduled_at or now,
                  max_attempts=current_app.config["MESSAGE_MAX_ATTEMPTS"])
    db.session.add(msg)
    return msg


def notify(p: Participant, purpose: str, *, campaign: Campaign | None = None,
           dedupe_prefix: str | None = None) -> list[Message]:
    created = []
    for channel in channels_for(p):
        key = f"{dedupe_prefix}:{channel}" if dedupe_prefix else None
        msg = enqueue(p, purpose, channel, campaign=campaign, dedupe_key=key)
        if msg:
            created.append(msg)
    return created


# ---- Pemrosesan antrean ----------------------------------------------------

def _finish(msg: Message, status: str, error: str | None = None) -> None:
    msg.status = status
    msg.last_error = error
    if status == "failed":
        msg.failed_at = timeutil.utcnow()


def _deliver(msg: Message, provider) -> None:
    p = msg.participant
    now = timeutil.utcnow()
    if p.status != "registered":
        return _finish(msg, "cancelled", "Pendaftaran peserta dibatalkan.")
    if msg.channel == "whatsapp" and not p.can_receive_whatsapp:
        return _finish(msg, "skipped", "Peserta tidak memberi izin WhatsApp atau telah berhenti berlangganan.")
    ctx = build_context(p, msg.campaign)
    if msg.purpose == "zoom_link" and not ctx["link_zoom"]:
        return _finish(msg, "cancelled", "Link Zoom belum/tidak lagi dipublikasikan.")
    if msg.purpose == "certificate" and not ctx["link_sertifikat"]:
        return _finish(msg, "cancelled", "Sertifikat belum terbit atau telah dicabut.")

    text = render_text(msg.purpose, ctx)
    msg.body = text
    msg.attempts += 1
    if msg.channel == "whatsapp":
        msg.provider = provider.name
        result = provider.send(p.phone, msg.purpose, text, template_params(msg.purpose, ctx))
    else:
        msg.provider = "smtp"
        subject = f"{SUBJECTS[msg.purpose]}: {ctx['judul']}"
        result = email_service.send_email(p.email, subject, text)

    if result.ok:
        msg.status = "sent"
        msg.sent_at = now
        msg.provider_message_id = result.provider_message_id
        msg.last_error = None
        return None
    msg.last_error = result.error
    if result.retryable and msg.attempts < msg.max_attempts:
        delay = BACKOFF_MINUTES[min(msg.attempts - 1, len(BACKOFF_MINUTES) - 1)]
        msg.status = "queued"
        msg.next_attempt_at = now + timedelta(minutes=delay)
    else:
        _finish(msg, "failed", result.error)
    return None


def process_queue(limit: int = 100) -> dict:
    """Kirim pesan yang jatuh tempo. Aman dijalankan beberapa worker sekaligus (klaim atomik)."""
    now = timeutil.utcnow()
    provider = get_provider()
    channels = []
    if provider:
        channels.append("whatsapp")
    if email_service.is_configured():
        channels.append("email")
    stats = {"processed": 0, "sent": 0, "failed": 0, "retry": 0, "other": 0}
    if not channels:
        return stats
    ids = [row[0] for row in db.session.query(Message.id).filter(
        Message.status == "queued", Message.next_attempt_at <= now, Message.scheduled_at <= now,
        Message.channel.in_(channels)).order_by(Message.id).limit(limit).all()]
    delay = current_app.config["WA_SEND_DELAY_MS"] / 1000
    for message_id in ids:
        claimed = db.session.execute(
            update(Message).where(Message.id == message_id, Message.status == "queued")
            .values(status="sending", updated_at=timeutil.utcnow())).rowcount
        db.session.commit()
        if not claimed:
            continue
        msg = db.session.get(Message, message_id)
        try:
            _deliver(msg, provider)
        except Exception as exc:  # noqa: BLE001 - jangan biarkan pesan macet di status "sending"
            log.exception("Gagal memproses pesan %s", message_id)
            msg.status = "queued" if msg.attempts < msg.max_attempts else "failed"
            msg.last_error = f"Kesalahan internal: {exc}"
            msg.next_attempt_at = timeutil.utcnow() + timedelta(minutes=5)
        db.session.commit()
        stats["processed"] += 1
        key = {"sent": "sent", "failed": "failed", "queued": "retry"}.get(msg.status, "other")
        stats[key] += 1
        if msg.channel == "whatsapp" and delay:
            time.sleep(delay)
    return stats


def release_stuck(minutes: int = 10) -> int:
    """Kembalikan pesan yang tertahan di 'sending' (mis. worker mati di tengah jalan)."""
    cutoff = timeutil.utcnow() - timedelta(minutes=minutes)
    count = db.session.execute(
        update(Message).where(Message.status == "sending", Message.updated_at < cutoff)
        .values(status="queued", next_attempt_at=timeutil.utcnow())).rowcount
    db.session.commit()
    return count


def retry(msg: Message, actor: str) -> bool:
    if msg.status not in ("failed", "cancelled", "skipped"):
        return False
    msg.status = "queued"
    msg.attempts = 0
    msg.next_attempt_at = timeutil.utcnow()
    msg.failed_at = None
    audit.record(actor, "message.retry", "message", msg.id, commit=False)
    db.session.commit()
    return True


def retry_all_failed(actor: str) -> int:
    count = db.session.execute(
        update(Message).where(Message.status == "failed")
        .values(status="queued", attempts=0, failed_at=None, next_attempt_at=timeutil.utcnow())).rowcount
    audit.record(actor, "message.retry_all_failed", details={"count": count}, commit=False)
    db.session.commit()
    return count


def cancel_queued(purpose: str | None = None, campaign_id: int | None = None) -> int:
    stmt = update(Message).where(Message.status == "queued")
    if purpose:
        stmt = stmt.where(Message.purpose == purpose)
    if campaign_id:
        stmt = stmt.where(Message.campaign_id == campaign_id)
    count = db.session.execute(stmt.values(status="cancelled", last_error="Dibatalkan admin/sistem.")).rowcount
    db.session.commit()
    return count


# ---- Status dari webhook provider -------------------------------------------

def apply_status(provider_message_id: str, status: str, error: str | None = None) -> bool:
    msg = db.session.query(Message).filter_by(provider_message_id=provider_message_id).first()
    if not msg:
        return False
    now = timeutil.utcnow()
    if status == "failed":
        if msg.status not in ("delivered", "read"):
            msg.status = "failed"
            msg.failed_at = now
            msg.last_error = error or "Gagal terkirim (laporan provider)."
    elif status in STATUS_RANK and STATUS_RANK[status] > STATUS_RANK.get(msg.status, -1):
        msg.status = status
        if status == "delivered":
            msg.delivered_at = now
        elif status == "read":
            msg.read_at = now
            msg.delivered_at = msg.delivered_at or now
    db.session.commit()
    return True


def opt_out_phone(phone: str) -> bool:
    p = db.session.query(Participant).filter_by(phone=phone).first()
    if not p or p.wa_opted_out_at:
        return False
    p.wa_opted_out_at = timeutil.utcnow()
    db.session.query(Message).filter_by(participant_id=p.id, channel="whatsapp", status="queued") \
        .update({"status": "skipped", "last_error": "Peserta berhenti berlangganan WhatsApp."})
    audit.record("participant", "participant.wa_opt_out", "participant", p.public_id, commit=False)
    db.session.commit()
    return True


# ---- Kampanye ----------------------------------------------------------------

def create_campaign(name: str, purpose: str, audience: str, scheduled_at, actor: str,
                    custom_text: str | None = None) -> Campaign:
    campaign = Campaign(name=name[:150], purpose=purpose, audience=audience, custom_text=custom_text,
                        scheduled_at=scheduled_at or timeutil.utcnow(), created_by=actor)
    db.session.add(campaign)
    db.session.flush()
    audit.record(actor, "campaign.create", "campaign", campaign.id,
                 {"purpose": purpose, "audience": audience, "scheduled_at": campaign.scheduled_at},
                 commit=False)
    db.session.commit()
    return campaign


def audience_query(audience: str):
    q = db.session.query(Participant).filter(Participant.status == "registered")
    if audience == "attended":
        q = q.filter(Participant.attended.is_(True))
    elif audience == "not_attended":
        q = q.filter(Participant.attended.is_(False))
    return q


def run_campaign(campaign: Campaign) -> int:
    count = 0
    for p in audience_query(campaign.audience).order_by(Participant.id).yield_per(200):
        if campaign.purpose == "certificate" and not (p.certificate and not p.certificate.revoked_at):
            continue
        for channel in channels_for(p):
            if enqueue(p, campaign.purpose, channel, campaign=campaign,
                       dedupe_key=f"c{campaign.id}:{p.id}:{channel}"):
                count += 1
    campaign.status = "done"
    campaign.enqueued_count = count
    campaign.processed_at = timeutil.utcnow()
    db.session.commit()
    integrations.emit("campaign.enqueued", {"id": campaign.id, "purpose": campaign.purpose,
                                            "messages": count}, commit=True)
    return count


def run_due_campaigns() -> int:
    now = timeutil.utcnow()
    due = db.session.query(Campaign).filter(Campaign.status == "scheduled",
                                            Campaign.scheduled_at <= now).order_by(Campaign.id).all()
    for campaign in due:
        run_campaign(campaign)
    return len(due)


def cancel_campaign(campaign: Campaign, actor: str) -> None:
    if campaign.status == "scheduled":
        campaign.status = "cancelled"
    cancel_queued(campaign_id=campaign.id)
    audit.record(actor, "campaign.cancel", "campaign", campaign.id)


# ---- Statistik ---------------------------------------------------------------

def stats() -> dict:
    by_status = dict(db.session.query(Message.status, func.count(Message.id)).group_by(Message.status).all())
    by_purpose = {}
    for purpose, status, count in db.session.query(Message.purpose, Message.status, func.count(Message.id)) \
            .group_by(Message.purpose, Message.status).all():
        by_purpose.setdefault(purpose, {})[status] = count
    return {"by_status": by_status, "by_purpose": by_purpose, "total": sum(by_status.values())}
