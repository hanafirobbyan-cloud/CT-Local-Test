"""Webhook masuk dari provider WhatsApp: status pengiriman & balasan BERHENTI (opt-out)."""
import hmac
import logging

from flask import Blueprint, abort, current_app, request

from ..extensions import limiter
from ..services import notifications
from ..utils.phone import normalize_phone
from ..utils.security import verify_signature

bp = Blueprint("webhooks", __name__)
log = logging.getLogger(__name__)

OPT_OUT_WORDS = {"STOP", "BERHENTI", "UNSUBSCRIBE", "STOP WEBINAR", "BERHENTI WEBINAR"}
META_STATUS = {"sent": "sent", "delivered": "delivered", "read": "read", "failed": "failed"}


def _handle_incoming_text(sender: str, body: str) -> None:
    if (body or "").strip().upper() in OPT_OUT_WORDS:
        phone = normalize_phone("+" + sender.lstrip("+"))
        if phone and notifications.opt_out_phone(phone):
            log.info("Opt-out WhatsApp diterima dari %s****", phone[:5])


# ---- Meta WhatsApp Cloud API -------------------------------------------------

@bp.get("/whatsapp/meta")
@limiter.exempt
def meta_verify():
    expected = current_app.config["WA_META_VERIFY_TOKEN"]
    token = request.args.get("hub.verify_token", "")
    if (request.args.get("hub.mode") == "subscribe" and expected
            and hmac.compare_digest(token.encode(), expected.encode())):
        return request.args.get("hub.challenge", ""), 200, {"Content-Type": "text/plain"}
    abort(403)


@bp.post("/whatsapp/meta")
@limiter.exempt
def meta_events():
    secret = current_app.config["WA_META_APP_SECRET"]
    if not secret:
        log.error("WA_META_APP_SECRET belum diisi; webhook Meta ditolak demi keamanan.")
        abort(403)
    if not verify_signature(secret, request.get_data(), request.headers.get("X-Hub-Signature-256")):
        abort(403)
    payload = request.get_json(silent=True) or {}
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for st in value.get("statuses", []):
                status = META_STATUS.get(st.get("status"))
                if not status:
                    continue
                error = None
                if st.get("errors"):
                    e = st["errors"][0]
                    error = f"[{e.get('code')}] {e.get('title') or e.get('message')}: " \
                            f"{(e.get('error_data') or {}).get('details', '')}".strip()
                notifications.apply_status(st.get("id", ""), status, error)
            for msg in value.get("messages", []):
                if msg.get("type") == "text":
                    _handle_incoming_text(msg.get("from", ""), msg.get("text", {}).get("body", ""))
                elif msg.get("type") == "button":
                    _handle_incoming_text(msg.get("from", ""), msg.get("button", {}).get("text", ""))
    return {"status": "ok"}


# ---- Fonnte ------------------------------------------------------------------

def _check_fonnte_token():
    expected = current_app.config["FONNTE_WEBHOOK_SECRET"]
    token = request.args.get("token", "")
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        abort(403)


@bp.post("/whatsapp/fonnte/status")
@limiter.exempt
def fonnte_status():
    _check_fonnte_token()
    data = request.get_json(silent=True) or request.form.to_dict()
    message_id = str(data.get("id") or "")
    state = str(data.get("state") or data.get("status") or "").lower()
    mapping = {"sent": "sent", "delivered": "delivered", "read": "read", "failed": "failed",
               "invalid": "failed", "expired": "failed"}
    if message_id and state in mapping:
        notifications.apply_status(message_id, mapping[state], data.get("reason"))
    return {"status": "ok"}


@bp.post("/whatsapp/fonnte/incoming")
@limiter.exempt
def fonnte_incoming():
    _check_fonnte_token()
    data = request.get_json(silent=True) or request.form.to_dict()
    _handle_incoming_text(str(data.get("sender", "")), str(data.get("message", "")))
    return {"status": "ok"}
