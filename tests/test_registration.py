from app.models import Message, Participant
from app.utils.phone import normalize_phone

from .conftest import registration_form


def test_landing_shows_tor_details(client):
    html = client.get("/").get_data(as_text=True)
    assert "Penerapan Logika Digital untuk Membangun Startup dan UMKM" in html
    assert "Growth Startup dan UMKM" in html
    assert "Minggu, 01 November 2026" in html
    assert "Fadel Rasyid" in html and "Nayla Tazkiyah Fadli" in html
    assert "Pemaparan materi" in html
    assert "082136190243" in html
    assert "Poin SKEM" in html


def test_security_headers(client):
    resp = client.get("/")
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_register_success_shows_confirmation(client, app):
    resp = client.post("/daftar", data=registration_form())
    assert resp.status_code == 302
    assert "/peserta/" in resp.headers["Location"] and "baru=1" in resp.headers["Location"]
    page = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "Pendaftaran berhasil" in page

    p = Participant.query.one()
    assert p.phone == "6281234567890"
    assert p.email == "siti@example.com"
    assert p.wa_consent and p.privacy_consent_at
    msg = Message.query.one()
    assert (msg.purpose, msg.channel, msg.status) == ("registration", "whatsapp", "queued")


def test_duplicate_email_and_phone_rejected(client):
    assert client.post("/daftar", data=registration_form()).status_code == 302
    resp = client.post("/daftar", data=registration_form(phone="081299998888"))
    assert resp.status_code == 400 and "sudah terdaftar" in resp.get_data(as_text=True)
    resp = client.post("/daftar", data=registration_form(email="lain@example.com", phone="+62 812 3456 7890"))
    assert resp.status_code == 400 and "Nomor WhatsApp ini sudah terdaftar" in resp.get_data(as_text=True)
    resp = client.post("/daftar", data=registration_form(email="SITI@Example.com", phone="081211112222"))
    assert resp.status_code == 400
    assert Participant.query.count() == 1


def test_validation_errors(client):
    resp = client.post("/daftar", data=registration_form(full_name="<script>", email="salah", phone="123",
                                                         student_id="", privacy_consent=""))
    html = resp.get_data(as_text=True)
    assert resp.status_code == 400
    for text in ("Isi nama lengkap", "Format email", "Nomor WhatsApp tidak valid", "NIM wajib", "kebijakan privasi"):
        assert text in html
    assert "<script>" not in html.split("<main")[1].split("</main>")[0].replace("&lt;script&gt;", "")
    assert Participant.query.count() == 0


def test_non_student_does_not_need_nim(client):
    resp = client.post("/daftar", data=registration_form(category="umkm", student_id="", study_program=""))
    assert resp.status_code == 302


def test_honeypot_blocks_bots(client):
    client.post("/daftar", data=registration_form(website="http://spam"))
    assert Participant.query.count() == 0


def test_no_whatsapp_without_consent(client):
    client.post("/daftar", data=registration_form(wa_consent=""))
    assert Participant.query.one().wa_consent is False
    assert Message.query.count() == 0  # email belum dikonfigurasi -> tidak ada kanal


def test_registration_closed(client, app):
    from app.services import settings_service
    settings_service.set_many({"registration_open": False})
    client.post("/daftar", data=registration_form())
    assert Participant.query.count() == 0


def test_check_registration_does_not_leak(client):
    client.post("/daftar", data=registration_form())
    a = client.post("/cek-pendaftaran", data={"identifier": "siti@example.com"}).get_data(as_text=True)
    b = client.post("/cek-pendaftaran", data={"identifier": "tidakada@example.com"}).get_data(as_text=True)
    assert a == b
    assert Message.query.filter_by(purpose="registration").count() == 2


def test_phone_normalization():
    assert normalize_phone("0812-3456-7890") == "6281234567890"
    assert normalize_phone("+62 812 3456 7890") == "6281234567890"
    assert normalize_phone("812 3456 7890") == "6281234567890"
    assert normalize_phone("021-555-1234") is None  # bukan nomor seluler
    assert normalize_phone("+60 12-345 6789") == "60123456789"
    assert normalize_phone("abc") is None
