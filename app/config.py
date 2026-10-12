"""Konfigurasi aplikasi. Semua rahasia dibaca dari environment variable (.env)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "ya"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{BASE_DIR / 'instance' / 'webinar.db'}"
    # Heroku/Render memberi "postgres://"; SQLAlchemy butuh nama driver eksplisit.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Config:
    APP_ENV = os.getenv("APP_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/")
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Jakarta")
    TRUST_PROXY = env_int("TRUST_PROXY", 0)

    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    INSTANCE_DIR = Path(os.getenv("INSTANCE_DIR", BASE_DIR / "instance"))
    UPLOAD_DIR = INSTANCE_DIR / "uploads"
    CERT_DIR = INSTANCE_DIR / "certificates"
    BACKUP_DIR = Path(os.getenv("BACKUP_DIR", BASE_DIR / "backups"))
    LOG_DIR = Path(os.getenv("LOG_DIR", BASE_DIR / "logs"))
    BACKUP_RETENTION = env_int("BACKUP_RETENTION", 14)
    BACKUP_INTERVAL_HOURS = env_int("BACKUP_INTERVAL_HOURS", 24)

    MAX_CONTENT_LENGTH = env_int("MAX_UPLOAD_MB", 5) * 1024 * 1024

    # Sesi & keamanan
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", APP_ENV == "production")
    PERMANENT_SESSION_LIFETIME = env_int("ADMIN_SESSION_HOURS", 8) * 3600
    WTF_CSRF_TIME_LIMIT = None  # token CSRF berlaku selama sesi
    ADMIN_MAX_FAILED_LOGINS = env_int("ADMIN_MAX_FAILED_LOGINS", 5)
    ADMIN_LOCKOUT_MINUTES = env_int("ADMIN_LOCKOUT_MINUTES", 15)
    # Format: "nama_bot:token_panjang,nama_lain:token_lain"
    API_TOKENS = os.getenv("API_TOKENS", "")

    # Rate limiting (gunakan redis://... di produksi multi-proses)
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_ENABLED = env_bool("RATELIMIT_ENABLED", True)

    # WhatsApp
    WHATSAPP_PROVIDER = os.getenv("WHATSAPP_PROVIDER", "disabled").lower()  # meta | fonnte | console | disabled
    WA_META_API_VERSION = os.getenv("WA_META_API_VERSION", "v23.0")
    WA_META_PHONE_NUMBER_ID = os.getenv("WA_META_PHONE_NUMBER_ID", "")
    WA_META_ACCESS_TOKEN = os.getenv("WA_META_ACCESS_TOKEN", "")
    WA_META_APP_SECRET = os.getenv("WA_META_APP_SECRET", "")
    WA_META_VERIFY_TOKEN = os.getenv("WA_META_VERIFY_TOKEN", "")
    WA_TEMPLATE_LANGUAGE = os.getenv("WA_TEMPLATE_LANGUAGE", "id")
    WA_TEMPLATE_REGISTRATION = os.getenv("WA_TEMPLATE_REGISTRATION", "webinar_registrasi")
    WA_TEMPLATE_ZOOM_LINK = os.getenv("WA_TEMPLATE_ZOOM_LINK", "webinar_link_zoom")
    WA_TEMPLATE_REMINDER = os.getenv("WA_TEMPLATE_REMINDER", "webinar_pengingat")
    WA_TEMPLATE_CERTIFICATE = os.getenv("WA_TEMPLATE_CERTIFICATE", "webinar_sertifikat")
    WA_TEMPLATE_ANNOUNCEMENT = os.getenv("WA_TEMPLATE_ANNOUNCEMENT", "webinar_pengumuman")
    FONNTE_TOKEN = os.getenv("FONNTE_TOKEN", "")
    FONNTE_WEBHOOK_SECRET = os.getenv("FONNTE_WEBHOOK_SECRET", "")
    WA_SEND_DELAY_MS = env_int("WA_SEND_DELAY_MS", 200)
    MESSAGE_MAX_ATTEMPTS = env_int("MESSAGE_MAX_ATTEMPTS", 4)

    # Email (SMTP)
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = env_int("SMTP_PORT", 587)
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_SECURITY = os.getenv("SMTP_SECURITY", "starttls").lower()  # starttls | ssl | none
    MAIL_FROM = os.getenv("MAIL_FROM", "")

    # Zoom API (opsional, untuk menarik laporan kehadiran)
    ZOOM_ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID", "")
    ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "")
    ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "")
    ZOOM_ALLOW_ANY_DOMAIN = env_bool("ZOOM_ALLOW_ANY_DOMAIN", False)

    # Webhook keluar untuk integrasi pihak ketiga (bot, CRM, dsb.)
    INTEGRATION_WEBHOOK_URL = os.getenv("INTEGRATION_WEBHOOK_URL", "")
    INTEGRATION_WEBHOOK_SECRET = os.getenv("INTEGRATION_WEBHOOK_SECRET", "")

    WORKER_INTERVAL_SECONDS = env_int("WORKER_INTERVAL_SECONDS", 5)
