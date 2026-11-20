"""Planning de la flotte : voitures, réservations, disponibilités. Empêche les doubles locations.

Une voiture est occupée sur une période si elle chevauche :
  - une location en cours (sortie filmée sans retour) : de la sortie au retour prévu (+ préparation),
    et tant qu'elle n'est pas rentrée si le retour est dépassé ou pas encore saisi ;
  - une réservation confirmée ou en attente.
"""
import re
import secrets
import time

from . import db
from .config import BOOKING_AUTO_CONFIRM, BOOKING_BUFFER_HOURS, BOOKING_MAX_DAYS

FAR = 4102444800.0          # 2100-01-01 : « tant que la voiture n'est pas rentrée »
ACTIVE = ("pending", "confirmed")


class Conflict(Exception):
    pass


def phone_digits(p):
    return re.sub(r"\D", "", p or "")


def label(ts):
    return time.strftime("%d/%m %H:%M", time.localtime(ts))


# ---------- flotte ----------
def ensure_car(plate, agency_id=None):
    with db.connect() as con:
        con.execute("INSERT OR IGNORE INTO cars(plate, name, active, public, created, agency_id) VALUES(?,?,1,0,?,?)",
                    (plate, plate, time.time(), agency_id))


def upsert_car(plate, name, category="", price_day=None, gearbox="", seats=None, active=1, public=1, agency_id=None):
    """Ajout/modification par l'ancienne page Voitures (les champs entretien sont dans maintenance)."""
    with db.connect() as con:
        con.execute(
            "INSERT INTO cars(plate, name, category, price_day, gearbox, seats, active, public, created, agency_id)"
            " VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(plate) DO UPDATE SET name=excluded.name,"
            " category=excluded.category, price_day=excluded.price_day, gearbox=excluded.gearbox,"
            " seats=excluded.seats, active=excluded.active, public=excluded.public,"
            " agency_id=COALESCE(excluded.agency_id, cars.agency_id)",
            (plate, name or plate, category, price_day, gearbox, seats, int(active), int(public), time.time(), agency_id))


def cars(active_only=True, public_only=False, agency_id=None):
    q, a = "SELECT * FROM cars WHERE 1=1", []
    if active_only:
        q += " AND active=1"
    if public_only:
        q += " AND public=1"            # le prix n'est plus montré : l'agence le donne en acceptant
    if agency_id:                     # voitures sans agence : communes à toutes les agences
        q += " AND (agency_id=? OR agency_id IS NULL)"
        a.append(agency_id)
    with db.connect() as con:
        return [dict(r) for r in con.execute(q + " ORDER BY name, plate", a)]


def get_car(plate):
    with db.connect() as con:
        r = con.execute("SELECT * FROM cars WHERE plate=?", (plate,)).fetchone()
        return dict(r) if r else None


# ---------- occupation ----------
def busy(car, now=None):
    """Toutes les périodes occupées de la voiture : [{kind, start, end, who, ref, late}]."""
    now = time.time() if now is None else now
    buf = BOOKING_BUFFER_HOURS * 3600
    out = []
    with db.connect() as con:
        rentals = con.execute(
            "SELECT * FROM checks c WHERE car=? AND kind='out' AND status NOT IN ('error','purged')"
            " AND NOT EXISTS (SELECT 1 FROM checks i WHERE i.out_check_id=c.id)", (car,)).fetchall()
        res = con.execute(
            f"SELECT * FROM reservations WHERE car=? AND status IN ({','.join('?' * len(ACTIVE))})",
            (car, *ACTIVE)).fetchall()
    for r in rentals:
        planned = r["planned_return_ts"]
        late = bool(planned and now > planned)
        end = FAR if not planned or late else planned + buf
        out.append({"kind": "rented", "start": r["created"], "end": end, "until": FAR if late or not planned else planned,
                    "who": r["client_phone"] or "",
                    "ref": r["id"], "late": late, "planned": planned})
    for r in res:
        out.append({"kind": "reserved" if r["status"] == "confirmed" else "pending",
                    "start": r["start_ts"], "end": r["end_ts"] + buf, "until": r["end_ts"], "who": r["client_name"] or "",
                    "phone": r["client_phone"] or "", "ref": r["id"], "late": False})
    return sorted(out, key=lambda b: b["start"])


def conflicts(car, start, end, exclude_res=None, ignore_phone=None, now=None):
    """Périodes qui chevauchent [start, end). ignore_phone : les réservations de ce client ne gênent pas."""
    ign = phone_digits(ignore_phone)
    found = []
    for b in busy(car, now):
        if b["kind"] != "rented" and (b["ref"] == exclude_res or (ign and phone_digits(b.get("phone")) == ign)):
            continue
        if b["start"] < end and start < b["end"]:
            found.append(b)
    return found


def describe(b):
    what = {"rented": "louée", "reserved": "réservée", "pending": "demande en attente"}[b["kind"]]
    end = "retour non fait" if b["until"] >= FAR else label(b["until"])
    return f"{what} du {label(b['start'])} au {end}" + (f" ({b['who']})" if b["who"] else "")


def available(start, end, public_only=False, now=None, agency_id=None):
    return [c for c in cars(public_only=public_only, agency_id=agency_id) if not conflicts(c["plate"], start, end, now=now)]


# ---------- réservations ----------
def create_reservation(car, name, phone, start, end, source="client", note="", now=None, by=None, lang="fr"):
    now = time.time() if now is None else now
    c = get_car(car)
    if not c or not c["active"]:
        raise Conflict("voiture inconnue")
    if source == "client" and not c["public"]:
        raise Conflict("voiture non disponible à la réservation en ligne")
    if not (name or "").strip() or not 8 <= len(phone_digits(phone)) <= 15:
        raise Conflict("nom et numéro WhatsApp obligatoires")
    if end <= start:
        raise Conflict("la date de retour doit être après la date de départ")
    if start < now - 3600:
        raise Conflict("la date de départ est déjà passée")
    if end - start > BOOKING_MAX_DAYS * 86400:
        raise Conflict(f"durée maximum : {BOOKING_MAX_DAYS} jours")
    if source == "client":
        with db.connect() as con:
            n = con.execute("SELECT COUNT(*) FROM reservations WHERE client_phone=? AND status='pending'",
                            (phone_digits(phone),)).fetchone()[0]
        if n >= 2:
            raise Conflict("vous avez déjà 2 demandes en attente : l'agence vous répond rapidement")
    clash = conflicts(car, start, end, now=now)
    if clash:
        raise Conflict("voiture déjà prise : " + describe(clash[0]))
    status = "confirmed" if (source == "staff" or BOOKING_AUTO_CONFIRM) else "pending"
    token = secrets.token_urlsafe(12)
    with db.connect() as con:
        cur = con.execute(
            "INSERT INTO reservations(car, client_name, client_phone, start_ts, end_ts, status, source,"
            " note, token, created, created_by, client_lang) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (car, name.strip()[:80], phone_digits(phone), start, end, status, source, note[:300], token, now, by,
             lang if lang in ("fr", "ar") else "fr"))
        rid = cur.lastrowid
    return get_reservation(rid)


def get_reservation(rid=None, token=None):
    with db.connect() as con:
        if token is not None:
            r = con.execute("SELECT * FROM reservations WHERE token=?", (token,)).fetchone()
        else:
            r = con.execute("SELECT * FROM reservations WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None


def set_status(rid, status, by=None):
    r = get_reservation(rid)
    if not r:
        raise Conflict("réservation introuvable")
    if status == "confirmed":
        clash = [b for b in conflicts(r["car"], r["start_ts"], r["end_ts"], exclude_res=rid)
                 if b["kind"] != "pending"]
        if clash:
            raise Conflict("impossible de confirmer : " + describe(clash[0]))
    with db.connect() as con:
        con.execute("UPDATE reservations SET status=?, decided_at=?, decided_by=? WHERE id=?",
                    (status, time.time(), by, rid))
        if status == "confirmed" and r["docs_status"] == "received":
            con.execute("UPDATE reservations SET docs_status='verified', docs_checked_by=? WHERE id=?", (by, rid))
    if status in ("refused", "cancelled"):
        from . import bookdocs
        bookdocs.purge(rid)                     # INPDP : plus de raison de garder les documents
    return get_reservation(rid)


def reservations(status=None, since=None, agency_id=None):
    q, args = "SELECT r.*, c.name AS car_name FROM reservations r LEFT JOIN cars c ON c.plate=r.car WHERE 1=1", []
    if agency_id:
        q += " AND (c.agency_id=? OR c.agency_id IS NULL)"
        args.append(agency_id)
    if status:
        q += " AND r.status=?"
        args.append(status)
    if since is not None:
        q += " AND r.end_ts>=?"
        args.append(since)
    with db.connect() as con:
        return [dict(x) for x in con.execute(q + " ORDER BY r.start_ts", args)]


def convert_for_rental(out_check, return_ts):
    """À l'enregistrement de la durée d'une sortie : vérifie qu'aucun AUTRE client n'a la voiture
    sur cette période ; la réservation de CE client devient « converted »."""
    clash = conflicts(out_check["car"], out_check["created"], return_ts,
                      ignore_phone=out_check["client_phone"])
    clash = [b for b in clash if not (b["kind"] == "rented" and b["ref"] == out_check["id"])]
    if clash:
        raise Conflict("double location : " + describe(clash[0]))
    ph = phone_digits(out_check["client_phone"])
    if ph:
        with db.connect() as con:
            con.execute("UPDATE reservations SET status='converted', decided_at=?, out_check_id=? WHERE car=?"
                        " AND client_phone=? AND status IN ('pending','confirmed') AND start_ts<? AND end_ts>?",
                        (time.time(), out_check["id"], out_check["car"], ph, return_ts, out_check["created"]))
            r = con.execute("SELECT license_expiry FROM reservations WHERE out_check_id=? AND license_expiry IS NOT NULL",
                            (out_check["id"],)).fetchone()
            if r and not out_check.get("license_expiry"):       # date du permis envoyée en réservant
                con.execute("UPDATE checks SET license_expiry=? WHERE id=?", (r[0], out_check["id"]))


# ---------- vue planning ----------
PRIORITY = {"rented": 3, "reserved": 2, "pending": 1}


def grid(day0_ts, days=14, now=None, agency_id=None):
    """Une ligne par voiture, une case par jour : free / rented / reserved / pending (+ late)."""
    rows = []
    for c in cars(agency_id=agency_id):
        periods = busy(c["plate"], now)
        cells = []
        for d in range(days):
            a = day0_ts + d * 86400
            b = a + 86400
            hit = [p for p in periods if p["start"] < b and a < p["end"]]
            if not hit:
                cells.append({"state": "free"})
                continue
            top = max(hit, key=lambda p: PRIORITY[p["kind"]])
            cells.append({"state": top["kind"], "late": top["late"], "title": describe(top)})
        rows.append({"car": c, "cells": cells})
    return rows


def today(now=None, agency_id=None):
    now = time.time() if now is None else now
    lt = time.localtime(now)
    start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    end = start + 86400
    out = {"free_now": [], "rented": [], "late": [], "returns_today": [], "departures_today": []}
    for c in cars(agency_id=agency_id):
        periods = busy(c["plate"], now)
        cur = [p for p in periods if p["kind"] == "rented"]
        if any(p["late"] for p in cur):
            out["late"].append(c)
        if cur:
            out["rented"].append(c)
        elif not conflicts(c["plate"], now, now + 3600, now=now):
            out["free_now"].append(c)
        for p in cur:
            if p["planned"] and start <= p["planned"] < end:
                out["returns_today"].append((c, p))
        for p in periods:
            if p["kind"] in ("reserved", "pending") and start <= p["start"] < end:
                out["departures_today"].append((c, p))
    return out
