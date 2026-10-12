"""WhatsApp Business Platform — Cloud API resmi dari Meta.

Pesan yang dimulai oleh bisnis WAJIB memakai template yang sudah disetujui Meta.
Nama template dan urutan parameternya dijelaskan di docs/WHATSAPP.md.
"""
import re

import requests
from flask import current_app

from .base import SendResult, WhatsAppProvider

TEMPLATE_CONFIG_KEYS = {
    "registration": "WA_TEMPLATE_REGISTRATION",
    "zoom_link": "WA_TEMPLATE_ZOOM_LINK",
    "reminder": "WA_TEMPLATE_REMINDER",
    "certificate": "WA_TEMPLATE_CERTIFICATE",
    "broadcast": "WA_TEMPLATE_ANNOUNCEMENT",
}

# Kode error Meta yang bersifat sementara (aman untuk dicoba ulang).
RETRYABLE_CODES = {1, 2, 4, 17, 341, 80007, 130429, 131000, 131016, 131048, 131056, 133004}


def clean_param(value: str) -> str:
    """Parameter template tidak boleh berisi baris baru, tab, atau >4 spasi berurutan."""
    value = re.sub(r"[\r\n\t]+", " · ", value or "-")
    value = re.sub(r" {4,}", "   ", value).strip()
    return value[:1000] or "-"


class MetaCloudProvider(WhatsAppProvider):
    name = "meta"

    def __init__(self):
        cfg = current_app.config
        self.phone_number_id = cfg["WA_META_PHONE_NUMBER_ID"]
        self.token = cfg["WA_META_ACCESS_TOKEN"]
        self.version = cfg["WA_META_API_VERSION"]
        self.language = cfg["WA_TEMPLATE_LANGUAGE"]
        self.templates = {purpose: cfg[key] for purpose, key in TEMPLATE_CONFIG_KEYS.items()}

    def is_configured(self) -> bool:
        return bool(self.phone_number_id and self.token)

    def build_payload(self, to: str, purpose: str, template_params: list[str]) -> dict:
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": self.templates[purpose],
                "language": {"code": self.language},
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": clean_param(p)} for p in template_params],
                }],
            },
        }

    def send(self, to: str, purpose: str, text: str, template_params: list[str]) -> SendResult:
        url = f"https://graph.facebook.com/{self.version}/{self.phone_number_id}/messages"
        try:
            resp = requests.post(url, json=self.build_payload(to, purpose, template_params),
                                 headers={"Authorization": f"Bearer {self.token}"}, timeout=20)
        except requests.RequestException as exc:
            return SendResult(ok=False, error=f"Koneksi ke Meta gagal: {exc}", retryable=True)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.ok and data.get("messages"):
            return SendResult(ok=True, provider_message_id=data["messages"][0].get("id"))
        err = data.get("error", {}) if isinstance(data, dict) else {}
        code = err.get("code")
        message = err.get("error_data", {}).get("details") or err.get("message") or resp.text[:300]
        retryable = resp.status_code == 429 or resp.status_code >= 500 or code in RETRYABLE_CODES
        return SendResult(ok=False, error=f"[{resp.status_code}/{code}] {message}", retryable=retryable)
