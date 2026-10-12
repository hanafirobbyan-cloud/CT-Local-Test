from dataclasses import dataclass


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None
    retryable: bool = False


class WhatsAppProvider:
    """Antarmuka provider. Tambahkan provider baru dengan mewarisi kelas ini
    lalu daftarkan di services/whatsapp/__init__.py."""

    name = "base"

    def is_configured(self) -> bool:
        raise NotImplementedError

    def send(self, to: str, purpose: str, text: str, template_params: list[str]) -> SendResult:
        """to: nomor E.164 tanpa '+'. text: pesan lengkap (untuk provider teks bebas).
        template_params: parameter template (untuk provider berbasis template, mis. Meta)."""
        raise NotImplementedError
