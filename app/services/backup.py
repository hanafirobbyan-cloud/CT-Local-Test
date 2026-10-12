"""Backup database + file (unggahan & sertifikat) ke folder BACKUP_DIR, dengan retensi."""
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path

from flask import current_app
from sqlalchemy.engine import make_url

from ..utils import timeutil
from . import settings_service as settings

log = logging.getLogger(__name__)


def create_backup() -> Path:
    cfg = current_app.config
    backup_dir = Path(cfg["BACKUP_DIR"])
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = timeutil.utcnow().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"backup-{stamp}.zip"
    url = make_url(cfg["SQLALCHEMY_DATABASE_URI"])

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if url.get_backend_name() == "sqlite":
            dump = tmp_path / "webinar.db"
            src = sqlite3.connect(url.database)
            dst = sqlite3.connect(dump)
            with dst:
                src.backup(dst)  # backup online yang konsisten
            src.close()
            dst.close()
        elif url.get_backend_name() == "postgresql":
            dump = tmp_path / "webinar.sql"
            if not shutil.which("pg_dump"):
                raise RuntimeError("pg_dump tidak ditemukan. Pasang postgresql-client atau gunakan backup terkelola.")
            env = {**os.environ, "PGPASSWORD": url.password or ""}
            subprocess.run(["pg_dump", "--no-owner", "-h", url.host or "localhost", "-p", str(url.port or 5432),
                            "-U", url.username or "", "-d", url.database, "-f", str(dump)],
                           check=True, env=env, timeout=600)
        else:
            raise RuntimeError(f"Backup otomatis belum mendukung {url.get_backend_name()}.")

        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(dump, dump.name)
            for folder_key, arc in (("UPLOAD_DIR", "uploads"), ("CERT_DIR", "certificates")):
                folder = Path(cfg[folder_key])
                if folder.is_dir():
                    for file in folder.rglob("*"):
                        if file.is_file():
                            zf.write(file, f"{arc}/{file.relative_to(folder)}")

    _apply_retention(backup_dir, cfg["BACKUP_RETENTION"])
    settings.set_many({"last_backup_at": timeutil.utcnow().isoformat()}, "system:backup")
    log.info("Backup dibuat: %s", target)
    return target


def _apply_retention(backup_dir: Path, keep: int) -> None:
    backups = sorted(backup_dir.glob("backup-*.zip"))
    for old in backups[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)


def backup_due() -> bool:
    hours = current_app.config["BACKUP_INTERVAL_HOURS"]
    if hours <= 0:
        return False
    last = settings.get("last_backup_at")
    if not last:
        return True
    from datetime import datetime
    try:
        return timeutil.utcnow() - datetime.fromisoformat(last) >= timedelta(hours=hours)
    except ValueError:
        return True

