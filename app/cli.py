"""Perintah CLI: `flask <perintah>`. Jalankan `flask --help` untuk daftar lengkap."""
import getpass
import logging
import os
import time

import click
from flask import current_app

from .extensions import db
from .models import AdminUser
from .services import audit, backup, scheduler


def register_cli(app):
    @app.cli.command("create-admin")
    @click.argument("username")
    @click.option("--password", envvar="ADMIN_PASSWORD", help="Bisa juga lewat env ADMIN_PASSWORD.")
    def create_admin(username, password):
        """Buat akun admin baru (atau reset kata sandi bila sudah ada)."""
        if not password:
            password = getpass.getpass("Kata sandi (min. 12 karakter): ")
            if password != getpass.getpass("Ulangi kata sandi: "):
                raise click.ClickException("Kata sandi tidak sama.")
        if len(password) < 12:
            raise click.ClickException("Kata sandi minimal 12 karakter.")
        user = db.session.query(AdminUser).filter_by(username=username).first()
        created = user is None
        if created:
            user = AdminUser(username=username, password_hash="")
            db.session.add(user)
        user.set_password(password)
        user.is_active = True
        user.failed_logins = 0
        user.locked_until = None
        db.session.commit()
        audit.record("cli", "admin.create" if created else "admin.reset_password", "admin", username)
        click.echo(f"Admin '{username}' {'dibuat' if created else 'diperbarui'}.")

    @app.cli.command("deactivate-admin")
    @click.argument("username")
    def deactivate_admin(username):
        """Nonaktifkan akun admin."""
        user = db.session.query(AdminUser).filter_by(username=username).first()
        if not user:
            raise click.ClickException("Admin tidak ditemukan.")
        user.is_active = False
        db.session.commit()
        audit.record("cli", "admin.deactivate", "admin", username)
        click.echo("Admin dinonaktifkan.")

    @app.cli.command("worker")
    @click.option("--interval", type=int, default=None, help="Jeda antar siklus (detik).")
    def worker(interval):
        """Jalankan worker: antrean WhatsApp/email, jadwal, auto-publish Zoom, sertifikat, backup."""
        interval = interval or current_app.config["WORKER_INTERVAL_SECONDS"]
        logging.getLogger().addHandler(logging.StreamHandler())
        click.echo(f"Worker berjalan (interval {interval} detik). Tekan Ctrl+C untuk berhenti.")
        while True:
            try:
                result = scheduler.tick()
                if result["queue"]["processed"] or result["campaigns"] or result.get("certificates_queued"):
                    click.echo(f"[worker] {result}")
            except KeyboardInterrupt:
                break
            except Exception:  # noqa: BLE001 - worker tidak boleh mati karena satu kesalahan
                db.session.rollback()
                logging.getLogger("worker").exception("Kesalahan pada siklus worker")
            finally:
                db.session.remove()
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                break
        click.echo("Worker berhenti.")

    @app.cli.command("run-tasks")
    def run_tasks():
        """Jalankan satu siklus worker (untuk cron / Task Scheduler)."""
        click.echo(scheduler.tick(force_all=True))

    @app.cli.command("backup")
    def backup_cmd():
        """Buat backup database + file sekarang."""
        click.echo(f"Backup tersimpan: {backup.create_backup()}")

    @app.cli.command("seed-demo")
    @click.option("--count", default=15)
    def seed_demo(count):
        """(Khusus development) isi peserta contoh ber-email example.com."""
        if current_app.config["APP_ENV"] == "production":
            raise click.ClickException("Tidak boleh di produksi.")
        from .services import registration
        cats = ["pelajar", "mahasiswa", "startup", "umkm"]
        made = 0
        for i in range(count):
            data = {"full_name": f"Peserta Contoh {i + 1}", "email": f"peserta{i + 1}@example.com",
                    "phone": f"62812000{i + 1:05d}", "category": cats[i % 4], "institution": "Institusi Contoh",
                    "student_id": f"NIM{i + 1:04d}" if cats[i % 4] == "mahasiswa" else "",
                    "study_program": "Bisnis Digital" if cats[i % 4] == "mahasiswa" else "",
                    "city": "", "info_source": "lainnya", "wa_consent": i % 3 != 0}
            try:
                registration.register(data, source="seed")
                made += 1
            except registration.DuplicateRegistration:
                pass
        click.echo(f"{made} peserta contoh dibuat.")

    @app.cli.command("check-config")
    def check_config():
        """Periksa konfigurasi integrasi (tanpa menampilkan rahasia)."""
        from .services import email_service, zoom
        from .services.whatsapp import provider_status
        cfg = current_app.config
        name, ready = provider_status()
        rows = [
            ("APP_ENV", cfg["APP_ENV"]),
            ("PUBLIC_BASE_URL", cfg["PUBLIC_BASE_URL"]),
            ("SECRET_KEY", "OK" if os.getenv("SECRET_KEY") else "KOSONG (wajib di produksi)"),
            ("Database", cfg["SQLALCHEMY_DATABASE_URI"].split("@")[-1]),
            ("WhatsApp provider", f"{name} — {'siap' if ready else 'BELUM SIAP'}"),
            ("Webhook Meta (app secret)", "OK" if cfg["WA_META_APP_SECRET"] else "-"),
            ("Email SMTP", "siap" if email_service.is_configured() else "belum dikonfigurasi"),
            ("Zoom API", "siap" if zoom.api_configured() else "tidak dipakai"),
            ("Webhook integrasi", cfg["INTEGRATION_WEBHOOK_URL"] or "-"),
            ("Rate limit storage", cfg["RATELIMIT_STORAGE_URI"]),
        ]
        for key, value in rows:
            click.echo(f"{key:28} {value}")
