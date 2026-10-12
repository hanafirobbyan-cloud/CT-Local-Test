import re


def normalize_phone(raw: str | None) -> str | None:
    """Normalisasi nomor WhatsApp ke format E.164 tanpa '+'.

    '0812-3456-7890', '+62 812 3456 7890', '812 3456 7890' -> '6281234567890'.
    Nomor luar negeri harus diawali '+kode negara'. Mengembalikan None bila tidak valid.
    """
    if not raw:
        return None
    raw = raw.strip()
    international = raw.startswith("+") or raw.startswith("00")
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("00"):
        digits = digits[2:]
    if not digits:
        return None
    if not international:
        if digits.startswith("0"):
            digits = "62" + digits[1:]
        elif digits.startswith("8"):
            digits = "62" + digits
    if digits.startswith("62"):
        # Nomor seluler Indonesia: 62 8xx, total 11–15 digit.
        if not re.fullmatch(r"628\d{8,12}", digits):
            return None
        return digits
    if not international:
        return None
    return digits if 8 <= len(digits) <= 15 else None


def wa_me_link(local_number: str) -> str:
    normalized = normalize_phone(local_number)
    return f"https://wa.me/{normalized}" if normalized else ""
