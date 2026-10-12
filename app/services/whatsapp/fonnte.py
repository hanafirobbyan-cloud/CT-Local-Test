"""Fonnte (https://fonnte.com) — gateway WhatsApp pihak ketiga yang populer di Indonesia.

Fonnte bekerja dengan menautkan perangkat WhatsApp biasa, BUKAN WhatsApp Business Platform
resmi. Gunakan hanya bila Anda memahami risikonya (lihat docs/WHATSAPP.md). Untuk produksi,
provider "meta" lebih direkomendasikan.
"""
import requests
from flask import current_app

from .base import SendResult, WhatsAppProvider

API_URL = "https://api.fonnte.com/send"


class FonnteProvider(WhatsAppProvider):
    name = "fonnte"

    def __init__(self):
        self.token = current_app.config["FONNTE_TOKEN"]

    def is_configured(self) -> bool:
        return bool(self.token)

    def send(self, to: str, purpose: str, text: str, template_params: list[str]) -> SendResult:
        try:
            resp = requests.post(API_URL, headers={"Authorization": self.token},
                                 data={"target": to, "message": text, "countryCode": "0"}, timeout=20)
        except requests.RequestException as exc:
            return SendResult(ok=False, error=f"Koneksi ke Fonnte gagal: {exc}", retryable=True)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.ok and data.get("status") is True:
            ids = data.get("id") or []
            message_id = str(ids[0]) if isinstance(ids, list) and ids else str(ids or "")
            return SendResult(ok=True, provider_message_id=message_id or None)
        reason = data.get("reason") or data.get("detail") or resp.text[:300]
        retryable = resp.status_code == 429 or resp.status_code >= 500
        return SendResult(ok=False, error=f"[{resp.status_code}] {reason}", retryable=retryable)
