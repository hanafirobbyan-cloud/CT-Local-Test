"""Halaman publik: landing, pendaftaran, halaman peserta, sertifikat, verifikasi."""
from flask import (Blueprint, abort, flash, redirect, render_template, request, send_file, url_for)
from sqlalchemy import text

from ..extensions import db, limiter
from ..models import Certificate, Participant
from ..services import attendance, audit, certificates, files, notifications, registration
from ..services import settings_service as settings
from ..utils import timeutil
from ..utils.security import hash_ip

bp = Blueprint("public", __name__)
PUBLIC_MEDIA_KEYS = ("speaker_photo", "moderator_photo", "organizer_logo", "poster_image")


@bp.get("/")
def index():
    is_open, closed_reason = settings.registration_state()
    return render_template("public/index.html", agenda=settings.agenda_items(),
                           benefits=settings.benefit_items(), faqs=settings.faq_items(),
                           event_start=settings.event_start(), reg_open=is_open, closed_reason=closed_reason)


@bp.route("/daftar", methods=["GET", "POST"])
@limiter.limit("20/hour;5/minute", methods=["POST"])
def register():
    is_open, closed_reason = settings.registration_state()
    form, errors = {}, {}
    if request.method == "POST" and is_open:
        if request.form.get("website"):  # honeypot: hanya diisi bot
            return redirect(url_for(".index"))
        form = request.form
        data, errors = registration.validate(request.form)
        if not errors:
            try:
                p = registration.register(data, ip_hash=hash_ip())
            except registration.DuplicateRegistration as dup:
                label = "Email" if dup.field == "email" else "Nomor WhatsApp"
                errors[dup.field] = (f"{label} ini sudah terdaftar. Gunakan menu Cek Pendaftaran "
                                     "untuk mengirim ulang konfirmasi.")
            else:
                return redirect(url_for(".participant", token=p.access_token, baru=1))
    status = 400 if errors else 200
    return render_template("public/register.html", form=form, errors=errors, reg_open=is_open,
                           closed_reason=closed_reason, categories=Participant.CATEGORIES,
                           info_sources=registration.INFO_SOURCES,
                           event_start=settings.event_start()), status


def _participant_or_404(token: str) -> Participant:
    if not token or len(token) > 64:
        abort(404)
    p = db.session.query(Participant).filter_by(access_token=token).first()
    if not p:
        abort(404)
    return p


@bp.get("/peserta/<token>")
def participant(token):
    p = _participant_or_404(token)
    start = settings.event_start()
    now = timeutil.utcnow()
    show_zoom = p.status == "registered" and notifications.zoom_is_published()
    attendance_open = (settings.get("attendance_code_open") and bool(settings.get("attendance_code"))
                       and (not start or now >= start))
    cert = p.certificate if p.certificate and not p.certificate.revoked_at else None
    resp = render_template("public/participant.html", p=p, is_new=request.args.get("baru") == "1",
                           show_zoom=show_zoom, attendance_open=attendance_open, cert=cert,
                           event_start=start)
    return resp, 200, {"Referrer-Policy": "no-referrer"}


@bp.post("/peserta/<token>/presensi")
@limiter.limit("10 per 10 minutes")
def submit_attendance(token):
    p = _participant_or_404(token)
    ok, message = attendance.submit_code(p, request.form.get("code", ""))
    flash(message, "success" if ok else "error")
    return redirect(url_for(".participant", token=token))


@bp.post("/peserta/<token>/whatsapp")
@limiter.limit("10 per hour")
def whatsapp_preference(token):
    p = _participant_or_404(token)
    now = timeutil.utcnow()
    if request.form.get("action") == "stop":
        if p.wa_opted_out_at is None:
            notifications.opt_out_phone(p.phone)
        flash("Anda tidak akan menerima pesan WhatsApp lagi dari webinar ini.", "success")
    else:
        p.wa_consent, p.wa_consent_at, p.wa_opted_out_at = True, now, None
        audit.record("participant", "participant.wa_opt_in", "participant", p.public_id)
        flash("Terima kasih, notifikasi WhatsApp diaktifkan.", "success")
    return redirect(url_for(".participant", token=token))


@bp.route("/cek-pendaftaran", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def check_registration():
    sent = False
    if request.method == "POST":
        registration.resend_confirmation(request.form.get("identifier", ""))
        sent = True
    return render_template("public/check.html", sent=sent)


@bp.get("/sertifikat/<token>")
def certificate_download(token):
    if not token or len(token) > 64:
        abort(404)
    cert = db.session.query(Certificate).filter_by(download_token=token).first()
    if not cert or cert.revoked_at:
        abort(404)
    path = certificates.file_path(cert)
    safe_name = "".join(c for c in cert.participant.full_name if c.isalnum() or c == " ").strip().replace(" ", "_")
    return send_file(path, mimetype="application/pdf", as_attachment=request.args.get("unduh") == "1",
                     download_name=f"Sertifikat_{safe_name or 'Peserta'}.pdf", max_age=0)


@bp.get("/verifikasi/<code>")
def verify(code):
    cert = db.session.query(Certificate).filter_by(verify_code=code[:32]).first() if code else None
    return render_template("public/verify.html", cert=cert, event_start=settings.event_start()), \
        (200 if cert else 404)


@bp.get("/privasi")
def privacy():
    return render_template("public/privacy.html")


@bp.get("/media/<name>")
def media(name):
    if name not in {settings.get(key) for key in PUBLIC_MEDIA_KEYS}:
        abort(404)
    path = files.path_for(name)
    if not path:
        abort(404)
    return send_file(path, max_age=3600)


@bp.get("/robots.txt")
def robots():
    body = "User-agent: *\nDisallow: /admin\nDisallow: /peserta\nDisallow: /sertifikat\nDisallow: /api\n"
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}


@bp.get("/healthz")
@limiter.exempt
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:  # noqa: BLE001
        return {"status": "error", "database": False}, 503
