"""Unggahan file admin (foto, logo, latar & tanda tangan sertifikat, font TTF)."""
import secrets
from pathlib import Path

from flask import current_app
from PIL import Image

IMAGE_FORMATS = {"PNG": ".png", "JPEG": ".jpg"}


class UploadError(Exception):
    pass


def upload_dir() -> Path:
    path = Path(current_app.config["UPLOAD_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(storage, kind: str) -> str:
    """Validasi isi file (bukan hanya ekstensi), simpan dengan nama acak, kembalikan nama file."""
    data = storage.read()
    if not data:
        raise UploadError("File kosong.")
    if kind == "font":
        if data[:4] not in (b"\x00\x01\x00\x00", b"true"):
            raise UploadError("Font harus berformat TrueType (.ttf).")
        ext = ".ttf"
    else:
        try:
            from io import BytesIO
            with Image.open(BytesIO(data)) as img:
                fmt = img.format
                img.verify()
        except Exception:  # noqa: BLE001
            raise UploadError("File bukan gambar PNG/JPG yang valid.") from None
        if fmt not in IMAGE_FORMATS:
            raise UploadError("Gambar harus berformat PNG atau JPG.")
        ext = IMAGE_FORMATS[fmt]
    name = f"{kind}-{secrets.token_hex(8)}{ext}"
    (upload_dir() / name).write_bytes(data)
    return name


def path_for(name: str | None) -> Path | None:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    path = upload_dir() / name
    return path if path.is_file() else None
