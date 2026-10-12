import json
from datetime import datetime

import pytest

from app.models import Message, Participant
from app.services import notifications, scheduler, zoom
from app.services import settings_service as settings
from app.services.whatsapp.meta_cloud import MetaCloudProvider, clean_param
from app.utils import timeutil
from app.utils.security import sign_payload

from .conftest import FakeProvider, registration_form

ZOOM_URL = "https://us06web.zoom.us/j/1234567890?pwd=rahasia"
# Acara 01-11-2026 16:00 WIB = 09:00 UTC; jendela publikasi 08:30 UTC
BEFORE_WINDOW = datetime(2026, 11, 1, 8, 0)
IN_WINDOW = datetime(2026, 11, 1, 8, 35)


def _register(client, **kw):
    client.post("/daftar", data=registration_form(**kw))
    return Participant.query.filter_by(email=kw.get("email", "siti@example.com")).one()


def test_zoom_link_hidden_until_published(client, app):
    p = _register(client)
    zoom.save(ZOOM_URL, "123 456 7890", "abc", False, "admin:test")
    assert ZOOM_URL not in client.get("/").get_data(as_text=True)
    assert "rahasia" not in client.get(f"/peserta/{p.access_token}").get_data(as_text=True)
    assert "rahasia" not in client.get("/api/v1/event").get_data(as_text=True)

    timeutil.set_now(BEFORE_WINDOW)
    with pytest.raises(zoom.ZoomError, match="Jendela publikasi"):
        zoom.publish("admin:test")

    timeutil.set_now(IN_WINDOW)
    campaign = zoom.publish("admin:test")
    assert notifications.run_campaign(campaign) == 1
    page = client.get(f"/peserta/{p.access_token}").get_data(as_text=True)
    assert "Gabung Zoom Meeting" in page and "pwd=rahasia" in page
    assert "rahasia" not in client.get("/").get_data(as_text=True)


def test_publish_sends_only_to_consenting_participants(client, app):
    _register(client)
    _register(client, email="b@example.com", phone="081300000001", wa_consent="")
    zoom.save(ZOOM_URL, "", "", False, "admin:test")
    timeutil.set_now(IN_WINDOW)
    notifications.run_campaign(zoom.publish("admin:test"))
    stats = notifications.process_queue()
    zoom_sends = [s for s in FakeProvider.sent if s["purpose"] == "zoom_link"]
    assert len(zoom_sends) == 1 and zoom_sends[0]["to"] == "6281234567890"
    assert ZOOM_URL in zoom_sends[0]["text"]
    assert zoom_sends[0]["params"][3] == ZOOM_URL
    assert stats["sent"] == 2  # konfirmasi pendaftaran + link zoom


def test_early_publish_requires_override_reason(app):
    zoom.save(ZOOM_URL, "", "", False, "admin:test")
    timeutil.set_now(BEFORE_WINDOW)
    with pytest.raises(zoom.ZoomError, match="alasan"):
        zoom.publish("admin:test", override=True, reason="")
    assert zoom.publish("admin:test", override=True, reason="Uji coba panitia")


def test_auto_publish_by_worker(client, app):
    _register(client)
    zoom.save(ZOOM_URL, "", "", True, "admin:test")
    timeutil.set_now(BEFORE_WINDOW)
    scheduler.tick(force_all=True)
    assert not settings.zoom_published_at()
    timeutil.set_now(IN_WINDOW)
    scheduler.tick(force_all=True)
    assert settings.zoom_published_at()
    assert any(s["purpose"] == "zoom_link" for s in FakeProvider.sent)


def test_zoom_url_must_be_zoom_domain(app):
    with pytest.raises(zoom.ZoomError):
        zoom.save("https://evil.example.com/j/1", "", "", False, "admin:test")
    with pytest.raises(zoom.ZoomError):
        zoom.save("http://zoom.us/j/1", "", "", False, "admin:test")


def test_retry_then_permanent_failure(client, app):
    _register(client)
    FakeProvider.mode = "retry"
    notifications.process_queue()
    msg = Message.query.one()
    assert msg.status == "queued" and msg.attempts == 1 and msg.next_attempt_at > timeutil.utcnow()
    assert msg.last_error == "sementara"

    FakeProvider.mode = "fail"
    timeutil.set_now(msg.next_attempt_at)
    notifications.process_queue()
    assert Message.query.one().status == "failed"

    FakeProvider.mode = "ok"
    assert notifications.retry(Message.query.one(), "admin:test")
    notifications.process_queue()
    assert Message.query.one().status == "sent"


def test_opted_out_participant_is_skipped(client, app):
    p = _register(client)
    notifications.opt_out_phone(p.phone)
    assert Message.query.one().status == "skipped"
    assert notifications.channels_for(p) == []


def _meta_post(client, payload, secret="meta-secret"):
    body = json.dumps(payload).encode()
    return client.post("/webhooks/whatsapp/meta", data=body, content_type="application/json",
                       headers={"X-Hub-Signature-256": sign_payload(secret, body)})


def test_meta_webhook_verification_and_status(client, app):
    assert client.get("/webhooks/whatsapp/meta?hub.mode=subscribe&hub.verify_token=salah&hub.challenge=1").status_code == 403
    ok = client.get("/webhooks/whatsapp/meta?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=42")
    assert ok.get_data(as_text=True) == "42"

    p = _register(client)
    notifications.process_queue()
    wamid = Message.query.one().provider_message_id

    def status_payload(status, errors=None):
        st = {"id": wamid, "status": status, "recipient_id": p.phone}
        if errors:
            st["errors"] = errors
        return {"entry": [{"changes": [{"value": {"statuses": [st]}}]}]}

    assert _meta_post(client, status_payload("delivered"), secret="salah").status_code == 403
    assert _meta_post(client, status_payload("delivered")).status_code == 200
    assert Message.query.one().status == "delivered"
    _meta_post(client, status_payload("read"))
    _meta_post(client, status_payload("delivered"))  # tidak boleh turun status
    assert Message.query.one().status == "read"

    stop = {"entry": [{"changes": [{"value": {"messages": [
        {"from": p.phone, "type": "text", "text": {"body": "berhenti"}}]}}]}]}
    _meta_post(client, stop)
    assert Participant.query.one().wa_opted_out_at is not None


def test_meta_webhook_failed_status(client, app):
    _register(client)
    notifications.process_queue()
    msg = Message.query.one()
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": msg.provider_message_id, "status": "failed",
              "errors": [{"code": 131026, "title": "Message undeliverable"}]}]}}]}]}
    _meta_post(client, payload)
    msg = Message.query.one()
    assert msg.status == "failed" and "131026" in msg.last_error


def test_meta_provider_payload(app, monkeypatch):
    app.config.update(WA_META_PHONE_NUMBER_ID="111", WA_META_ACCESS_TOKEN="tok")
    provider = MetaCloudProvider()
    payload = provider.build_payload("6281234567890", "zoom_link", ["Siti", "Judul", "Minggu", "https://zoom.us/j/1", "a\nb"])
    tpl = payload["template"]
    assert tpl["name"] == "webinar_link_zoom" and tpl["language"]["code"] == "id"
    assert tpl["components"][0]["parameters"][4]["text"] == "a · b"
    assert clean_param("") == "-"

    class Resp:
        ok, status_code, text = True, 200, ""

        def json(self):
            return {"messages": [{"id": "wamid.ABC"}]}

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, headers=headers)
        return Resp()

    monkeypatch.setattr("app.services.whatsapp.meta_cloud.requests.post", fake_post)
    result = provider.send("6281234567890", "registration", "teks", ["a", "b", "c", "d"])
    assert result.ok and result.provider_message_id == "wamid.ABC"
    assert captured["url"].endswith("/111/messages") and captured["headers"]["Authorization"] == "Bearer tok"


def test_scheduled_campaign_runs_when_due(client, app):
    _register(client)
    when = datetime(2026, 10, 31, 9, 0)
    notifications.create_campaign("Pengingat H-1", "reminder", "all", when, "admin:test")
    timeutil.set_now(datetime(2026, 10, 31, 8, 0))
    scheduler.tick(force_all=True)
    assert not any(s["purpose"] == "reminder" for s in FakeProvider.sent)
    timeutil.set_now(when)
    scheduler.tick(force_all=True)
    assert any(s["purpose"] == "reminder" for s in FakeProvider.sent)
