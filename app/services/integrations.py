"""Webhook keluar untuk integrasi (bot Telegram/Discord, CRM, Google Sheets via Apps Script, dll).

Setiap event disimpan dulu ke tabel integration_events, lalu dikirim oleh worker dengan
header X-Webinar-Signature (HMAC-SHA256 dari body memakai INTEGRATION_WEBHOOK_SECRET).
"""
import json
import logging
from datetime import timedelta

import requests
from flask import current_app

from ..extensions import db
from ..models import IntegrationEvent
from ..utils import timeutil
from ..utils.security import sign_payload

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 6


def emit(event: str, payload: dict, commit: bool = False) -> None:
    if not current_app.config["INTEGRATION_WEBHOOK_URL"]:
        return
    body = {"event": event, "occurred_at": timeutil.utcnow().isoformat() + "Z", "data": payload}
    db.session.add(IntegrationEvent(event=event, payload=json.dumps(body, ensure_ascii=False, default=str)))
    if commit:
        db.session.commit()


def participant_payload(p) -> dict:
    return {"id": p.public_id, "full_name": p.full_name, "category": p.category,
            "institution": p.institution, "attended": p.attended}


def deliver_pending(limit: int = 50) -> int:
    url = current_app.config["INTEGRATION_WEBHOOK_URL"]
    if not url:
        return 0
    secret = current_app.config["INTEGRATION_WEBHOOK_SECRET"]
    now = timeutil.utcnow()
    events = (db.session.query(IntegrationEvent)
              .filter(IntegrationEvent.status == "pending", IntegrationEvent.next_attempt_at <= now)
              .order_by(IntegrationEvent.id).limit(limit).all())
    delivered = 0
    for ev in events:
        body = ev.payload.encode()
        headers = {"Content-Type": "application/json", "X-Webinar-Event": ev.event}
        if secret:
            headers["X-Webinar-Signature"] = sign_payload(secret, body)
        ev.attempts += 1
        try:
            resp = requests.post(url, data=body, headers=headers, timeout=10)
            if 200 <= resp.status_code < 300:
                ev.status = "delivered"
                delivered += 1
            else:
                raise RuntimeError(f"HTTP {resp.status_code}")
        except Exception as exc:  # noqa: BLE001 - semua kegagalan jaringan diperlakukan sama
            ev.last_error = str(exc)[:500]
            if ev.attempts >= MAX_ATTEMPTS:
                ev.status = "failed"
            else:
                ev.next_attempt_at = now + timedelta(minutes=2 ** ev.attempts)
            log.warning("Webhook integrasi gagal (event %s): %s", ev.id, exc)
    db.session.commit()
    return delivered
