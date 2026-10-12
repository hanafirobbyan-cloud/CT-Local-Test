"""Satu "tick" worker: dijalankan berulang oleh `flask worker` (atau sekali oleh `flask run-tasks`)."""
import logging
import time

from flask import g

from ..utils import timeutil
from . import backup, certificates, integrations, notifications, zoom
from . import settings_service as settings

log = logging.getLogger(__name__)
_last_run: dict[str, float] = {}


def _every(name: str, seconds: int) -> bool:
    now = time.monotonic()
    if now - _last_run.get(name, -1e9) >= seconds:
        _last_run[name] = now
        return True
    return False


def tick(force_all: bool = False) -> dict:
    g.pop("settings_cache", None)  # selalu baca pengaturan terbaru
    result = {}
    settings.set_many({"worker_heartbeat": timeutil.utcnow().isoformat()}, "system:worker")
    if force_all or _every("stuck", 60):
        result["released"] = notifications.release_stuck()
    result["zoom_auto_published"] = zoom.auto_publish_tick()  # sebelum kampanye agar langsung terkirim
    result["campaigns"] = notifications.run_due_campaigns()
    if force_all or _every("certificates", 60):
        result["certificates_queued"] = certificates.auto_tick()
    result["queue"] = notifications.process_queue()
    result["webhooks"] = integrations.deliver_pending()
    if force_all or _every("backup", 600):
        if backup.backup_due():
            try:
                result["backup"] = str(backup.create_backup())
            except Exception as exc:  # noqa: BLE001
                log.error("Backup otomatis gagal: %s", exc)
    return result
