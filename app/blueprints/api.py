"""REST API v1 untuk integrasi bot & layanan pihak ketiga. Dokumentasi: docs/API.md & docs/openapi.yaml."""
from functools import wraps

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, or_

from ..extensions import db, limiter
from ..models import Message, Participant
from ..services import attendance, certificates, notifications, registration
from ..services import settings_service as settings
from ..utils import timeutil
from ..utils.security import hash_ip, match_api_token

bp = Blueprint("api", __name__)


def require_token(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(error="unauthorized", message="Header Authorization: Bearer <token> wajib."), 401
        name = match_api_token(header[7:].strip())
        if not name:
            return jsonify(error="unauthorized", message="Token tidak valid."), 401
        g.api_client = name
        return view(*args, **kwargs)
    return wrapper


def participant_json(p: Participant, full: bool = True) -> dict:
    data = {
        "id": p.public_id, "full_name": p.full_name, "category": p.category,
        "institution": p.institution, "status": p.status, "attended": p.attended,
        "attendance_method": p.attendance_method, "registered_at": p.created_at.isoformat() + "Z",
    }
    if full:
        data.update({
            "email": p.email, "phone": p.phone, "student_id": p.student_id, "study_program": p.study_program,
            "city": p.city, "wa_consent": p.wa_consent, "wa_opted_out": p.wa_opted_out_at is not None,
            "attendance_minutes": p.attendance_minutes,
            "certificate_number": p.certificate.number if p.certificate and not p.certificate.revoked_at else None,
        })
    return data


# ---- Publik --------------------------------------------------------------------

@bp.get("/event")
def event():
    start, end = settings.event_start(), settings.event_end()
    is_open, reason = settings.registration_state()
    return jsonify({
        "title": settings.get("event_title"), "theme": settings.get("event_theme"),
        "start": start.isoformat() + "Z" if start else None, "end": end.isoformat() + "Z" if end else None,
        "time_label": settings.get("event_time_label"), "platform": settings.get("event_platform"),
        "speaker": {"name": settings.get("speaker_name"), "role": settings.get("speaker_role")},
        "moderator": {"name": settings.get("moderator_name"), "role": settings.get("moderator_role")},
        "agenda": settings.agenda_items(), "benefits": settings.benefit_items(),
        "contact": {"name": settings.get("contact_name"), "phone": settings.get("contact_phone")},
        "registration": {"open": is_open, "reason": reason or None},
    })


@bp.post("/registrations")
@limiter.limit("20/hour;5/minute")
def create_registration():
    is_open, reason = settings.registration_state()
    if not is_open:
        return jsonify(error="registration_closed", message=reason), 403
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="invalid_json", message="Body harus JSON object."), 400
    form = {k: payload.get(k) for k in ("full_name", "email", "phone", "category", "institution",
                                        "student_id", "study_program", "city", "info_source")}
    form["privacy_consent"] = "1" if payload.get("privacy_consent") is True else ""
    form["wa_consent"] = "1" if payload.get("wa_consent") is True else ""
    data, errors = registration.validate(form)
    if errors:
        return jsonify(error="validation_error", fields=errors), 422
    try:
        p = registration.register(data, ip_hash=hash_ip(), source="api")
    except registration.DuplicateRegistration as dup:
        return jsonify(error="duplicate", field=dup.field,
                       message="Email atau nomor WhatsApp sudah terdaftar."), 409
    return jsonify({"id": p.public_id, "status": p.status,
                    "participant_url": notifications.participant_url(p)}), 201


# ---- Admin (butuh token) -------------------------------------------------------

@bp.get("/admin/stats")
@require_token
def admin_stats():
    base = db.session.query(Participant).filter_by(status="registered")
    by_cat = dict(db.session.query(Participant.category, func.count(Participant.id))
                  .filter_by(status="registered").group_by(Participant.category).all())
    return jsonify({
        "registered": base.count(), "attended": base.filter(Participant.attended.is_(True)).count(),
        "by_category": by_cat, "messages": notifications.stats()["by_status"],
        "certificates": certificates.stats(), "generated_at": timeutil.utcnow().isoformat() + "Z",
    })


@bp.get("/admin/participants")
@require_token
def admin_participants():
    q = db.session.query(Participant)
    term = (request.args.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        q = q.filter(or_(Participant.full_name.ilike(like), Participant.email.ilike(like),
                         Participant.phone.ilike(like), Participant.institution.ilike(like)))
    if request.args.get("category") in Participant.CATEGORIES:
        q = q.filter_by(category=request.args["category"])
    if request.args.get("attended") in ("true", "false"):
        q = q.filter(Participant.attended.is_(request.args["attended"] == "true"))
    if request.args.get("status") in ("registered", "cancelled"):
        q = q.filter_by(status=request.args["status"])
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(200, max(1, request.args.get("per_page", 50, type=int)))
    total = q.count()
    items = q.order_by(Participant.id).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({"total": total, "page": page, "per_page": per_page,
                    "items": [participant_json(p) for p in items]})


@bp.get("/admin/participants/<public_id>")
@require_token
def admin_participant(public_id):
    p = db.session.query(Participant).filter_by(public_id=public_id).first()
    if not p:
        return jsonify(error="not_found"), 404
    return jsonify(participant_json(p))


@bp.post("/admin/participants/<public_id>/attendance")
@require_token
def admin_attendance(public_id):
    p = db.session.query(Participant).filter_by(public_id=public_id).first()
    if not p:
        return jsonify(error="not_found"), 404
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload.get("attended"), bool):
        return jsonify(error="validation_error", message="Field 'attended' (boolean) wajib."), 422
    minutes = payload.get("minutes") if isinstance(payload.get("minutes"), int) else None
    attendance.mark(p, payload["attended"], "api", f"api:{g.api_client}", minutes=minutes)
    return jsonify(participant_json(p))


@bp.get("/admin/messages")
@require_token
def admin_messages():
    q = db.session.query(Message)
    if request.args.get("status"):
        q = q.filter_by(status=request.args["status"])
    if request.args.get("purpose"):
        q = q.filter_by(purpose=request.args["purpose"])
    limit = min(500, max(1, request.args.get("limit", 100, type=int)))
    items = q.order_by(Message.id.desc()).limit(limit).all()
    return jsonify({"items": [{
        "id": m.id, "participant_id": m.participant.public_id, "channel": m.channel, "purpose": m.purpose,
        "status": m.status, "attempts": m.attempts, "last_error": m.last_error,
        "sent_at": m.sent_at.isoformat() + "Z" if m.sent_at else None,
        "delivered_at": m.delivered_at.isoformat() + "Z" if m.delivered_at else None,
    } for m in items]})
