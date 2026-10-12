"""Utilitas waktu. Database menyimpan waktu UTC tanpa zona (naive); tampilan memakai APP_TIMEZONE."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app, has_app_context

DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
             "Agustus", "September", "Oktober", "November", "Desember"]

_now_override: datetime | None = None


def set_now(value: datetime | None) -> None:
    """Hanya untuk pengujian: membekukan waktu sekarang (UTC naive)."""
    global _now_override
    _now_override = value


def utcnow() -> datetime:
    if _now_override is not None:
        return _now_override
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_tz() -> ZoneInfo:
    name = current_app.config["APP_TIMEZONE"] if has_app_context() else "Asia/Jakarta"
    return ZoneInfo(name)


def parse_local(value: str | None) -> datetime | None:
    """'2026-11-01T16:00' (waktu lokal) -> datetime UTC naive."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz())
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(local_tz())


def to_local_input(dt: datetime | None) -> str:
    """Nilai untuk <input type=datetime-local>."""
    local = to_local(dt)
    return local.strftime("%Y-%m-%dT%H:%M") if local else ""


def fmt_local(dt: datetime | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    local = to_local(dt)
    return local.strftime(fmt) if local else "-"


def tz_label() -> str:
    return {"Asia/Jakarta": "WIB", "Asia/Makassar": "WITA", "Asia/Jayapura": "WIT"}.get(
        str(local_tz()), str(local_tz()))


def format_indo_date(dt_utc: datetime | None, with_day: bool = True) -> str:
    local = to_local(dt_utc)
    if not local:
        return "-"
    text = f"{local.day:02d} {MONTHS_ID[local.month - 1]} {local.year}"
    return f"{DAYS_ID[local.weekday()]}, {text}" if with_day else text


def format_indo_time(dt_utc: datetime | None) -> str:
    local = to_local(dt_utc)
    return f"{local:%H.%M} {tz_label()}" if local else "-"
