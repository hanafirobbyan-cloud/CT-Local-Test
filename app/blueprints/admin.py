"""Dashboard admin. Semua route (kecuali login) mewajibkan sesi admin yang valid."""
import csv
import io
import math
from collections import OrderedDict
from datetime import datetime, timedelta

import segno
from flask import (Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from sqlalchemy import func, or_

from ..extensions import db, limiter
from ..models import AdminUser, AuditLog, Campaign, Certificate, Message, Participant
from ..services import (attendance, audit, certificates, email_service, files, notifications, registration,
                        scheduler, zoom)
from ..services import settings_service as settings
from ..services.whatsapp import provider_status
from ..utils import timeutil
from ..utils.security import csv_safe

bp = Blueprint("admin", __name__)

EVENT_KEYS = [
    "event_title", "event_theme", "event_start", "event_end", "event_time_label", "event_platform",
    "event_background", "event_objective", "audience_text", "benefits", "agenda", "faq",
    "speaker_name", "speaker_role", "speaker_bio", "speaker_photo",
    "moderator_name", "moderator_role", "moderator_bio", "moderator_photo",
    "contact_name", "contact_phone", "organizer_name", "organizer_logo", "poster_image",
    "registration_open", "registration_close_at", "registration_capacity", "privacy_text", "consent_version",
]
NOTIFY_KEYS = ["notify_whatsapp", "notify_email", "send_registration_confirmation", "msg_registration",
               "msg_zoom_link", "msg_reminder", "msg_certificate", "msg_broadcast"]
CERT_KEYS = ["cert_auto_send", "cert_send_after_minutes", "cert_number_format", "cert_heading",
             "cert_subheading", "cert_body", "cert_sign1_name", "cert_sign1_role", "cert_sign1_image",
             "cert_sign2_name", "cert_sign2_role", "cert_sign2_image", "cert_background", "cert_font",
             "cert_primary_color", "cert_accent_color", "cert_heading_y", "cert_name_y", "cert_body_y",
             "cert_sign_y", "cert_show_qr"]
ATTENDANCE_KEYS = ["attendance_code", "attendance_code_open", "attendance_min_minutes"]
PER_PAGE = 25


# ---- Autentikasi -------------------------------------------------------------

@bp.before_request
def load_admin():
    g.admin = None
    admin_id = session.get("admin_id")
    if admin_id:
        user = db.session.get(AdminUser, admin_id)
        if user and user.is_active and session.get("admin_nonce") == user.session_nonce:
            g.admin = user
        else:
            session.clear()
    if request.endpoint == "admin.login":
        return None
    if g.admin is None:
        return redirect(url_for("admin.login", next=request.path))
    return None


def actor() -> str:
    return f"admin:{g.admin.username}"


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes", methods=["POST"])
def login():
    if g.admin:
        return redirect(url_for(".dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()[:64]
        password = request.form.get("password", "")[:200]
        user = db.session.query(AdminUser).filter_by(username=username).first()
        now = timeutil.utcnow()
        if user and user.locked_until and user.locked_until > now:
            audit.record(f"login:{username}", "admin.login_blocked")
            error = "Akun dikunci sementara karena terlalu banyak percobaan gagal. Coba lagi nanti."
        elif user and user.is_active and user.check_password(password):
            user.failed_logins = 0
            user.locked_until = None
            user.last_login_at = now
            session.clear()
            session["admin_id"] = user.id
            session["admin_nonce"] = user.session_nonce
            session.permanent = True
            audit.record(f"admin:{user.username}", "admin.login")
            target = request.args.get("next", "")
            return redirect(target if target.startswith("/admin") and "//" not in target
                            else url_for(".dashboard"))
        else:
            if user:
                user.failed_logins += 1
                if user.failed_logins >= current_app.config["ADMIN_MAX_FAILED_LOGINS"]:
                    user.locked_until = now + timedelta(minutes=current_app.config["ADMIN_LOCKOUT_MINUTES"])
                    user.failed_logins = 0
            audit.record(f"login:{username or '-'}", "admin.login_failed")
            error = "Username atau kata sandi salah."
    return render_template("admin/login.html", error=error), (401 if error else 200)


@bp.post("/logout")
def logout():
    audit.record(actor(), "admin.logout")
    session.clear()
    flash("Anda telah keluar.", "success")
    return redirect(url_for(".login"))


@bp.route("/akun", methods=["GET", "POST"])
def account():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        if not g.admin.check_password(current):
            flash("Kata sandi saat ini salah.", "error")
        elif len(new) < 12 or new != request.form.get("confirm_password"):
            flash("Kata sandi baru minimal 12 karakter dan konfirmasi harus sama.", "error")
        else:
            g.admin.set_password(new)
            session["admin_nonce"] = g.admin.session_nonce
            audit.record(actor(), "admin.password_change")
            flash("Kata sandi berhasil diubah. Sesi lain otomatis keluar.", "success")
            return redirect(url_for(".account"))
    return render_template("admin/account.html")


# ---- Helper ------------------------------------------------------------------

def paginate(query, page: int, per_page: int = PER_PAGE) -> dict:
    total = query.count()
    pages = max(1, math.ceil(total / per_page))
    page = min(max(1, page), pages)
    return {"items": query.offset((page - 1) * per_page).limit(per_page).all(), "page": page,
            "pages": pages, "total": total}


def save_settings(keys: list[str]) -> bool:
    values = {}
    try:
        for key in keys:
            kind = settings.SCHEMA[key][0]
            if kind == "file":
                if request.form.get(f"remove_{key}"):
                    values[key] = ""
                upload = request.files.get(key)
                if upload and upload.filename:
                    values[key] = files.save_upload(upload, "font" if key == "cert_font" else "image")
            elif kind == "bool":
                values[key] = settings.coerce(key, request.form.get(key))
            elif key in request.form:
                values[key] = settings.coerce(key, request.form[key])
    except files.UploadError as exc:
        flash(str(exc), "error")
        return False
    if "event_start" in values and not values["event_start"]:
        flash("Waktu mulai acara wajib diisi.", "error")
        return False
    if "cert_number_format" in values and "{urut" not in values["cert_number_format"]:
        flash("Format nomor sertifikat harus memuat {urut} (mis. WLD-{tahun}-{urut:04d}).", "error")
        return False
    settings.set_many(values, actor())
    audit.record(actor(), "settings.update", details={"keys": sorted(values)})
    flash("Pengaturan disimpan.", "success")
    return True


def participants_query(args):
    q = db.session.query(Participant)
    term = (args.get("q") or "").strip()[:100]
    if term:
        like = f"%{term}%"
        q = q.filter(or_(Participant.full_name.ilike(like), Participant.email.ilike(like),
                         Participant.phone.ilike(like), Participant.institution.ilike(like),
                         Participant.student_id.ilike(like)))
    if args.get("category") in Participant.CATEGORIES:
        q = q.filter(Participant.category == args["category"])
    if args.get("attended") == "yes":
        q = q.filter(Participant.attended.is_(True))
    elif args.get("attended") == "no":
        q = q.filter(Participant.attended.is_(False))
    if args.get("wa") == "consent":
        q = q.filter(Participant.wa_consent.is_(True), Participant.wa_opted_out_at.is_(None))
    elif args.get("wa") == "no":
        q = q.filter(or_(Participant.wa_consent.is_(False), Participant.wa_opted_out_at.isnot(None)))
    status = args.get("status", "registered")
    if status in ("registered", "cancelled"):
        q = q.filter(Participant.status == status)
    return q


def _heartbeat_age():
    beat = settings.get("worker_heartbeat")
    if not beat:
        return None
    try:
        return (timeutil.utcnow() - datetime.fromisoformat(beat)).total_seconds()
    except ValueError:
        return None


# ---- Dashboard ---------------------------------------------------------------

@bp.get("/")
def dashboard():
    reg = db.session.query(Participant).filter_by(status="registered")
    total = reg.count()
    attended_count = reg.filter(Participant.attended.is_(True)).count()
    by_category = dict(db.session.query(Participant.category, func.count(Participant.id))
                       .filter_by(status="registered").group_by(Participant.category).all())

    today_local = timeutil.to_local(timeutil.utcnow()).date()
    days = OrderedDict((today_local - timedelta(days=i), 0) for i in range(13, -1, -1))
    since = timeutil.utcnow() - timedelta(days=15)
    for (created,) in db.session.query(Participant.created_at).filter(Participant.created_at >= since):
        day = timeutil.to_local(created).date()
        if day in days:
            days[day] += 1
    max_day = max(days.values()) or 1

    wa_name, wa_ready = provider_status()
    return render_template(
        "admin/dashboard.html", total=total, attended=attended_count, by_category=by_category,
        categories=Participant.CATEGORIES, days=days, max_day=max_day,
        today_count=days[today_local], msg=notifications.stats(), certs=certificates.stats(),
        wa_name=wa_name, wa_ready=wa_ready, email_ready=email_service.is_configured(),
        heartbeat_age=_heartbeat_age(), warnings=settings.setup_warnings(),
        zoom_published=settings.zoom_published_at(), window_opens=settings.zoom_publish_window_opens(),
        event_start=settings.event_start(), status_labels=Message.STATUS_LABELS,
        purpose_labels=Message.PURPOSE_LABELS,
        consent_count=reg.filter(Participant.wa_consent.is_(True), Participant.wa_opted_out_at.is_(None)).count(),
    )


@bp.get("/qr-pendaftaran.png")
def registration_qr():
    buf = io.BytesIO()
    segno.make(f"{current_app.config['PUBLIC_BASE_URL']}/daftar", error="m").save(buf, kind="png", scale=12, border=2)
    buf.seek(0)
    return send_file(buf, mimetype="image/png", as_attachment=request.args.get("unduh") == "1",
                     download_name="qr-pendaftaran-webinar.png")


# ---- Peserta -----------------------------------------------------------------

@bp.get("/peserta")
def participants():
    result = paginate(participants_query(request.args).order_by(Participant.id.desc()),
                      request.args.get("page", 1, type=int))
    return render_template("admin/participants.html", result=result, args=request.args,
                           categories=Participant.CATEGORIES)


@bp.get("/peserta/export.csv")
def export_participants():
    rows = participants_query(request.args).order_by(Participant.id).all()
    out = io.StringIO()
    out.write("﻿")  # BOM agar Excel membaca UTF-8 dengan benar
    writer = csv.writer(out)
    writer.writerow(["No", "ID", "Nama Lengkap", "Email", "WhatsApp", "Kategori", "Institusi", "NIM",
                     "Program Studi", "Kota", "Sumber Info", "Status", "Izin WA", "Berhenti WA", "Hadir",
                     "Metode Presensi", "Durasi (menit)", "No. Sertifikat", f"Terdaftar ({timeutil.tz_label()})"])
    for i, p in enumerate(rows, 1):
        cert = p.certificate.number if p.certificate and not p.certificate.revoked_at else ""
        writer.writerow([csv_safe(v) for v in [
            i, p.public_id, p.full_name, p.email, p.phone, p.category_label, p.institution, p.student_id,
            p.study_program, p.city, p.info_source, p.status, "Ya" if p.wa_consent else "Tidak",
            "Ya" if p.wa_opted_out_at else "", "Ya" if p.attended else "Tidak", p.attendance_method,
            p.attendance_minutes, cert, timeutil.fmt_local(p.created_at)]])
    audit.record(actor(), "participants.export", details={"count": len(rows), "filters": dict(request.args)})
    stamp = timeutil.to_local(timeutil.utcnow()).strftime("%Y%m%d-%H%M")
    return Response(out.getvalue(), content_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=peserta-webinar-{stamp}.csv"})


def _get_participant(pid: int) -> Participant:
    p = db.session.get(Participant, pid)
    if not p:
        abort(404)
    return p


@bp.get("/peserta/<int:pid>")
def participant_detail(pid):
    p = _get_participant(pid)
    msgs = p.messages.order_by(Message.id.desc()).limit(50).all()
    return render_template("admin/participant_detail.html", p=p, msgs=msgs, categories=Participant.CATEGORIES,
                           status_labels=Message.STATUS_LABELS, purpose_labels=Message.PURPOSE_LABELS,
                           zoom_published=notifications.zoom_is_published(),
                           participant_url=notifications.participant_url(p))


@bp.post("/peserta/<int:pid>/edit")
def participant_edit(pid):
    p = _get_participant(pid)
    form = request.form.to_dict()
    form["privacy_consent"] = "1"
    data, errors = registration.validate(form)
    if not errors:
        clash = db.session.query(Participant).filter(
            Participant.id != p.id, or_(Participant.email == data["email"], Participant.phone == data["phone"])).first()
        if clash:
            errors["email"] = f"Email/nomor WA sudah dipakai peserta lain ({clash.full_name})."
    if errors:
        for message in errors.values():
            flash(message, "error")
        return redirect(url_for(".participant_detail", pid=pid))
    before = {"full_name": p.full_name, "email": p.email, "phone": p.phone}
    for field in ("full_name", "email", "phone", "category", "institution", "city"):
        setattr(p, field, data[field] or None if field == "city" else data[field])
    p.student_id = data["student_id"] or None
    p.study_program = data["study_program"] or None
    audit.record(actor(), "participant.edit", "participant", p.public_id, {"before": before})
    flash("Data peserta diperbarui. Jika nama berubah, buat ulang sertifikatnya.", "success")
    return redirect(url_for(".participant_detail", pid=pid))


@bp.post("/peserta/<int:pid>/aksi")
def participant_action(pid):
    p = _get_participant(pid)
    action = request.form.get("action")
    who = actor()
    if action == "attend":
        attendance.mark(p, True, "manual", who)
        flash("Ditandai hadir.", "success")
    elif action == "unattend":
        attendance.mark(p, False, "manual", who)
        flash("Status hadir dibatalkan (sertifikat aktif ikut dicabut).", "success")
    elif action in ("cancel", "reactivate"):
        p.status = "cancelled" if action == "cancel" else "registered"
        audit.record(who, f"participant.{action}", "participant", p.public_id)
        flash("Status pendaftaran diperbarui.", "success")
    elif action == "delete":
        audit.record(who, "participant.delete", "participant", p.public_id, {"name": p.full_name}, commit=False)
        if p.certificate and p.certificate.file_name:
            (certificates.cert_dir() / p.certificate.file_name).unlink(missing_ok=True)
        db.session.delete(p)
        db.session.commit()
        flash("Data peserta dihapus permanen.", "success")
        return redirect(url_for(".participants"))
    elif action == "resend_confirmation":
        n = len(notifications.notify(p, "registration",
                                     dedupe_prefix=f"reg-admin:{p.id}:{int(timeutil.utcnow().timestamp())}"))
        audit.record(who, "message.resend_confirmation", "participant", p.public_id)
        flash(f"{n} pesan konfirmasi masuk antrean." if n else "Peserta tidak memiliki kanal yang dapat dihubungi.",
              "success" if n else "error")
    elif action == "send_zoom":
        if not notifications.zoom_is_published():
            flash("Link Zoom belum dipublikasikan.", "error")
        else:
            n = len(notifications.notify(p, "zoom_link",
                                         dedupe_prefix=f"zoom-admin:{p.id}:{int(timeutil.utcnow().timestamp())}"))
            audit.record(who, "message.send_zoom_individual", "participant", p.public_id)
            flash(f"{n} pesan link Zoom masuk antrean.", "success")
    elif action == "issue_cert":
        try:
            certificates.issue(p, who)
            flash("Sertifikat diterbitkan.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
    elif action == "regenerate_cert" and p.certificate:
        certificates._write_file(p.certificate)
        db.session.commit()
        flash("File sertifikat dibuat ulang.", "success")
    elif action == "send_cert":
        n = certificates.send_one(p, who)
        flash(f"{n} pesan sertifikat masuk antrean." if n else "Sertifikat belum terbit / tidak ada kanal.",
              "success" if n else "error")
    elif action == "revoke_cert" and p.certificate:
        certificates.revoke(p.certificate, request.form.get("reason") or "Dicabut admin.", who)
        flash("Sertifikat dicabut.", "success")
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for(".participant_detail", pid=pid))


# ---- Zoom --------------------------------------------------------------------

def _zoom_context():
    zoom_msgs = dict(db.session.query(Message.status, func.count(Message.id))
                     .filter(Message.purpose == "zoom_link").group_by(Message.status).all())
    is_open, window_msg = zoom.window_state()
    return {"values": settings.get_all(), "published_at": settings.zoom_published_at(),
            "window_open": is_open, "window_msg": window_msg, "opens_at": settings.zoom_publish_window_opens(),
            "event_start": settings.event_start(), "zoom_msgs": zoom_msgs,
            "status_labels": Message.STATUS_LABELS}


@bp.get("/zoom")
def zoom_page():
    return render_template("admin/zoom.html", **_zoom_context())


@bp.post("/zoom/simpan")
def zoom_save():
    try:
        changed = zoom.save(request.form.get("zoom_url", ""), request.form.get("zoom_meeting_id", ""),
                            request.form.get("zoom_passcode", ""), request.form.get("zoom_auto_publish") == "1",
                            actor())
        flash("Link Zoom disimpan (tidak tampil ke publik).", "success")
        if changed:
            flash("Link berubah setelah dipublikasikan. Tekan 'Publikasikan ulang' agar peserta menerima link baru.",
                  "warning")
    except zoom.ZoomError as exc:
        flash(str(exc), "error")
    return redirect(url_for(".zoom_page"))


@bp.post("/zoom/publikasi")
def zoom_publish():
    try:
        campaign = zoom.publish(actor(), override=request.form.get("override") == "1",
                                reason=request.form.get("reason", "")[:300])
        count = notifications.run_campaign(campaign)
        flash(f"Link Zoom dipublikasikan. {count} pesan masuk antrean pengiriman.", "success")
    except zoom.ZoomError as exc:
        flash(str(exc), "error")
    return redirect(url_for(".zoom_page"))


@bp.post("/zoom/tarik")
def zoom_unpublish():
    cancelled = zoom.unpublish(actor())
    flash(f"Publikasi link Zoom ditarik. {cancelled} pesan yang belum terkirim dibatalkan.", "success")
    return redirect(url_for(".zoom_page"))


# ---- Presensi ----------------------------------------------------------------

@bp.route("/presensi", methods=["GET", "POST"])
def attendance_page():
    summary = None
    if request.method == "POST":
        kind = request.form.get("kind")
        if kind == "settings":
            save_settings(ATTENDANCE_KEYS)
            return redirect(url_for(".attendance_page"))
        try:
            if kind == "csv":
                upload = request.files.get("report")
                if not upload or not upload.filename:
                    raise ValueError("Pilih file CSV laporan peserta Zoom.")
                rows = attendance.parse_zoom_csv(upload.read())
                summary = attendance.apply_report(rows, "zoom_csv", actor())
            elif kind == "zoom_api":
                rows = zoom.fetch_participants(request.form.get("meeting_id") or settings.get("zoom_meeting_id"))
                summary = attendance.apply_report(rows, "zoom_api", actor())
        except (ValueError, zoom.ZoomError) as exc:
            flash(str(exc), "error")
    reg = db.session.query(Participant).filter_by(status="registered")
    methods = dict(db.session.query(Participant.attendance_method, func.count(Participant.id))
                   .filter(Participant.attended.is_(True)).group_by(Participant.attendance_method).all())
    return render_template("admin/attendance.html", values=settings.get_all(), summary=summary,
                           total=reg.count(), attended=reg.filter(Participant.attended.is_(True)).count(),
                           methods=methods, zoom_api=zoom.api_configured())


# ---- Pesan & kampanye --------------------------------------------------------

@bp.get("/pesan")
def messages():
    q = db.session.query(Message)
    for field in ("status", "purpose", "channel"):
        if request.args.get(field):
            q = q.filter(getattr(Message, field) == request.args[field])
    result = paginate(q.order_by(Message.id.desc()), request.args.get("page", 1, type=int), 40)
    campaigns = db.session.query(Campaign).order_by(Campaign.id.desc()).limit(30).all()
    campaign_stats = {}
    for cid, status, count in db.session.query(Message.campaign_id, Message.status, func.count(Message.id)) \
            .filter(Message.campaign_id.in_([c.id for c in campaigns] or [0])) \
            .group_by(Message.campaign_id, Message.status).all():
        campaign_stats.setdefault(cid, {})[status] = count
    wa_name, wa_ready = provider_status()
    return render_template("admin/messages.html", result=result, args=request.args, campaigns=campaigns,
                           campaign_stats=campaign_stats, stats=notifications.stats(),
                           status_labels=Message.STATUS_LABELS, purpose_labels=Message.PURPOSE_LABELS,
                           wa_name=wa_name, wa_ready=wa_ready, email_ready=email_service.is_configured(),
                           heartbeat_age=_heartbeat_age())


@bp.post("/pesan/<int:mid>/ulang")
def message_retry(mid):
    msg = db.session.get(Message, mid) or abort(404)
    flash("Pesan dijadwalkan ulang." if notifications.retry(msg, actor()) else "Pesan ini tidak dapat diulang.",
          "success")
    return redirect(request.referrer or url_for(".messages"))


@bp.post("/pesan/ulang-semua-gagal")
def message_retry_all():
    flash(f"{notifications.retry_all_failed(actor())} pesan gagal dijadwalkan ulang.", "success")
    return redirect(url_for(".messages"))


@bp.post("/pesan/proses")
def message_process_now():
    result = scheduler.tick(force_all=True)
    q = result["queue"]
    flash(f"Antrean diproses: {q['sent']} terkirim, {q['failed']} gagal, {q['retry']} dijadwalkan ulang.", "success")
    audit.record(actor(), "queue.process_manual", details=q)
    return redirect(request.referrer or url_for(".messages"))


@bp.post("/kampanye")
def campaign_create():
    purpose = request.form.get("purpose")
    audience = request.form.get("audience", "all")
    if purpose not in ("reminder", "broadcast") or audience not in ("all", "attended", "not_attended"):
        abort(400)
    custom_text = (request.form.get("custom_text") or "").strip()[:1500]
    if purpose == "broadcast" and len(custom_text) < 5:
        flash("Isi teks pengumuman.", "error")
        return redirect(url_for(".messages"))
    when = timeutil.parse_local(request.form.get("scheduled_at")) or timeutil.utcnow()
    name = request.form.get("name", "").strip() or Message.PURPOSE_LABELS[purpose]
    notifications.create_campaign(name, purpose, audience, when, actor(), custom_text or None)
    flash(f"Kampanye dijadwalkan untuk {timeutil.fmt_local(when)} {timeutil.tz_label()}.", "success")
    return redirect(url_for(".messages"))


@bp.post("/kampanye/<int:cid>/batal")
def campaign_cancel(cid):
    campaign = db.session.get(Campaign, cid) or abort(404)
    notifications.cancel_campaign(campaign, actor())
    flash("Kampanye dibatalkan; pesan yang belum terkirim dibatalkan.", "success")
    return redirect(url_for(".messages"))


@bp.route("/pesan/template", methods=["GET", "POST"])
def message_templates():
    if request.method == "POST":
        save_settings(NOTIFY_KEYS)
        return redirect(url_for(".message_templates"))
    return render_template("admin/message_templates.html", values=settings.get_all(), keys=NOTIFY_KEYS,
                           schema=settings.SCHEMA, email_ready=email_service.is_configured())


# ---- Sertifikat --------------------------------------------------------------

@bp.route("/sertifikat", methods=["GET", "POST"])
def certificates_page():
    if request.method == "POST":
        save_settings(CERT_KEYS)
        return redirect(url_for(".certificates_page"))
    result = paginate(db.session.query(Certificate).order_by(Certificate.sequence.desc()),
                      request.args.get("page", 1, type=int))
    end = settings.event_end()
    auto_at = end + timedelta(minutes=settings.get("cert_send_after_minutes")) if end else None
    return render_template("admin/certificates.html", values=settings.get_all(), keys=CERT_KEYS,
                           schema=settings.SCHEMA, result=result, stats=certificates.stats(), auto_at=auto_at)


@bp.get("/sertifikat/pratinjau.pdf")
def certificate_preview():
    return Response(certificates.preview_pdf(), mimetype="application/pdf",
                    headers={"Content-Disposition": "inline; filename=pratinjau-sertifikat.pdf"})


@bp.get("/sertifikat/<int:cid>/file")
def certificate_file(cid):
    cert = db.session.get(Certificate, cid) or abort(404)
    return send_file(certificates.file_path(cert), mimetype="application/pdf", max_age=0)


@bp.post("/sertifikat/aksi")
def certificate_action():
    action = request.form.get("action")
    if action == "issue_all":
        flash(f"{certificates.issue_all(actor())} sertifikat baru diterbitkan untuk peserta yang hadir.", "success")
    elif action == "regenerate":
        flash(f"{certificates.regenerate_all(actor())} file sertifikat dibuat ulang dengan template terbaru.",
              "success")
    elif action == "send_all":
        certificates.issue_all(actor())
        campaign = notifications.create_campaign("Pengiriman e-sertifikat", "certificate", "attended",
                                                 timeutil.utcnow(), actor())
        flash(f"{notifications.run_campaign(campaign)} pesan sertifikat masuk antrean.", "success")
    else:
        abort(400)
    return redirect(url_for(".certificates_page"))


@bp.get("/upload/<name>")
def uploaded_file(name):
    path = files.path_for(name) or abort(404)
    return send_file(path, max_age=0)


# ---- Pengaturan & audit ------------------------------------------------------

@bp.route("/pengaturan", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        save_settings(EVENT_KEYS)
        return redirect(url_for(".settings_page"))
    return render_template("admin/settings.html", values=settings.get_all(), keys=EVENT_KEYS,
                           schema=settings.SCHEMA)


@bp.get("/audit")
def audit_log():
    q = db.session.query(AuditLog)
    if request.args.get("action"):
        q = q.filter(AuditLog.action.ilike(f"%{request.args['action'][:50]}%"))
    result = paginate(q.order_by(AuditLog.id.desc()), request.args.get("page", 1, type=int), 50)
    return render_template("admin/audit.html", result=result, args=request.args)
