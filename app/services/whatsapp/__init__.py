from flask import current_app

from .base import SendResult, WhatsAppProvider
from .console import ConsoleProvider
from .fonnte import FonnteProvider
from .meta_cloud import MetaCloudProvider

PROVIDERS: dict[str, type[WhatsAppProvider]] = {
    "meta": MetaCloudProvider,
    "fonnte": FonnteProvider,
    "console": ConsoleProvider,
}


def get_provider() -> WhatsAppProvider | None:
    """Provider aktif sesuai WHATSAPP_PROVIDER, atau None bila nonaktif/belum dikonfigurasi."""
    name = current_app.config["WHATSAPP_PROVIDER"]
    if name == "console" and current_app.config["APP_ENV"] == "production":
        return None
    cls = PROVIDERS.get(name)
    if cls is None:
        return None
    provider = cls()
    return provider if provider.is_configured() else None


def provider_status() -> tuple[str, bool]:
    name = current_app.config["WHATSAPP_PROVIDER"]
    return name, get_provider() is not None


__all__ = ["SendResult", "WhatsAppProvider", "get_provider", "provider_status", "PROVIDERS"]
