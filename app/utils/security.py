import hashlib
import hmac

from flask import current_app, request


def hash_ip(ip: str | None = None) -> str | None:
    """Simpan IP sebagai hash ber-salt (bukan IP mentah) untuk audit & anti-penyalahgunaan."""
    ip = ip if ip is not None else (request.remote_addr if request else None)
    if not ip:
        return None
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, ip.encode(), hashlib.sha256).hexdigest()


def sign_payload(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, header_value: str | None) -> bool:
    if not secret or not header_value:
        return False
    return hmac.compare_digest(sign_payload(secret, body), header_value.strip())


def parse_api_tokens(raw: str) -> dict[str, str]:
    """'bot:abc,crm:def' -> {'abc': 'bot', 'def': 'crm'}"""
    tokens = {}
    for item in (raw or "").split(","):
        name, sep, token = item.strip().partition(":")
        if sep and token and len(token) >= 24:
            tokens[token.strip()] = name.strip()
    return tokens


def match_api_token(presented: str) -> str | None:
    for token, name in parse_api_tokens(current_app.config["API_TOKENS"]).items():
        if hmac.compare_digest(token, presented):
            return name
    return None


def csv_safe(value) -> str:
    """Cegah CSV/formula injection saat file dibuka di Excel/Sheets."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text
