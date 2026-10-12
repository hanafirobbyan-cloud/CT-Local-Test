"""Pengiriman email via SMTP (Gmail Workspace, Mailgun, SendGrid, Brevo, dsb.)."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

from flask import current_app

from .whatsapp.base import SendResult


def is_configured() -> bool:
    cfg = current_app.config
    return bool(cfg["SMTP_HOST"] and cfg["MAIL_FROM"])


def send_email(to: str, subject: str, text: str) -> SendResult:
    cfg = current_app.config
    msg = EmailMessage()
    msg["From"] = cfg["MAIL_FROM"]
    msg["To"] = to
    msg["Subject"] = subject
    msg_id = make_msgid(domain=cfg["MAIL_FROM"].rpartition("@")[2].strip(">") or None)
    msg["Message-ID"] = msg_id
    msg.set_content(text)
    try:
        if cfg["SMTP_SECURITY"] == "ssl":
            server = smtplib.SMTP_SSL(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=30,
                                      context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=30)
        with server:
            if cfg["SMTP_SECURITY"] == "starttls":
                server.starttls(context=ssl.create_default_context())
            if cfg["SMTP_USERNAME"]:
                server.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"])
            server.send_message(msg)
    except smtplib.SMTPRecipientsRefused as exc:
        return SendResult(ok=False, error=f"Alamat ditolak: {exc}", retryable=False)
    except smtplib.SMTPAuthenticationError as exc:
        return SendResult(ok=False, error=f"Login SMTP gagal: {exc}", retryable=False)
    except (smtplib.SMTPException, OSError) as exc:
        return SendResult(ok=False, error=f"SMTP error: {exc}", retryable=True)
    return SendResult(ok=True, provider_message_id=msg_id)
