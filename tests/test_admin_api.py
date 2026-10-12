from app import create_app
from app.extensions import db
from app.models import AdminUser, AuditLog, Participant

from .conftest import registration_form

TOKEN = "t" * 32


def test_admin_requires_login(client):
    resp = client.get("/admin/")
    assert resp.status_code == 302 and "/admin/login" in resp.headers["Location"]
    assert client.get("/admin/peserta/export.csv").status_code == 302


def test_admin_lockout(app, client):
    user = AdminUser(username="admin", password_hash="")
    user.set_password("kata-sandi-panjang-123")
    db.session.add(user)
    db.session.commit()
    for _ in range(5):
        assert client.post("/admin/login", data={"username": "admin", "password": "salah"}).status_code == 401
    resp = client.post("/admin/login", data={"username": "admin", "password": "kata-sandi-panjang-123"})
    assert resp.status_code == 401 and "dikunci" in resp.get_data(as_text=True)
    assert AuditLog.query.filter_by(action="admin.login_failed").count() == 5
    assert AuditLog.query.filter_by(action="admin.login_blocked").count() == 1


def test_admin_pages_render(admin_client):
    admin_client.post("/daftar", data=registration_form())
    pid = Participant.query.one().id
    for path in ["/admin/", "/admin/peserta", f"/admin/peserta/{pid}", "/admin/presensi", "/admin/zoom",
                 "/admin/pesan", "/admin/pesan/template", "/admin/sertifikat", "/admin/pengaturan",
                 "/admin/audit", "/admin/akun", "/admin/qr-pendaftaran.png", "/admin/sertifikat/pratinjau.pdf"]:
        assert admin_client.get(path).status_code == 200, path


def test_admin_actions(admin_client):
    admin_client.post("/daftar", data=registration_form())
    p = Participant.query.one()
    admin_client.post(f"/admin/peserta/{p.id}/aksi", data={"action": "attend"})
    admin_client.post(f"/admin/peserta/{p.id}/aksi", data={"action": "issue_cert"})
    p = Participant.query.one()
    assert p.attended and p.certificate
    resp = admin_client.post("/admin/pengaturan", data={"event_title": "Judul Baru", "event_start": "2026-11-01T16:00",
                                                         "registration_open": "1"})
    assert resp.status_code == 302
    assert "Judul Baru" in admin_client.get("/").get_data(as_text=True)
    resp = admin_client.post("/admin/zoom/simpan", data={"zoom_url": "https://zoom.us/j/999"})
    assert resp.status_code == 302
    assert AuditLog.query.filter_by(action="zoom.save").count() == 1


def test_export_csv_escapes_formulas(admin_client):
    admin_client.post("/daftar", data=registration_form(institution="=HYPERLINK(\"http://x\")"))
    csv_text = admin_client.get("/admin/peserta/export.csv").get_data(as_text=True)
    assert "Siti Rahma" in csv_text
    assert "'=HYPERLINK" in csv_text


def test_public_api(client):
    event = client.get("/api/v1/event").get_json()
    assert event["speaker"]["name"] == "Fadel Rasyid" and event["registration"]["open"]
    payload = {"full_name": "Andi Saputra", "email": "andi@example.com", "phone": "081377778888",
               "category": "startup", "institution": "Startup X", "privacy_consent": True, "wa_consent": True}
    resp = client.post("/api/v1/registrations", json=payload)
    assert resp.status_code == 201 and resp.get_json()["participant_url"].startswith("https://webinar.test/peserta/")
    assert client.post("/api/v1/registrations", json=payload).status_code == 409
    assert client.post("/api/v1/registrations", json={**payload, "email": "x"}).status_code == 422


def test_admin_api_requires_token(client):
    assert client.get("/api/v1/admin/stats").status_code == 401
    assert client.get("/api/v1/admin/stats", headers={"Authorization": "Bearer salah"}).status_code == 401
    client.post("/daftar", data=registration_form())
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert client.get("/api/v1/admin/stats", headers=headers).get_json()["registered"] == 1
    item = client.get("/api/v1/admin/participants", headers=headers).get_json()["items"][0]
    resp = client.post(f"/api/v1/admin/participants/{item['id']}/attendance", json={"attended": True}, headers=headers)
    assert resp.get_json()["attended"] is True


def test_csrf_enforced(tmp_path):
    app = create_app({"SECRET_KEY": "x", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'c.db'}",
                      "RATELIMIT_ENABLED": False})
    with app.app_context():
        db.create_all()
        resp = app.test_client().post("/daftar", data=registration_form())
        assert resp.status_code == 400
        assert Participant.query.count() == 0


def test_migrations_create_schema(tmp_path):
    from flask_migrate import upgrade
    from sqlalchemy import inspect
    app = create_app({"SECRET_KEY": "x", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'm.db'}"})
    with app.app_context():
        upgrade()
        tables = set(inspect(db.engine).get_table_names())
    assert {"participants", "messages", "certificates", "campaigns", "settings", "audit_logs",
            "admin_users", "integration_events"} <= tables


def test_backup_creates_zip(app):
    from app.services import backup
    path = backup.create_backup()
    assert path.exists() and path.suffix == ".zip"
