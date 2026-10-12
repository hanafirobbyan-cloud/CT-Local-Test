import pytest

from app import create_app
from app.extensions import db as _db
from app.models import AdminUser
from app.services.whatsapp import PROVIDERS
from app.services.whatsapp.base import SendResult, WhatsAppProvider
from app.utils import timeutil


class FakeProvider(WhatsAppProvider):
    """Provider uji: mencatat pesan dan mensimulasikan hasil sukses/gagal."""
    name = "fake"
    sent: list = []
    mode = "ok"

    def is_configured(self):
        return True

    def send(self, to, purpose, text, template_params):
        FakeProvider.sent.append({"to": to, "purpose": purpose, "text": text, "params": template_params})
        if FakeProvider.mode == "ok":
            return SendResult(ok=True, provider_message_id=f"wamid.TEST{len(FakeProvider.sent)}")
        if FakeProvider.mode == "retry":
            return SendResult(ok=False, error="sementara", retryable=True)
        return SendResult(ok=False, error="permanen", retryable=False)


@pytest.fixture
def app(tmp_path):
    PROVIDERS["fake"] = FakeProvider
    FakeProvider.sent = []
    FakeProvider.mode = "ok"
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
        "WHATSAPP_PROVIDER": "fake",
        "WA_SEND_DELAY_MS": 0,
        "UPLOAD_DIR": tmp_path / "uploads",
        "CERT_DIR": tmp_path / "certs",
        "BACKUP_DIR": tmp_path / "backups",
        "PUBLIC_BASE_URL": "https://webinar.test",
        "WA_META_APP_SECRET": "meta-secret",
        "WA_META_VERIFY_TOKEN": "verify-me",
        "API_TOKENS": "bot:" + "t" * 32,
    })
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()
    timeutil.set_now(None)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(app):
    user = AdminUser(username="admin", password_hash="")
    user.set_password("kata-sandi-panjang-123")
    _db.session.add(user)
    _db.session.commit()
    c = app.test_client()
    resp = c.post("/admin/login", data={"username": "admin", "password": "kata-sandi-panjang-123"})
    assert resp.status_code == 302
    return c


def registration_form(**overrides):
    data = {
        "full_name": "Siti Rahma", "email": "siti@example.com", "phone": "0812-3456-7890",
        "category": "mahasiswa", "institution": "Universitas Contoh", "student_id": "5426600001",
        "study_program": "Bisnis Digital", "privacy_consent": "1", "wa_consent": "1",
    }
    data.update(overrides)
    return data
