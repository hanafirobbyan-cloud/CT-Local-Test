"""Penyimpanan & publikasi link Zoom.

Aturan:
- Link disimpan admin kapan saja, tetapi TIDAK pernah tampil di halaman publik.
- Publikasi (kirim ke peserta + tampil di halaman peserta) dibuka mulai
  `zoom_publish_lead_minutes` (default 30) menit sebelum acara. Publikasi lebih awal
  hanya bisa dengan override + alasan, dan tercatat di audit log.
- Opsi auto-publish: worker mempublikasikan otomatis saat jendela publikasi terbuka.
"""
from urllib.parse import urlparse

import requests
from flask import current_app

from ..utils import timeutil
from . import audit, integrations, notifications
from . import settings_service as settings

ZOOM_HOSTS = ("zoom.us", "zoom.com", "zoomgov.com")


class ZoomError(Exception):
    pass


def validate_url(url: str) -> str | None:
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or not parsed.netloc:
        return "Link harus diawali https://"
    host = parsed.hostname or ""
    if not current_app.config["ZOOM_ALLOW_ANY_DOMAIN"] and not any(
            host == h or host.endswith("." + h) for h in ZOOM_HOSTS):
        return "Link harus berasal dari domain Zoom (zoom.us / zoom.com)."
    return None


def save(url: str, meeting_id: str, passcode: str, auto_publish: bool, actor: str) -> bool:
    """Simpan link. Mengembalikan True bila link berubah setelah dipublikasikan
    (admin perlu menekan 'Publikasikan ulang' agar peserta menerima link baru)."""
    url = (url or "").strip()
    if url:
        error = validate_url(url)
        if error:
            raise ZoomError(error)
    changed_after_publish = bool(settings.zoom_published_at()) and url != settings.get("zoom_url")
    settings.set_many({"zoom_url": url, "zoom_meeting_id": (meeting_id or "").strip()[:30],
                       "zoom_passcode": (passcode or "").strip()[:30],
                       "zoom_auto_publish": bool(auto_publish)}, actor)
    audit.record(actor, "zoom.save", details={"has_url": bool(url), "auto_publish": bool(auto_publish),
                                              "changed_after_publish": changed_after_publish})
    return changed_after_publish


def window_state() -> tuple[bool, str]:
    opens = settings.zoom_publish_window_opens()
    if not opens:
        return False, "Waktu mulai acara belum diatur."
    if timeutil.utcnow() < opens:
        return False, (f"Jendela publikasi dibuka {timeutil.fmt_local(opens, '%d/%m/%Y %H:%M')} "
                       f"{timeutil.tz_label()} ({settings.get('zoom_publish_lead_minutes')} menit sebelum acara).")
    return True, ""


def publish(actor: str, override: bool = False, reason: str = ""):
    if not settings.get("zoom_url"):
        raise ZoomError("Isi link Zoom terlebih dahulu.")
    is_open, message = window_state()
    if not is_open:
        if not override:
            raise ZoomError(message)
        if len((reason or "").strip()) < 5:
            raise ZoomError("Publikasi lebih awal memerlukan alasan (min. 5 karakter).")
    notifications.cancel_queued(purpose="zoom_link")
    now = timeutil.utcnow()
    settings.set_many({"zoom_published_at": now.isoformat()}, actor)
    campaign = notifications.create_campaign(
        f"Link Zoom — dipublikasikan {timeutil.fmt_local(now)}", "zoom_link", "all", now, actor)
    audit.record(actor, "zoom.publish", "campaign", campaign.id,
                 {"override": override and not is_open, "reason": reason or None})
    integrations.emit("zoom.published", {"campaign_id": campaign.id}, commit=True)
    return campaign


def unpublish(actor: str) -> int:
    settings.set_many({"zoom_published_at": ""}, actor)
    cancelled = notifications.cancel_queued(purpose="zoom_link")
    audit.record(actor, "zoom.unpublish", details={"cancelled_messages": cancelled})
    return cancelled


def auto_publish_tick() -> bool:
    if not (settings.get("zoom_auto_publish") and settings.get("zoom_url")) or settings.zoom_published_at():
        return False
    is_open, _ = window_state()
    end = settings.event_end()
    if is_open and (not end or timeutil.utcnow() < end):
        publish("system:auto-publish")
        return True
    return False


# ---- Zoom API (opsional): laporan peserta untuk presensi --------------------

def api_configured() -> bool:
    cfg = current_app.config
    return bool(cfg["ZOOM_ACCOUNT_ID"] and cfg["ZOOM_CLIENT_ID"] and cfg["ZOOM_CLIENT_SECRET"])


def _api_token() -> str:
    cfg = current_app.config
    resp = requests.post("https://zoom.us/oauth/token",
                         params={"grant_type": "account_credentials", "account_id": cfg["ZOOM_ACCOUNT_ID"]},
                         auth=(cfg["ZOOM_CLIENT_ID"], cfg["ZOOM_CLIENT_SECRET"]), timeout=20)
    if not resp.ok:
        raise ZoomError(f"Gagal mendapatkan token Zoom: HTTP {resp.status_code} {resp.text[:200]}")
    return resp.json()["access_token"]


def fetch_participants(meeting_id: str) -> list[dict]:
    """Ambil laporan peserta meeting yang sudah selesai (butuh akun Zoom Pro+ dan scope
    report:read:list_meeting_participants:admin). Mengembalikan [{name, email, minutes}]."""
    if not api_configured():
        raise ZoomError("Kredensial Zoom API belum diisi di .env.")
    meeting_id = (meeting_id or "").replace(" ", "")
    if not meeting_id:
        raise ZoomError("Meeting ID kosong.")
    token = _api_token()
    rows, next_token = [], ""
    for _ in range(50):  # batas aman paginasi
        resp = requests.get(f"https://api.zoom.us/v2/report/meetings/{meeting_id}/participants",
                            params={"page_size": 300, "next_page_token": next_token},
                            headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if not resp.ok:
            raise ZoomError(f"Zoom API error: HTTP {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        for item in data.get("participants", []):
            rows.append({"name": item.get("name", ""), "email": (item.get("user_email") or "").lower(),
                         "minutes": (item.get("duration") or 0) / 60})
        next_token = data.get("next_page_token") or ""
        if not next_token:
            break
    return rows
