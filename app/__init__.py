"""Aplikasi pendaftaran webinar — factory Flask."""
import logging
import secrets
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # harus sebelum config dibaca

from flask import Flask, render_template, request  # noqa: E402
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

from .config import Config  # noqa: E402
from .extensions import csrf, db, limiter, migrate  # noqa: E402


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    if not app.config["SECRET_KEY"]:
        if app.config["APP_ENV"] == "production":
            raise RuntimeError("SECRET_KEY wajib diisi di produksi (lihat .env.example).")
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning("SECRET_KEY kosong — memakai kunci acak sementara (khusus development).")

    if app.config["TRUST_PROXY"]:
        n = app.config["TRUST_PROXY"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    for key in ("INSTANCE_DIR", "UPLOAD_DIR", "CERT_DIR", "LOG_DIR"):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)

    _configure_logging(app)
    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)
    limiter.init_app(app)

    from .blueprints.admin import bp as admin_bp
    from .blueprints.api import bp as api_bp
    from .blueprints.public import bp as public_bp
    from .blueprints.webhooks import bp as webhooks_bp
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(webhooks_bp, url_prefix="/webhooks")
    csrf.exempt(api_bp)       # API memakai Bearer token, bukan cookie
    csrf.exempt(webhooks_bp)  # webhook diverifikasi dengan tanda tangan/token

    _register_template_helpers(app)
    _register_security_headers(app)
    _register_error_handlers(app)

    from .cli import register_cli
    register_cli(app)
    return app


def _configure_logging(app: Flask) -> None:
    handler = RotatingFileHandler(Path(app.config["LOG_DIR"]) / "app.log", maxBytes=2_000_000,
                                  backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.setLevel(logging.INFO)
    root = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    root.setLevel(logging.INFO)


def _register_template_helpers(app: Flask) -> None:
    from .services import settings_service as settings
    from .utils import timeutil
    from .utils.phone import wa_me_link

    app.jinja_env.filters.update(
        local=timeutil.fmt_local,
        indo_date=timeutil.format_indo_date,
        indo_time=timeutil.format_indo_time,
        local_input=timeutil.to_local_input,
    )

    @app.context_processor
    def inject_globals():
        return {"setting": settings.get, "wa_me_link": wa_me_link, "tz_label": timeutil.tz_label,
                "app_env": app.config["APP_ENV"], "setting_labels": settings.LABELS,
                "setting_schema": settings.SCHEMA}


def _register_security_headers(app: Flask) -> None:
    csp = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
           "font-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'; object-src 'none'")

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("Content-Security-Policy", csp)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if app.config["SESSION_COOKIE_SECURE"]:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith(("/admin", "/peserta", "/sertifikat")):
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp


def _register_error_handlers(app: Flask) -> None:
    def wants_json():
        return request.path.startswith(("/api/", "/webhooks/"))

    def handle(code, title, message):
        def _handler(_err):
            if wants_json():
                return {"error": title, "message": message}, code
            return render_template("errors/error.html", code=code, title=title, message=message), code
        return _handler

    app.register_error_handler(400, handle(400, "Permintaan tidak valid", "Periksa kembali data yang dikirim."))
    app.register_error_handler(403, handle(403, "Akses ditolak", "Anda tidak memiliki akses ke halaman ini."))
    app.register_error_handler(404, handle(404, "Halaman tidak ditemukan", "Tautan mungkin salah atau sudah tidak berlaku."))
    app.register_error_handler(413, handle(413, "File terlalu besar", "Ukuran file melebihi batas yang diizinkan."))
    app.register_error_handler(429, handle(429, "Terlalu banyak percobaan", "Mohon tunggu beberapa saat lalu coba lagi."))

    @app.errorhandler(500)
    def server_error(err):
        db.session.rollback()
        app.logger.error("Kesalahan server: %s", err)
        if wants_json():
            return {"error": "Kesalahan server", "message": "Silakan coba lagi."}, 500
        return render_template("errors/error.html", code=500, title="Terjadi kesalahan",
                               message="Silakan coba lagi beberapa saat lagi."), 500

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def csrf_error(_err):
        return render_template("errors/error.html", code=400, title="Sesi formulir kedaluwarsa",
                               message="Muat ulang halaman lalu kirim formulir kembali."), 400
