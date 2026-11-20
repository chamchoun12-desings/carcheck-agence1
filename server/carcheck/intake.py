"""Part 02 · The exit video: save the walk-around with server time + SHA-256.
Also: client signature, driving licence (photo + expiry date), plate read from the video,
and videos filmed offline (phone time + phone hash, checked on arrival)."""
import base64
import datetime
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import db, planning
from .config import MAX_SECONDS, MIN_SECONDS, VAULT


class Refused(Exception):
    pass


def video_duration(path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def normalize_plate(car: str) -> str:
    car = (car or "").upper().replace("تونس", "TU")
    return "".join(ch for ch in car if ch.isalnum() and ch.isascii() or ch in "-_")


def parse_expiry(v):
    """'2027-03-31' -> date, '' -> None. Refuse les formats inconnus."""
    if not v:
        return None
    try:
        return datetime.date.fromisoformat(v.strip()[:10])
    except ValueError:
        raise Refused("date d'expiration du permis invalide (format AAAA-MM-JJ)")


def decode_signature(data_url_or_bytes):
    """Signature : PNG brut ou 'data:image/png;base64,...' (pavé de signature de la page web)."""
    if not data_url_or_bytes:
        return None
    raw = data_url_or_bytes
    if isinstance(raw, str):
        if "," not in raw:
            return None
        try:
            raw = base64.b64decode(raw.split(",", 1)[1], validate=True)
        except ValueError:
            raise Refused("signature illisible")
    if not raw.startswith(b"\x89PNG") or len(raw) > 2_000_000:
        raise Refused("signature illisible")
    return raw


def read_plate_from_video(video_bytes):
    """Plaque lue par l'IA dans les premières secondes (le tour commence par l'avant)."""
    from . import ai
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "v.mp4").write_bytes(video_bytes)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(tmp / "v.mp4"), "-t", "15",
                        "-vf", "fps=1,scale=1280:-2", "-q:v", "3", str(tmp / "p_%02d.jpg")], check=True)
        frames = sorted(tmp.glob("p_*.jpg"))[:10]
        return ai.read_plate([f.read_bytes() for f in frames]) if frames else None
    except subprocess.CalledProcessError:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def save(car, kind, video_bytes, gps=None, client_phone=None, dash_bytes=None,
         signature=None, license_bytes=None, license_expiry=None, recorded_at=None, phone_sha256=None,
         plate_source="typed", client_name=None, client_lang="fr", by=None, agency_id=None):
    if kind not in ("out", "in"):
        raise Refused("kind must be 'out' or 'in'")
    car = normalize_plate(car)
    if not car:
        raise Refused("plaque manquante : tapez-la (ou laissez l'IA la lire dans la vidéo)")

    h = hashlib.sha256(video_bytes).hexdigest()
    if phone_sha256 and phone_sha256.lower() != h:
        raise Refused("la vidéo reçue ne correspond pas à celle filmée (empreinte différente) : renvoyez-la")
    sig = decode_signature(signature)
    expiry = parse_expiry(license_expiry)
    if kind == "out" and expiry and expiry < datetime.date.today():
        raise Refused(f"permis expiré le {expiry:%d/%m/%Y} : location impossible")
    if license_bytes and len(license_bytes) > 20_000_000:
        raise Refused("photo du permis trop lourde (max 20 Mo)")
    rec = None
    if recorded_at:
        try:
            rec = float(recorded_at)
        except ValueError:
            rec = None
        if rec and not (time.time() - 30 * 86400 < rec < time.time() + 600):
            rec = None                                   # heure du téléphone absurde : ignorée

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")          # the SERVER's clock, not the phone's
    check_id = f"{kind}-{h[:12]}"
    if db.get_check(check_id):
        raise Refused("cette vidéo a déjà été envoyée")

    d = VAULT / car / check_id
    d.mkdir(parents=True, exist_ok=True)
    video = d / "walk.mp4"
    video.write_bytes(video_bytes)

    def refuse(msg):
        shutil.rmtree(d, ignore_errors=True)
        raise Refused(msg)

    try:
        dur = video_duration(video)
    except Exception:
        refuse("le fichier n'est pas une vidéo lisible")
    if dur < MIN_SECONDS:
        refuse(f"vidéo trop courte ({dur:.0f} s). Minimum {MIN_SECONDS:.0f} s : faites le tour lentement.")
    if dur > MAX_SECONDS:
        refuse(f"vidéo trop longue ({dur:.0f} s). Maximum {MAX_SECONDS:.0f} s.")

    out_check_id = None
    if kind == "out":
        from . import maintenance
        block = maintenance.blocking(car)
        if block:
            refuse(f"{car} ne peut pas sortir : {block}. Mettez la date à jour dans sa fiche (Voitures).")
        still_out = db.latest_open_out(car)
        if still_out:
            refuse(f"{car} est déjà sortie (contrôle du {still_out['server_time']}) : filmez d'abord son retour")
    if kind == "in":
        out = db.latest_open_out(car)
        if not out:
            refuse(f"aucune sortie ouverte pour {car} : filmez d'abord la sortie")
        if not out.get("planned_return"):
            refuse(f"durée de location non saisie pour la sortie de {car} : "
                   "ouvrez le contrôle de sortie et enregistrez-la d'abord")
        out_check_id = out["id"]
        client_phone = client_phone or out["client_phone"]
        client_name = client_name or out["client_name"]
        client_lang = out["client_lang"] or client_lang

    planning.ensure_car(car, agency_id)
    if sig:
        (d / "signature.png").write_bytes(sig)
    if license_bytes and kind == "out":
        (d / "license.jpg").write_bytes(license_bytes)       # donnée personnelle : voir purge_license()
    meta = {"car": car, "kind": kind, "sha256": h, "server_time": stamp, "gps": gps,
            "duration": round(dur, 1), "recorded_at_phone": rec, "phone_sha256": phone_sha256,
            "signature_sha256": hashlib.sha256(sig).hexdigest() if sig else None}
    (d / "meta.json").write_text(json.dumps(meta, indent=2))

    with db.connect() as con:
        con.execute(
            "INSERT INTO checks(id, car, kind, sha256, server_time, gps, dir, duration,"
            " client_phone, out_check_id, share_token, created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (check_id, car, kind, h, stamp, json.dumps(gps) if gps else None, str(d), dur,
             client_phone, out_check_id, secrets.token_urlsafe(16), time.time()))
    db.update_check(check_id, client_name=(client_name or "").strip()[:80] or None,
                    client_lang=client_lang if client_lang in ("fr", "ar") else "fr",
                    filmed_by=by, agency_id=agency_id)
    db.update_check(check_id, recorded_at=rec, phone_sha256=(phone_sha256 or None),
                    has_signature=int(bool(sig)), plate_source=plate_source,
                    license_expiry=expiry.isoformat() if expiry and kind == "out" else None)
    if dash_bytes:
        save_dashboard(check_id, dash_bytes)
    return db.get_check(check_id)


def verify(check_id) -> bool:
    """Recompute the hash: if even one byte changed since upload, this returns False."""
    c = db.get_check(check_id)
    data = (VAULT / c["car"] / check_id / "walk.mp4").read_bytes()
    return hashlib.sha256(data).hexdigest() == c["sha256"]


def save_dashboard(check_id, image_bytes):
    """Photo du compteur : enregistrée avec son empreinte, valeurs remises à zéro (à relire)."""
    if not image_bytes or len(image_bytes) > 20_000_000:
        raise Refused("photo du compteur vide ou trop lourde (max 20 Mo)")
    c = db.get_check(check_id)
    (VAULT / c["car"] / check_id / "dashboard.jpg").write_bytes(image_bytes)
    db.update_check(check_id, dash_sha256=hashlib.sha256(image_bytes).hexdigest(),
                    km=None, fuel=None, dash_status=None, dash_confidence=None)


def dashboard_path(check):
    p = VAULT / check["car"] / check["id"] / "dashboard.jpg"
    return p if p.exists() else None


def file_path(check, name):
    p = VAULT / check["car"] / check["id"] / name
    return p if p.exists() else None


def purge_license(out_check_id):
    """INPDP : la photo du permis ne sert qu'à la location. Supprimée à la clôture ; la date reste."""
    c = db.get_check(out_check_id)
    if c:
        p = VAULT / c["car"] / c["id"] / "license.jpg"
        p.unlink(missing_ok=True)


def license_status(out_check, until_ts=None):
    """('ok'|'soon'|'expired'|'none', texte) — 'soon' : expire avant le retour prévu."""
    if not out_check or not out_check.get("license_expiry"):
        return "none", "date d'expiration du permis non saisie"
    exp = datetime.date.fromisoformat(out_check["license_expiry"])
    txt = f"permis valable jusqu'au {exp:%d/%m/%Y}"
    if exp < datetime.date.today():
        return "expired", f"permis EXPIRÉ depuis le {exp:%d/%m/%Y}"
    until = until_ts or out_check.get("planned_return_ts")
    if until and exp < datetime.date.fromtimestamp(until):
        return "soon", f"{txt} : il expire AVANT le retour prévu"
    return "ok", txt + " ✓"
