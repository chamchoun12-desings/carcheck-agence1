"""Documents du client envoyés avec sa réservation : pièce d'identité (CIN recto/verso ou passeport) et permis.
Données personnelles sensibles (INPDP) :
  - photos seulement, aucun numéro de document enregistré ;
  - visibles par l'agence connectée uniquement, jamais par un lien public, jamais envoyées à l'IA ;
  - supprimées si la réservation est refusée ou annulée, à la clôture de la location,
    et au plus tard DOCS_RETENTION_DAYS jours après la fin prévue."""
import datetime
import shutil
import time

from . import db
from .config import DOCS_RETENTION_DAYS, VAULT

SLOTS = {  # nom -> libellé
    "id_front": "Pièce d’identité · recto (ou page photo du passeport)",
    "id_back": "CIN · verso",
    "license_front": "Permis · recto",
    "license_back": "Permis · verso",
}
MAX_BYTES = 10_000_000
ID_TYPES = {"cin": "Carte d’identité (CIN)", "passport": "Passeport"}


class DocError(Exception):
    pass


def file_kind(b):
    """Extension sûre d'après le contenu (pas d'après le nom envoyé)."""
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    if b[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc", b"ftypmsf1"):
        return "heic"
    if b[:5] == b"%PDF-":
        return "pdf"
    return None


def _date(v, label):
    if not v:
        return None
    try:
        return datetime.date.fromisoformat(v.strip()[:10])
    except ValueError:
        raise DocError(f"date d’expiration {label} invalide")


def validate(files, id_type, id_expiry, license_expiry, end_ts, required=True):
    """files = {slot: bytes}. Lève DocError avec un message clair pour le client."""
    files = {k: v for k, v in files.items() if v}
    if id_type not in ID_TYPES:
        raise DocError("choisissez carte d’identité ou passeport")
    for k, b in files.items():
        if k not in SLOTS:
            raise DocError("document inconnu")
        if len(b) > MAX_BYTES:
            raise DocError(f"{SLOTS[k]} : fichier trop lourd (10 Mo maximum)")
        if not file_kind(b):
            raise DocError(f"{SLOTS[k]} : envoyez une photo (JPEG, PNG, HEIC) ou un PDF")
    if required:
        need = ["id_front", "license_front"] + (["id_back"] if id_type == "cin" else [])
        missing = [SLOTS[k] for k in need if k not in files]
        if missing:
            raise DocError("document manquant : " + ", ".join(missing))
    end = datetime.date.fromtimestamp(end_ts)
    lic = _date(license_expiry, "du permis")
    if required and not lic:
        raise DocError("indiquez la date de validité de votre permis")
    if lic and lic < end:
        raise DocError(f"votre permis n’est plus valable à la fin de la location (expire le {lic:%d/%m/%Y})")
    idx = _date(id_expiry, "de la pièce d’identité")
    if id_type == "passport" and required and not idx:
        raise DocError("indiquez la date d’expiration du passeport")
    if idx and idx < end:
        raise DocError(f"votre pièce d’identité n’est plus valable à la fin de la location (expire le {idx:%d/%m/%Y})")
    return {"id_expiry": idx.isoformat() if idx else None, "license_expiry": lic.isoformat() if lic else None}


def folder(rid):
    return VAULT / "bookings" / str(int(rid))


def save(rid, files, id_type, dates):
    d = folder(rid)
    d.mkdir(parents=True, exist_ok=True)
    for k, b in files.items():
        if not b:
            continue
        for old in d.glob(f"{k}.*"):
            old.unlink()
        (d / f"{k}.{file_kind(b)}").write_bytes(b)
    with db.connect() as con:
        con.execute("UPDATE reservations SET id_doc_type=?, id_expiry=?, license_expiry=?, docs_status='received',"
                    " docs_note=NULL, docs_consent_at=?, docs_purged_at=NULL WHERE id=?",
                    (id_type, dates["id_expiry"], dates["license_expiry"], time.time(), rid))


def files_of(rid):
    """{slot: Path} des documents présents."""
    d = folder(rid)
    out = {}
    if d.exists():
        for p in d.iterdir():
            slot = p.stem
            if slot in SLOTS and p.is_file():
                out[slot] = p
    return out


def check(rid, ok, note="", by=None):
    with db.connect() as con:
        con.execute("UPDATE reservations SET docs_status=?, docs_note=?, docs_checked_by=? WHERE id=?",
                    ("verified" if ok else "rejected", (note or "").strip()[:200] or None, by, rid))


def purge(rid):
    shutil.rmtree(folder(rid), ignore_errors=True)
    with db.connect() as con:
        con.execute("UPDATE reservations SET docs_purged_at=? WHERE id=? AND docs_purged_at IS NULL", (time.time(), rid))


def purge_for_out(out_check_id):
    """Clôture de la location : on supprime les documents de la réservation qui l'a précédée."""
    with db.connect() as con:
        ids = [r[0] for r in con.execute("SELECT id FROM reservations WHERE out_check_id=?", (out_check_id,))]
    for rid in ids:
        purge(rid)
    return ids


def purge_expired(now=None):
    """Tous les jours (cleanup) : réservations refusées/annulées, et fin prévue dépassée de DOCS_RETENTION_DAYS."""
    now = time.time() if now is None else now
    with db.connect() as con:
        ids = [r[0] for r in con.execute(
            "SELECT id FROM reservations WHERE docs_purged_at IS NULL AND docs_status!='none'"
            " AND (status IN ('refused','cancelled') OR end_ts < ?)", (now - DOCS_RETENTION_DAYS * 86400,))]
    for rid in ids:
        purge(rid)
    return ids
