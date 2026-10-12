"""Verifikasi kehadiran. Sumber: kode presensi saat acara, laporan peserta Zoom (CSV/API),
atau penandaan manual admin. Hanya peserta yang hadir yang berhak atas sertifikat."""
import csv
import hmac
import io
from collections import defaultdict

from ..extensions import db
from ..models import Participant
from ..utils import timeutil
from . import audit, integrations
from . import settings_service as settings


def mark(p: Participant, attended: bool, method: str, actor: str, minutes: int | None = None,
         commit: bool = True) -> bool:
    """Ubah status hadir. Mengembalikan True bila ada perubahan."""
    changed = False
    if attended and not p.attended:
        p.attended = True
        p.attendance_method = method
        p.attended_at = timeutil.utcnow()
        changed = True
        integrations.emit("attendance.marked", integrations.participant_payload(p))
    elif not attended and p.attended:
        p.attended = False
        p.attendance_method = None
        p.attended_at = None
        changed = True
        if p.certificate and not p.certificate.revoked_at:
            from . import certificates
            certificates.revoke(p.certificate, "Status kehadiran dibatalkan.", actor, commit=False)
    if minutes is not None:
        p.attendance_minutes = int(minutes)
    if changed:
        audit.record(actor, "attendance.mark" if attended else "attendance.unmark", "participant",
                     p.public_id, {"method": method, "minutes": minutes}, commit=False)
    if commit:
        db.session.commit()
    return changed


def submit_code(p: Participant, code: str) -> tuple[bool, str]:
    if p.status != "registered":
        return False, "Pendaftaran Anda tidak aktif."
    if p.attended:
        return True, "Kehadiran Anda sudah tercatat."
    expected = (settings.get("attendance_code") or "").strip().upper()
    if not settings.get("attendance_code_open") or not expected:
        return False, "Presensi belum dibuka atau sudah ditutup."
    start = settings.event_start()
    if start and timeutil.utcnow() < start:
        return False, "Presensi hanya dapat diisi saat acara berlangsung."
    if not hmac.compare_digest((code or "").strip().upper().encode(), expected.encode()):
        return False, "Kode presensi salah."
    mark(p, True, "code", f"participant:{p.public_id}")
    return True, "Terima kasih, kehadiran Anda telah tercatat."


def parse_zoom_csv(raw: bytes) -> list[dict]:
    """Baca laporan peserta Zoom (Reports > Usage > Participants > Export).
    Mendukung format dengan blok info meeting di atas tabel peserta."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    rows = list(csv.reader(io.StringIO(text)))
    header_idx = None
    for idx, row in enumerate(rows):
        lowered = [c.strip().lower() for c in row]
        if any("email" in c for c in lowered) and any(
                k in c for c in lowered for k in ("duration", "durasi", "minutes", "menit")):
            header_idx = idx
            break
    if header_idx is None:
        raise ValueError("Kolom Email dan Duration tidak ditemukan. Pastikan file adalah laporan peserta Zoom.")
    header = [c.strip().lower() for c in rows[header_idx]]

    def find(*keys, prefer=None):
        if prefer:
            for i, c in enumerate(header):
                if prefer in c:
                    return i
        for i, c in enumerate(header):
            if any(k in c for k in keys):
                return i
        return None

    email_i = find("email")
    dur_i = find("duration", "durasi", "minutes", "menit", prefer="total duration")
    name_i = find("name", "nama")
    result = []
    for row in rows[header_idx + 1:]:
        if not row or all(not c.strip() for c in row):
            continue
        try:
            minutes = float((row[dur_i] if dur_i is not None and dur_i < len(row) else "0").replace(",", ".") or 0)
        except ValueError:
            minutes = 0
        result.append({
            "name": row[name_i].strip() if name_i is not None and name_i < len(row) else "",
            "email": row[email_i].strip().lower() if email_i < len(row) else "",
            "minutes": minutes,
        })
    return result


def apply_report(rows: list[dict], method: str, actor: str) -> dict:
    """Cocokkan laporan Zoom dengan peserta berdasarkan email (durasi dijumlahkan bila re-join)."""
    min_minutes = settings.get("attendance_min_minutes")
    totals: dict[str, float] = defaultdict(float)
    no_email = []
    for row in rows:
        if row["email"]:
            totals[row["email"]] += row["minutes"]
        elif row["name"]:
            no_email.append(row["name"])
    summary = {"rows": len(rows), "marked": 0, "already": 0, "below_threshold": [], "unmatched": [],
               "no_email": sorted(set(no_email)), "min_minutes": min_minutes}
    for email, minutes in totals.items():
        p = db.session.query(Participant).filter_by(email=email, status="registered").first()
        if not p:
            summary["unmatched"].append(email)
            continue
        if minutes < max(min_minutes, 0.01):
            p.attendance_minutes = int(minutes)
            summary["below_threshold"].append(f"{p.full_name} ({int(minutes)} menit)")
            continue
        if p.attended:
            p.attendance_minutes = int(minutes)
            summary["already"] += 1
        elif mark(p, True, method, actor, minutes=int(minutes), commit=False):
            summary["marked"] += 1
    audit.record(actor, "attendance.import", details={k: (len(v) if isinstance(v, list) else v)
                                                     for k, v in summary.items()}, commit=False)
    db.session.commit()
    return summary
