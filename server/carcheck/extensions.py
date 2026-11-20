"""Pendant la location : prolongation demandée par WhatsApp, validée d'un clic, et alertes de retard."""
import re
import time

from . import db, messages, planning, report
from .config import (AGENCY_NAME, LATE_GRACE_MIN, MAX_EXTENSION_DAYS, OWNER_PHONE, WA_TPL_LATE_CLIENT,
                     WA_TPL_LATE_OWNER)

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
KEYWORDS = re.compile(r"prolong|rallong|extend|تمديد|تمدي|مدد|نمدد|زيد|نزيد")
WORDS = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
         "huit": 8, "neuf": 9, "dix": 10, "semaine": 7, "يوم": 1, "نهار": 1, "يومين": 2, "نهارين": 2, "جمعة": 7, "أسبوع": 7}


def parse(text):
    """« prolonger 2 jours » -> 2 ; « تمديد يومين » -> 2 ; « prolonger » seul -> 0 (on explique) ; autre -> None."""
    t = (text or "").lower().translate(AR_DIGITS)
    if not KEYWORDS.search(t):
        return None
    m = re.search(r"(\d{1,3})", t)
    if m:
        d = int(m.group(1))
    else:
        d = next((WORDS[w] for w in re.findall(r"\w+", t) if w in WORDS), 0)
    return d if 0 <= d <= MAX_EXTENSION_DAYS else 0


def open_rental_for(phone):
    """Location en cours de ce client (comparaison sur les 8 derniers chiffres du numéro)."""
    tail = planning.phone_digits(phone)[-8:]
    if len(tail) < 8:
        return None
    with db.connect() as con:
        rows = con.execute("SELECT * FROM checks c WHERE kind='out' AND status NOT IN ('error','purged')"
                           " AND NOT EXISTS (SELECT 1 FROM checks i WHERE i.out_check_id=c.id)"
                           " ORDER BY created DESC").fetchall()
    for r in rows:
        if planning.phone_digits(r["client_phone"])[-8:] == tail:
            return dict(r)
    return None


def car_label(out):
    c = planning.get_car(out["car"])
    return f"{c['name']} {out['car']}" if c and c["name"] and c["name"] != out["car"] else out["car"]


def handle_incoming(phone, text):
    """Message reçu sur WhatsApp. Retourne ce qui a été fait (ou None si ce n'est pas une prolongation)."""
    days = parse(text)
    if days is None:
        return None
    out = open_rental_for(phone)
    if not out:
        return {"action": "no_rental"}
    lang = out["client_lang"]
    if days == 0:
        report.send_text(out["client_phone"], messages.t(lang, "ext_help"))
        return {"action": "help"}
    with db.connect() as con:
        pend = con.execute("SELECT id FROM extensions WHERE out_check_id=? AND status='pending'", (out["id"],)).fetchone()
        if pend:
            con.execute("UPDATE extensions SET days=?, text=?, created=? WHERE id=?", (days, text[:300], time.time(), pend[0]))
            eid = pend[0]
        else:
            eid = con.execute("INSERT INTO extensions(out_check_id, days, phone, text, created) VALUES(?,?,?,?,?)",
                              (out["id"], days, planning.phone_digits(phone), text[:300], time.time())).lastrowid
    report.send_text(out["client_phone"], messages.t(lang, "ext_received", name=out["client_name"] or "",
                                                     days=days, car=car_label(out)))
    return {"action": "pending", "id": eid, "days": days}


def pending(agency_id=None):
    with db.connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT e.*, c.car, c.client_name, c.client_phone, c.planned_return_ts, c.client_lang FROM extensions e"
            " JOIN checks c ON c.id=e.out_check_id WHERE e.status='pending' ORDER BY e.created")]
    if agency_id:
        plates = {c["plate"] for c in planning.cars(agency_id=agency_id)}
        rows = [r for r in rows if r["car"] in plates]
    return rows


def get(eid):
    with db.connect() as con:
        r = con.execute("SELECT * FROM extensions WHERE id=?", (eid,)).fetchone()
        return dict(r) if r else None


def decide(eid, approve, by=None):
    """Valider (vérifie qu'aucun autre client n'a la voiture ensuite) ou refuser. Le client reçoit la réponse."""
    e = get(eid)
    if not e or e["status"] != "pending":
        raise planning.Conflict("demande déjà traitée")
    out = db.get_check(e["out_check_id"])
    lang = out["client_lang"]
    car = car_label(out)
    status, reason = "refused", "reason_agency"
    if approve:
        new_ts = out["planned_return_ts"] + e["days"] * 86400
        try:
            planning.convert_for_rental(out, new_ts)
            c = planning.get_car(out["car"]) or {}
            price = out["rental_price"]
            if c.get("price_day"):
                price = (price if price is not None else (out["rental_days"] or 0) * c["price_day"]) + e["days"] * c["price_day"]
            db.set_rental(out["id"], (out["rental_days"] or 0) + e["days"], new_ts, out["km_per_day"], by, price)
            status, reason = "approved", None
        except planning.Conflict:
            reason = "reason_booked"
    with db.connect() as con:
        con.execute("UPDATE extensions SET status=?, reason=?, decided_by=?, decided_at=? WHERE id=?",
                    (status, reason, by, time.time(), eid))
    out = db.get_check(out["id"])
    if status == "approved":
        body = messages.t(lang, "ext_ok", car=car, date=messages.date(out["planned_return_ts"]))
    else:
        body = messages.t(lang, "ext_refused", car=car, reason=messages.t(lang, reason),
                          date=messages.date(out["planned_return_ts"]))
    report.send_text(out["client_phone"], body)
    return {"status": status, "reason": reason, "message": body}


# ---------- alertes de retard ----------
LATE_QUERY = """
SELECT * FROM checks c WHERE kind='out' AND planned_return_ts IS NOT NULL
  AND COALESCE(late_alert_sent, 0) = 0 AND status NOT IN ('error','purged')
  AND ? > planned_return_ts + ? * 60
  AND NOT EXISTS (SELECT 1 FROM checks i WHERE i.out_check_id = c.id)
"""


def late_due(now=None):
    now = time.time() if now is None else now
    with db.connect() as con:
        return [dict(r) for r in con.execute(LATE_QUERY, (now, LATE_GRACE_MIN))]


def send_late_alerts(now=None):
    """Une alerte par retard : l'agence ({{1}} voiture, {{2}} client, {{3}} retour prévu) et un message poli au
    client dans sa langue ({{1}} voiture, {{2}} retour prévu, {{3}} agence)."""
    sent = []
    for c in late_due(now):
        when = messages.date(c["planned_return_ts"])
        who = " ".join(x for x in (c["client_name"], c["client_phone"]) if x) or "client inconnu"
        res = {"owner": report.send_template(OWNER_PHONE, [car_label(c), who, when], WA_TPL_LATE_OWNER, "fr")
               if OWNER_PHONE else {"skipped": "no phone"},
               "client": report.send_template(c["client_phone"], [car_label(c), when, AGENCY_NAME], WA_TPL_LATE_CLIENT,
                                              c["client_lang"] or "fr") if c["client_phone"] else {"skipped": "no phone"}}
        db.update_check(c["id"], late_alert_sent=1)
        sent.append({"check": c["id"], "car": c["car"], "results": res})
    return sent


def late_now(agency_id=None, now=None):
    """Locations en retard en ce moment (pour le Planning)."""
    now = time.time() if now is None else now
    with db.connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM checks c WHERE kind='out' AND planned_return_ts IS NOT NULL AND ? > planned_return_ts"
            " AND status NOT IN ('error','purged') AND NOT EXISTS (SELECT 1 FROM checks i WHERE i.out_check_id=c.id)"
            " ORDER BY planned_return_ts", (now,))]
    if agency_id:
        plates = {c["plate"] for c in planning.cars(agency_id=agency_id)}
        rows = [r for r in rows if r["car"] in plates]
    return rows
