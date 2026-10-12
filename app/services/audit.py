import json
import logging

from flask import has_request_context

from ..extensions import db
from ..models import AuditLog
from ..utils.security import hash_ip

log = logging.getLogger(__name__)


def record(actor: str, action: str, target_type: str | None = None, target_id=None,
           details: dict | None = None, commit: bool = True) -> None:
    """Catat aksi penting (admin maupun sistem) ke tabel audit_logs."""
    entry = AuditLog(
        actor=actor or "system",
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=json.dumps(details, ensure_ascii=False, default=str) if details else None,
        ip_hash=hash_ip() if has_request_context() else None,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    log.info("audit actor=%s action=%s target=%s:%s", actor, action, target_type, target_id)
