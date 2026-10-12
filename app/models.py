"""Model database. Lihat docs/DATABASE.md untuk penjelasan setiap tabel."""
import secrets
import uuid

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .utils import timeutil


def _token() -> str:
    return secrets.token_urlsafe(32)


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: timeutil.utcnow())
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: timeutil.utcnow(),
                           onupdate=lambda: timeutil.utcnow())


class AdminUser(TimestampMixin, db.Model):
    __tablename__ = "admin_users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    failed_logins = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)
    # Berubah setiap ganti kata sandi -> sesi lama otomatis tidak berlaku.
    session_nonce = db.Column(db.String(32), nullable=False, default=lambda: secrets.token_hex(16))

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)
        self.session_nonce = secrets.token_hex(16)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Participant(TimestampMixin, db.Model):
    __tablename__ = "participants"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), unique=True, nullable=False, default=lambda: uuid.uuid4().hex)
    access_token = db.Column(db.String(64), unique=True, nullable=False, default=_token)

    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)  # E.164 tanpa '+', mis. 6281234567890
    category = db.Column(db.String(20), nullable=False, index=True)
    institution = db.Column(db.String(150), nullable=False)
    student_id = db.Column(db.String(30))
    study_program = db.Column(db.String(120))
    city = db.Column(db.String(80))
    info_source = db.Column(db.String(40))

    status = db.Column(db.String(20), nullable=False, default="registered", index=True)  # registered|cancelled
    privacy_consent_at = db.Column(db.DateTime, nullable=False)
    consent_version = db.Column(db.String(20), nullable=False)
    wa_consent = db.Column(db.Boolean, nullable=False, default=False)
    wa_consent_at = db.Column(db.DateTime)
    wa_opted_out_at = db.Column(db.DateTime)
    registered_ip_hash = db.Column(db.String(64))

    attended = db.Column(db.Boolean, nullable=False, default=False, index=True)
    attendance_method = db.Column(db.String(20))  # manual|code|zoom_csv|zoom_api|api
    attendance_minutes = db.Column(db.Integer)
    attended_at = db.Column(db.DateTime)

    messages = db.relationship("Message", back_populates="participant", cascade="all, delete-orphan",
                               lazy="dynamic")
    certificate = db.relationship("Certificate", back_populates="participant", uselist=False,
                                  cascade="all, delete-orphan")

    CATEGORIES = {
        "pelajar": "Pelajar",
        "mahasiswa": "Mahasiswa",
        "startup": "Pelaku/Penggiat Startup",
        "umkm": "Pelaku UMKM",
        "lainnya": "Lainnya",
    }

    @property
    def category_label(self) -> str:
        return self.CATEGORIES.get(self.category, self.category)

    @property
    def can_receive_whatsapp(self) -> bool:
        return self.wa_consent and self.wa_opted_out_at is None and self.status == "registered"

    @property
    def masked_phone(self) -> str:
        return f"+{self.phone[:4]}****{self.phone[-3:]}" if len(self.phone) > 7 else "****"

    @property
    def masked_email(self) -> str:
        local, _, domain = self.email.partition("@")
        return f"{local[:2]}***@{domain}"


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=False)  # JSON
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: timeutil.utcnow(),
                           onupdate=lambda: timeutil.utcnow())
    updated_by = db.Column(db.String(64))


class Campaign(TimestampMixin, db.Model):
    """Satu kali pengiriman massal (link Zoom, pengingat, sertifikat, pengumuman)."""
    __tablename__ = "campaigns"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    purpose = db.Column(db.String(30), nullable=False)
    audience = db.Column(db.String(20), nullable=False, default="all")  # all|attended|not_attended
    custom_text = db.Column(db.Text)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="scheduled", index=True)
    created_by = db.Column(db.String(64))
    enqueued_count = db.Column(db.Integer, nullable=False, default=0)
    processed_at = db.Column(db.DateTime)

    messages = db.relationship("Message", back_populates="campaign", lazy="dynamic")


class Message(TimestampMixin, db.Model):
    """Antrean pesan keluar (WhatsApp/email) beserta status pengirimannya."""
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey("participants.id", ondelete="CASCADE"),
                               nullable=False, index=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)
    channel = db.Column(db.String(10), nullable=False)  # whatsapp|email
    purpose = db.Column(db.String(30), nullable=False, index=True)
    dedupe_key = db.Column(db.String(120), unique=True)
    status = db.Column(db.String(20), nullable=False, default="queued", index=True)
    provider = db.Column(db.String(20))
    provider_message_id = db.Column(db.String(128), index=True)
    body = db.Column(db.Text)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=4)
    scheduled_at = db.Column(db.DateTime, nullable=False, default=lambda: timeutil.utcnow())
    next_attempt_at = db.Column(db.DateTime, nullable=False, default=lambda: timeutil.utcnow(), index=True)
    last_error = db.Column(db.Text)
    sent_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    read_at = db.Column(db.DateTime)
    failed_at = db.Column(db.DateTime)

    participant = db.relationship("Participant", back_populates="messages")
    campaign = db.relationship("Campaign", back_populates="messages")

    STATUS_LABELS = {
        "queued": "Antre", "sending": "Mengirim", "sent": "Terkirim", "delivered": "Diterima",
        "read": "Dibaca", "failed": "Gagal", "cancelled": "Dibatalkan", "skipped": "Dilewati",
    }
    PURPOSE_LABELS = {
        "registration": "Konfirmasi pendaftaran", "zoom_link": "Link Zoom", "reminder": "Pengingat",
        "certificate": "E-sertifikat", "broadcast": "Pengumuman",
    }


class Certificate(TimestampMixin, db.Model):
    __tablename__ = "certificates"
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey("participants.id", ondelete="CASCADE"),
                               unique=True, nullable=False)
    sequence = db.Column(db.Integer, unique=True, nullable=False)
    number = db.Column(db.String(80), unique=True, nullable=False)
    verify_code = db.Column(db.String(32), unique=True, nullable=False, default=lambda: secrets.token_hex(8))
    download_token = db.Column(db.String(64), unique=True, nullable=False, default=_token)
    file_name = db.Column(db.String(200))
    issued_at = db.Column(db.DateTime, nullable=False, default=lambda: timeutil.utcnow())
    generated_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)
    revoke_reason = db.Column(db.String(200))

    participant = db.relationship("Participant", back_populates="certificate")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: timeutil.utcnow(), index=True)
    actor = db.Column(db.String(64), nullable=False)
    action = db.Column(db.String(64), nullable=False, index=True)
    target_type = db.Column(db.String(40))
    target_id = db.Column(db.String(64))
    details = db.Column(db.Text)  # JSON
    ip_hash = db.Column(db.String(64))


class IntegrationEvent(TimestampMixin, db.Model):
    """Event keluar (webhook) untuk bot/layanan pihak ketiga, dikirim oleh worker."""
    __tablename__ = "integration_events"
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(64), nullable=False)
    payload = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)  # pending|delivered|failed
    attempts = db.Column(db.Integer, nullable=False, default=0)
    next_attempt_at = db.Column(db.DateTime, nullable=False, default=lambda: timeutil.utcnow())
    last_error = db.Column(db.Text)
