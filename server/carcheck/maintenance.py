"""Entretien de la flotte : vidange (par km), assurance, visite technique, vignette.
Assurance, visite technique ou vignette expirée : la voiture ne peut pas sortir."""
import datetime
import json
import time

from . import db, planning, report
from .config import DOC_WARN_DAYS, MAINTENANCE_DIGEST_HOUR, OIL_EVERY_KM, OIL_WARN_KM, OWNER_PHONE, WA_TPL_MAINTENANCE

DOCS = [("insurance_until", "Assurance"), ("inspection_until", "Visite technique"), ("vignette_until", "Vignette")]


def current_km(plate):
    """Dernier kilométrage confirmé au compteur (sortie ou retour), ou celui de la dernière vidange."""
    with db.connect() as con:
        r = con.execute("SELECT MAX(km) FROM checks WHERE car=? AND dash_status='confirmed' AND km IS NOT NULL",
                        (plate,)).fetchone()
        car = con.execute("SELECT last_oil_km, km_start FROM cars WHERE plate=?", (plate,)).fetchone()
    vals = [v for v in ((r[0] if r else None), *((car[0], car[1]) if car else ())) if v is not None]
    return max(vals) if vals else None


def alerts(car, today=None):
    """[{kind, level: 'due'|'soon', text}] pour une voiture."""
    today = today or datetime.date.today()
    out = []
    km = current_km(car["plate"])
    every = car.get("oil_every_km") or OIL_EVERY_KM
    if car.get("last_oil_km") is not None and km is not None:
        nxt = car["last_oil_km"] + every
        if km >= nxt:
            out.append({"kind": "oil", "level": "due", "text": f"Vidange dépassée de {km - nxt} km (prévue à {nxt} km)"})
        elif km >= nxt - OIL_WARN_KM:
            out.append({"kind": "oil", "level": "soon", "text": f"Vidange dans {nxt - km} km (à {nxt} km)"})
    elif km is not None and car.get("last_oil_km") is None:
        out.append({"kind": "oil", "level": "soon", "text": "Kilométrage de la dernière vidange non saisi"})
    for field, label in DOCS:
        v = car.get(field)
        if not v:
            out.append({"kind": field, "level": "soon", "text": f"{label} : date non saisie"})
            continue
        d = datetime.date.fromisoformat(v)
        if d < today:
            out.append({"kind": field, "level": "due", "text": f"{label} expirée depuis le {d:%d/%m/%Y}"})
        elif (d - today).days <= DOC_WARN_DAYS:
            out.append({"kind": field, "level": "soon", "text": f"{label} expire le {d:%d/%m/%Y} (dans {(d - today).days} j)"})
    return out


def blocking(plate):
    """Raison qui interdit la sortie (document expiré), ou None."""
    car = planning.get_car(plate)
    if not car:
        return None
    due = [a for a in alerts(car) if a["level"] == "due" and a["kind"] != "oil"]
    return due[0]["text"] if due else None


def fleet_alerts(agency_id=None):
    """[(car, [alertes])] seulement pour les voitures qui ont quelque chose à signaler."""
    res = []
    for c in planning.cars(agency_id=agency_id):
        a = alerts(c)
        if a:
            res.append((c, a))
    return res


def set_docs(plate, insurance="", inspection="", vignette="", oil_every=None):
    for v in (insurance, inspection, vignette):
        if v:
            datetime.date.fromisoformat(v)                       # refuse une date mal écrite
    with db.connect() as con:
        con.execute("UPDATE cars SET insurance_until=COALESCE(NULLIF(?,''), insurance_until),"
                    " inspection_until=COALESCE(NULLIF(?,''), inspection_until),"
                    " vignette_until=COALESCE(NULLIF(?,''), vignette_until),"
                    " oil_every_km=COALESCE(?, oil_every_km) WHERE plate=?",
                    (insurance, inspection, vignette, oil_every, plate))


def oil_done(plate, km, cost=0, by=None, day=None):
    with db.connect() as con:
        con.execute("UPDATE cars SET last_oil_km=? WHERE plate=?", (km, plate))
    add_repair(plate, f"Vidange à {km} km", cost, kind="entretien", by=by, day=day)


# ---------- réparations et coûts ----------
def add_repair(plate, description, cost, kind="réparation", mark_id=None, by=None, day=None):
    day = day or datetime.date.today().isoformat()
    datetime.date.fromisoformat(day)
    with db.connect() as con:
        con.execute("INSERT INTO repairs(car, day, kind, description, cost, mark_id, created_by, created)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (plate, day, kind, description.strip()[:200], float(cost or 0), mark_id, by, time.time()))


def repairs(plate=None, since=None, until=None):
    q, a = "SELECT * FROM repairs WHERE 1=1", []
    if plate:
        q += " AND car=?"
        a.append(plate)
    if since:
        q += " AND day>=?"
        a.append(since)
    if until:
        q += " AND day<?"
        a.append(until)
    with db.connect() as con:
        return [dict(r) for r in con.execute(q + " ORDER BY day DESC, id DESC", a)]


# ---------- résumé quotidien au propriétaire ----------
def send_daily_digest(now=None):
    """Une fois par jour (après MAINTENANCE_DIGEST_HOUR h) : modèle « entretien », {{1}} = liste des alertes."""
    now = time.time() if now is None else now
    lt = time.localtime(now)
    today = time.strftime("%Y-%m-%d", lt)
    if lt.tm_hour < MAINTENANCE_DIGEST_HOUR or db.kv_get("maintenance_digest") == today:
        return None
    items = []
    for car, al in fleet_alerts():
        important = [a["text"] for a in al if a["level"] == "due" or "expire le" in a["text"] or "Vidange dans" in a["text"]]
        if important:
            items.append(f"{car['name']} {car['plate']} : " + ", ".join(important))
    db.kv_set("maintenance_digest", today)
    if not items:
        return {"sent": False, "items": []}
    text = " ; ".join(items)[:900]              # un paramètre de modèle WhatsApp ne peut pas contenir de retour à la ligne
    res = report.send_template(OWNER_PHONE, [text], WA_TPL_MAINTENANCE, "fr") if OWNER_PHONE else {"skipped": "no phone"}
    return {"sent": True, "items": items, "result": json.dumps(res)[:200]}
