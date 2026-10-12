from datetime import datetime

import pytest

from app.models import Certificate, Message, Participant
from app.services import attendance, certificates, notifications
from app.services import settings_service as settings
from app.utils import timeutil

from .conftest import FakeProvider, registration_form

DURING_EVENT = datetime(2026, 11, 1, 9, 30)      # 16:30 WIB
AFTER_EVENT = datetime(2026, 11, 1, 12, 5)       # 19:05 WIB (selesai 18:00 + 60 menit)

ZOOM_CSV = """Meeting ID,Topic,Start Time
123 4567 890,Webinar,11/01/2026 04:00:00 PM

Name (Original Name),User Email,Join Time,Leave Time,Duration (Minutes),Guest
Siti Rahma,siti@example.com,11/01/2026 04:01:00 PM,11/01/2026 05:00:00 PM,59,No
Siti Rahma,siti@example.com,11/01/2026 05:05:00 PM,11/01/2026 05:50:00 PM,45,No
Budi,budi@example.com,11/01/2026 04:00:00 PM,11/01/2026 04:05:00 PM,5,No
Orang Asing,asing@example.com,11/01/2026 04:00:00 PM,11/01/2026 05:00:00 PM,60,Yes
Tanpa Email,,11/01/2026 04:00:00 PM,11/01/2026 05:00:00 PM,60,Yes
"""


def _register(client, **kw):
    client.post("/daftar", data=registration_form(**kw))
    return Participant.query.filter_by(email=kw.get("email", "siti@example.com")).one()


def test_attendance_code_rules(client, app):
    p = _register(client)
    settings.set_many({"attendance_code": "LOGIKA26", "attendance_code_open": True})
    timeutil.set_now(datetime(2026, 11, 1, 8, 0))
    assert attendance.submit_code(p, "LOGIKA26")[0] is False  # acara belum mulai
    timeutil.set_now(DURING_EVENT)
    assert attendance.submit_code(p, "salah")[0] is False
    resp = client.post(f"/peserta/{p.access_token}/presensi", data={"code": "logika26"})
    assert resp.status_code == 302
    assert Participant.query.one().attended and Participant.query.one().attendance_method == "code"


def test_zoom_csv_import(client, app):
    _register(client)
    _register(client, email="budi@example.com", phone="081300000002", category="umkm", student_id="")
    settings.set_many({"attendance_min_minutes": 30})
    summary = attendance.apply_report(attendance.parse_zoom_csv(ZOOM_CSV.encode("utf-8-sig")), "zoom_csv", "admin:t")
    assert summary["marked"] == 1
    assert summary["unmatched"] == ["asing@example.com"]
    assert summary["no_email"] == ["Tanpa Email"]
    assert len(summary["below_threshold"]) == 1
    siti = Participant.query.filter_by(email="siti@example.com").one()
    assert siti.attended and siti.attendance_minutes == 104
    assert not Participant.query.filter_by(email="budi@example.com").one().attended


def test_csv_without_required_columns_rejected():
    with pytest.raises(ValueError):
        attendance.parse_zoom_csv(b"a,b\n1,2\n")


def test_certificate_only_for_attended(client, app):
    p = _register(client)
    absent = _register(client, email="absen@example.com", phone="081300000003")
    with pytest.raises(ValueError):
        certificates.issue(absent, "admin:t")
    attendance.mark(p, True, "manual", "admin:t")
    assert certificates.issue_all("admin:t") == 1
    assert Certificate.query.count() == 1
    cert = Participant.query.filter_by(email="siti@example.com").one().certificate
    assert cert.number == "WLD-2026-0001" or cert.number.endswith("0001")
    assert certificates.file_path(cert).read_bytes().startswith(b"%PDF")

    resp = client.get(f"/sertifikat/{cert.download_token}")
    assert resp.status_code == 200 and resp.mimetype == "application/pdf"
    assert "Sertifikat valid" in client.get(f"/verifikasi/{cert.verify_code}").get_data(as_text=True)
    assert client.get("/verifikasi/tidakada").status_code == 404

    attendance.mark(Participant.query.filter_by(email="siti@example.com").one(), False, "manual", "admin:t")
    assert client.get(f"/sertifikat/{cert.download_token}").status_code == 404
    assert "dicabut" in client.get(f"/verifikasi/{cert.verify_code}").get_data(as_text=True)


def test_auto_certificate_after_event(client, app):
    p = _register(client)
    _register(client, email="absen@example.com", phone="081300000003")
    attendance.mark(p, True, "manual", "admin:t")
    notifications.process_queue()
    timeutil.set_now(DURING_EVENT)
    assert certificates.auto_tick() == 0
    timeutil.set_now(AFTER_EVENT)
    assert certificates.auto_tick() == 1
    assert certificates.auto_tick() == 0  # tidak dobel
    notifications.process_queue()
    cert_msgs = [s for s in FakeProvider.sent if s["purpose"] == "certificate"]
    assert len(cert_msgs) == 1 and cert_msgs[0]["to"] == p.phone
    assert "https://webinar.test/sertifikat/" in cert_msgs[0]["text"]
    assert Message.query.filter_by(purpose="certificate").count() == 1


def test_certificate_unicode_name_without_custom_font(app):
    pdf = certificates.render_pdf("Siti Ṛahmā – Nur’aini", "WLD-2026-0009", "https://webinar.test/verifikasi/x")
    assert pdf.startswith(b"%PDF")
