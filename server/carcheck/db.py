"""SQLite storage: one row per walk-around (checks), one row per damage mark (marks)."""
import sqlite3
import time
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks(
  id TEXT PRIMARY KEY,            -- e.g. out-3f2a9c1b7d4e
  car TEXT NOT NULL,              -- plate number
  kind TEXT NOT NULL,             -- out / in
  sha256 TEXT NOT NULL,
  server_time TEXT NOT NULL,
  gps TEXT,
  dir TEXT NOT NULL,
  duration REAL,
  n_frames INTEGER DEFAULT 0,
  status TEXT DEFAULT 'uploaded', -- uploaded / analyzing / review / done / reported / error
  bad_photos TEXT DEFAULT '[]',
  error TEXT,
  client_phone TEXT,
  out_check_id TEXT,              -- for an 'in' check: the matching 'out'
  share_token TEXT,               -- secret link for client/owner report
  created REAL
);
CREATE TABLE IF NOT EXISTS marks(
  id INTEGER PRIMARY KEY,
  car TEXT, check_id TEXT,
  kind_of_check TEXT,             -- out / in
  zone TEXT, kind TEXT, size TEXT,
  photo TEXT, photos TEXT,        -- best photo + all photos where it appears
  confidence REAL,
  status TEXT DEFAULT 'ai',       -- ai / confirmed / rejected
  source TEXT DEFAULT 'ai',       -- ai / staff
  is_new INTEGER DEFAULT 0,       -- for 'in' checks: 1 = not present at 'out'
  decided_at REAL,
  created REAL
);
CREATE TABLE IF NOT EXISTS replies(
  id INTEGER PRIMARY KEY, phone TEXT, text TEXT, raw TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS cars(
  plate TEXT PRIMARY KEY,          -- immatriculation normalisée (123TU4567)
  name TEXT,                       -- ex. Peugeot 208
  category TEXT,                   -- citadine, berline, SUV...
  price_day REAL,                  -- prix par jour affiché aux clients
  gearbox TEXT,                    -- manuelle / automatique
  seats INTEGER,
  active INTEGER DEFAULT 1,        -- 0 = hors flotte (vendue, en panne longue)
  public INTEGER DEFAULT 1,        -- 1 = visible sur la page client « Réserver »
  created REAL
);
CREATE TABLE IF NOT EXISTS reservations(
  id INTEGER PRIMARY KEY,
  car TEXT NOT NULL,
  client_name TEXT, client_phone TEXT,
  start_ts REAL NOT NULL, end_ts REAL NOT NULL,
  status TEXT DEFAULT 'pending',   -- pending / confirmed / refused / cancelled / converted (devenue une sortie)
  source TEXT DEFAULT 'client',    -- client (page Réserver) / staff (téléphone, agence)
  note TEXT, token TEXT, created REAL, decided_at REAL
);
CREATE TABLE IF NOT EXISTS agencies(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, address TEXT, phone TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS users(
  username TEXT PRIMARY KEY, name TEXT, pass_hash TEXT NOT NULL,
  role TEXT DEFAULT 'staff',       -- owner (tout voir, gérer l'équipe) / staff
  agency_id INTEGER,               -- agence de l'employé (vide = toutes)
  active INTEGER DEFAULT 1, created REAL
);
CREATE TABLE IF NOT EXISTS extensions(
  id INTEGER PRIMARY KEY, out_check_id TEXT NOT NULL, days INTEGER NOT NULL,
  phone TEXT, text TEXT, source TEXT DEFAULT 'whatsapp',
  status TEXT DEFAULT 'pending',   -- pending / approved / refused
  reason TEXT, created REAL, decided_by TEXT, decided_at REAL
);
CREATE TABLE IF NOT EXISTS repairs(
  id INTEGER PRIMARY KEY, car TEXT NOT NULL, day TEXT NOT NULL,
  kind TEXT DEFAULT 'réparation',  -- réparation / entretien / autre
  description TEXT, cost REAL DEFAULT 0, mark_id INTEGER,
  created_by TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS invoices(
  id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL, in_check_id TEXT UNIQUE NOT NULL,
  total REAL, created REAL, created_by TEXT
);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events(               -- journal : qui a fait quoi, quand
  id INTEGER PRIMARY KEY, ts REAL NOT NULL, who TEXT, kind TEXT NOT NULL, car TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS ix_res_car ON reservations(car, start_ts);
CREATE INDEX IF NOT EXISTS ix_marks_check ON marks(check_id);
CREATE INDEX IF NOT EXISTS ix_checks_car ON checks(car, kind);
"""


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


RENTAL_COLUMNS = [("rental_days", "INTEGER"), ("planned_return", "TEXT"),
                  ("planned_return_ts", "REAL"), ("reminder_sent", "INTEGER DEFAULT 0"),
                  ("km_per_day", "REAL"),
                  # compteur : km et carburant (0 à 1), lus par l'IA puis confirmés par l'employé
                  ("km", "INTEGER"), ("fuel", "REAL"), ("dash_status", "TEXT"),
                  ("dash_confidence", "REAL"), ("dash_sha256", "TEXT"),
                  # tournage hors ligne, signature, permis, plaque
                  ("recorded_at", "REAL"), ("phone_sha256", "TEXT"), ("has_signature", "INTEGER DEFAULT 0"),
                  ("license_expiry", "TEXT"), ("plate_source", "TEXT"),
                  # client, langue, traçabilité, agence
                  ("client_name", "TEXT"), ("client_lang", "TEXT DEFAULT 'fr'"), ("filmed_by", "TEXT"),
                  ("agency_id", "INTEGER"), ("dash_by", "TEXT"), ("rental_by", "TEXT"),
                  # argent : prix de la location, caution
                  ("rental_price", "REAL"), ("late_alert_sent", "INTEGER DEFAULT 0"),
                  ("deposit_amount", "REAL"), ("deposit_method", "TEXT"), ("deposit_by", "TEXT"),
                  ("deposit_status", "TEXT"), ("deposit_retained", "REAL"), ("deposit_detail", "TEXT"),
                  ("deposit_settled_by", "TEXT"), ("deposit_settled_at", "REAL")]
EXTRA_COLUMNS = {
    "marks": [("decided_by", "TEXT")],
    "reservations": [("client_lang", "TEXT DEFAULT 'fr'"), ("created_by", "TEXT"), ("decided_by", "TEXT"),
                     # documents envoyés par le client : photos seulement (pas de numéro), supprimées à la fin
                     ("id_doc_type", "TEXT"), ("id_expiry", "TEXT"), ("license_expiry", "TEXT"),
                     ("docs_status", "TEXT DEFAULT 'none'"), ("docs_note", "TEXT"), ("docs_checked_by", "TEXT"),
                     ("docs_consent_at", "REAL"), ("docs_purged_at", "REAL"), ("out_check_id", "TEXT"),
                     ("price_day", "REAL")],          # prix par jour fixé par l'agence en acceptant la demande
    "cars": [("agency_id", "INTEGER"), ("oil_every_km", "INTEGER"), ("last_oil_km", "INTEGER"),
             ("insurance_until", "TEXT"), ("inspection_until", "TEXT"), ("vignette_until", "TEXT"),
             ("dash_type", "INTEGER DEFAULT 0"),     # 0 aiguilles, 1 numérique, 2 écran
             ("km_start", "INTEGER")],               # km saisis à l'ajout de la voiture
    "users": [("phone", "TEXT"), ("jobs", "TEXT")],   # tâches : out,in,book,maint,cash
}


def init():
    with connect() as con:
        con.executescript(SCHEMA)
        for table, columns in [("checks", RENTAL_COLUMNS), *EXTRA_COLUMNS.items()]:
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            for name, typ in columns:             # upgrade older databases in place
                if name not in cols:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


def set_rental(check_id, days, return_ts, km_per_day=None, by=None, price=None):
    """Durée de location d'une sortie. Changer la date (prolongation) ré-arme le rappel et l'alerte de retard."""
    label = time.strftime("%Y-%m-%d %H:%M", time.localtime(return_ts))
    with connect() as con:
        con.execute("UPDATE checks SET rental_days=?, planned_return=?, planned_return_ts=?, reminder_sent=0,"
                    " late_alert_sent=0, km_per_day=?, rental_by=COALESCE(?, rental_by),"
                    " rental_price=COALESCE(?, rental_price) WHERE id=?",
                    (days, label, return_ts, km_per_day, by, price, check_id))


def set_dashboard(check_id, km, fuel, status="confirmed", confidence=None, by=None):
    """km entier, fuel entre 0 et 1 (huitièmes). status : ai (proposé) ou confirmed."""
    with connect() as con:
        con.execute("UPDATE checks SET km=?, fuel=?, dash_status=?, dash_confidence=?, dash_by=? WHERE id=?",
                    (km, fuel, status, confidence, by if status == "confirmed" else None, check_id))


def log_event(who, kind, car=None, detail="", ts=None):
    """Journal de l'équipe. kind : out, in, book, more, oil, add, edit, remove, staff, close."""
    with connect() as con:
        con.execute("INSERT INTO events(ts, who, kind, car, detail) VALUES(?,?,?,?,?)",
                    (time.time() if ts is None else ts, who, kind, car, (detail or "")[:200]))


def events(who=None, car=None, limit=200):
    q, a = "SELECT * FROM events WHERE 1=1", []
    if who:
        q += " AND who=?"
        a.append(who)
    if car:
        q += " AND car=?"
        a.append(car)
    with connect() as con:
        return [dict(r) for r in con.execute(q + " ORDER BY ts DESC, id DESC LIMIT ?", (*a, limit))]


def kv_get(key, default=None):
    with connect() as con:
        r = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r[0] if r else default


def kv_set(key, value):
    with connect() as con:
        con.execute("INSERT INTO kv(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value))


def has_return(out_check_id):
    with connect() as con:
        return con.execute("SELECT 1 FROM checks WHERE out_check_id=?", (out_check_id,)).fetchone() is not None


def get_check(check_id):
    with connect() as con:
        r = con.execute("SELECT * FROM checks WHERE id=?", (check_id,)).fetchone()
        return dict(r) if r else None


def update_check(check_id, **fields):
    keys = ", ".join(f"{k}=?" for k in fields)
    with connect() as con:
        con.execute(f"UPDATE checks SET {keys} WHERE id=?", (*fields.values(), check_id))


def marks_for(check_id, include_rejected=True):
    q = "SELECT * FROM marks WHERE check_id=?"
    if not include_rejected:
        q += " AND status!='rejected'"
    with connect() as con:
        return [dict(r) for r in con.execute(q + " ORDER BY zone, kind", (check_id,))]


def add_mark(check, m, source="ai", status="ai", by=None):
    with connect() as con:
        con.execute(
            "INSERT INTO marks(car, check_id, kind_of_check, zone, kind, size, photo, photos,"
            " confidence, status, source, created, decided_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (check["car"], check["id"], check["kind"], m["zone"], m["kind"], m["size"],
             m.get("photo"), ",".join(m.get("photos", [])), m.get("confidence", 1.0),
             status, source, time.time(), by),
        )


def set_mark_status(mark_id, status, by=None):
    with connect() as con:
        con.execute("UPDATE marks SET status=?, decided_at=?, decided_by=? WHERE id=?",
                    (status, time.time(), by, mark_id))


def latest_open_out(car):
    """The most recent 'out' check for this car that has no 'in' yet."""
    with connect() as con:
        r = con.execute(
            "SELECT * FROM checks c WHERE car=? AND kind='out' AND status!='error'"
            " AND NOT EXISTS (SELECT 1 FROM checks i WHERE i.out_check_id=c.id)"
            " ORDER BY created DESC LIMIT 1", (car,)).fetchone()
        return dict(r) if r else None


def list_checks(limit=50, agency_id=None):
    q, a = "SELECT * FROM checks", []
    if agency_id:
        q += " WHERE agency_id=? OR car IN (SELECT plate FROM cars WHERE agency_id=?)"
        a = [agency_id, agency_id]
    with connect() as con:
        return [dict(r) for r in con.execute(q + " ORDER BY created DESC LIMIT ?", (*a, limit))]
