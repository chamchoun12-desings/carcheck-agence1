"""Comptes : un identifiant par employé, des agences, deux rôles.
owner = voit toutes les agences et gère l'équipe ; staff = son agence.
Le compte STAFF_USER / STAFF_PASSWORD du fichier .env reste le compte propriétaire de secours."""
import hashlib
import hmac
import secrets
import time

from . import db
from .config import STAFF_PASSWORD, STAFF_USER

ROLES = {"owner": "Propriétaire", "staff": "Employé"}
_cache = {}


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()
    return f"{salt}${h}"


def check_pw(pw, stored):
    key = hashlib.sha256(f"{pw}\0{stored}".encode()).hexdigest()      # évite de recalculer à chaque page
    if key not in _cache:
        try:
            salt, h = stored.split("$", 1)
        except ValueError:
            return False
        _cache[key] = hmac.compare_digest(hash_pw(pw, salt).split("$", 1)[1], h)
    return _cache[key]


def authenticate(username, password):
    with db.connect() as con:
        r = con.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
    if r and check_pw(password, r["pass_hash"]):
        u = dict(r)
        u.pop("pass_hash")
        return u
    if STAFF_PASSWORD and hmac.compare_digest(username, STAFF_USER) and hmac.compare_digest(password, STAFF_PASSWORD):
        return {"username": STAFF_USER, "name": "Propriétaire", "role": "owner", "agency_id": None, "active": 1}
    return None


def add_user(username, name, password, role="staff", agency_id=None):
    username = username.strip().lower()
    if not username.isascii() or not username.replace(".", "").replace("_", "").isalnum() or len(username) > 30:
        raise ValueError("identifiant : lettres, chiffres, point ou _ seulement")
    if len(password) < 8:
        raise ValueError("mot de passe : 8 caractères minimum")
    if role not in ROLES:
        raise ValueError("rôle inconnu")
    with db.connect() as con:
        con.execute("INSERT INTO users(username, name, pass_hash, role, agency_id, active, created) VALUES(?,?,?,?,?,1,?)"
                    " ON CONFLICT(username) DO UPDATE SET name=excluded.name, pass_hash=excluded.pass_hash,"
                    " role=excluded.role, agency_id=excluded.agency_id, active=1",
                    (username, name.strip()[:60] or username, hash_pw(password), role, agency_id, time.time()))


def set_active(username, active):
    with db.connect() as con:
        con.execute("UPDATE users SET active=? WHERE username=?", (int(active), username))


def list_users():
    with db.connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT u.username, u.name, u.role, u.agency_id, u.active, a.name AS agency FROM users u"
            " LEFT JOIN agencies a ON a.id=u.agency_id ORDER BY u.active DESC, u.name")]


def add_agency(name, address="", phone=""):
    with db.connect() as con:
        cur = con.execute("INSERT INTO agencies(name, address, phone, created) VALUES(?,?,?,?)",
                          (name.strip()[:60], address.strip()[:120], phone.strip()[:20], time.time()))
        return cur.lastrowid


def agencies():
    with db.connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM agencies ORDER BY name")]


def agency_name(agency_id):
    if not agency_id:
        return ""
    with db.connect() as con:
        r = con.execute("SELECT name FROM agencies WHERE id=?", (agency_id,)).fetchone()
        return r[0] if r else ""


def display(username):
    """« Ahmed » pour l'affichage (ou l'identifiant s'il n'a pas de nom)."""
    if not username:
        return "—"
    with db.connect() as con:
        r = con.execute("SELECT name FROM users WHERE username=?", (username,)).fetchone()
    return r[0] if r and r[0] else ("Propriétaire" if username == STAFF_USER else username)


def scope(user):
    """Agence à afficher : None pour le propriétaire (toutes), sinon celle de l'employé."""
    return None if user.get("role") == "owner" else user.get("agency_id")
