"""Provider khusus PENGEMBANGAN: menulis pesan ke log, tidak mengirim WhatsApp sungguhan.
Otomatis ditolak bila APP_ENV=production."""
import logging
import uuid

from .base import SendResult, WhatsAppProvider

log = logging.getLogger("whatsapp.console")


class ConsoleProvider(WhatsAppProvider):
    name = "console"

    def is_configured(self) -> bool:
        return True

    def send(self, to: str, purpose: str, text: str, template_params: list[str]) -> SendResult:
        log.warning("[WA-CONSOLE — TIDAK BENAR-BENAR DIKIRIM] ke=%s tujuan=%s\n%s", to, purpose, text)
        return SendResult(ok=True, provider_message_id=f"console-{uuid.uuid4().hex[:12]}")
