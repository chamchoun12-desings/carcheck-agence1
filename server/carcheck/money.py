"""Argent : prix de la location, caution (prise, retenue, restituée) et facture de fin de location."""
import datetime
import json
import time

from . import billing, db, planning
from .config import FISCAL_STAMP, INVOICE_PREFIX, VAT_RATE

METHODS = ["espèces", "carte", "chèque", "virement"]


class MoneyError(Exception):
    pass


def default_price(out):
    """Prix de la location : celui saisi, sinon jours × prix par jour de la voiture."""
    if out.get("rental_price") is not None:
        return round(out["rental_price"], 3)
    car = planning.get_car(out["car"]) or {}
    if car.get("price_day") and out.get("rental_days"):
        return round(car["price_day"] * out["rental_days"], 3)
    return 0.0


def take_deposit(out_check_id, amount, method, by=None):
    out = db.get_check(out_check_id)
    if not out or out["kind"] != "out":
        raise MoneyError("contrôle de sortie introuvable")
    if out["deposit_status"] in ("returned", "partly_retained", "retained"):
        raise MoneyError("caution déjà clôturée")
    if amount < 0 or amount > 100000:
        raise MoneyError("montant de caution invalide")
    if method not in METHODS:
        raise MoneyError("mode de paiement inconnu")
    db.update_check(out_check_id, deposit_amount=round(amount, 3), deposit_method=method, deposit_by=by,
                    deposit_status="held")


def suggestion(in_check):
    """Retenues proposées au retour : carburant et km (déjà calculés), dégâts et autre à saisir par l'employé."""
    s = billing.summary(in_check)
    return {"fuel": s.get("fuel_cost", 0.0) if s["ready"] else 0.0,
            "km": s.get("km_cost", 0.0) if s["ready"] else 0.0, "damages": 0.0, "other": 0.0}


def invoice_for(in_check_id):
    with db.connect() as con:
        r = con.execute("SELECT * FROM invoices WHERE in_check_id=?", (in_check_id,)).fetchone()
        return dict(r) if r else None


def settle(in_check_id, damages=0.0, other=0.0, note="", by=None, now=None):
    """Clôture : calcule la retenue sur la caution, la somme restituée, et crée la facture numérotée."""
    c = db.get_check(in_check_id)
    if not c or c["kind"] != "in":
        raise MoneyError("contrôle de retour introuvable")
    if invoice_for(in_check_id):
        raise MoneyError("location déjà clôturée")
    s = billing.summary(c)
    if not s["ready"]:
        raise MoneyError(s["why"])
    if damages < 0 or other < 0:
        raise MoneyError("montants négatifs")
    out = db.get_check(c["out_check_id"])
    sug = suggestion(c)
    extras = {"fuel": round(sug["fuel"], 3), "km": round(sug["km"], 3), "damages": round(damages, 3), "other": round(other, 3)}
    total_extras = round(sum(extras.values()), 3)
    deposit = out["deposit_amount"] or 0.0
    retained = round(min(deposit, total_extras), 3)
    returned = round(deposit - retained, 3)
    still_due = round(total_extras - retained, 3)
    status = "returned" if retained == 0 else ("retained" if returned == 0 else "partly_retained")
    detail = {**extras, "note": note.strip()[:200], "returned": returned, "still_due": still_due}
    db.update_check(out["id"], deposit_retained=retained, deposit_detail=json.dumps(detail),
                    deposit_status=status if deposit else "none", deposit_settled_by=by,
                    deposit_settled_at=time.time() if now is None else now)
    price = default_price(out)
    if out["rental_price"] is None:
        db.update_check(out["id"], rental_price=price)
    total = round(price + total_extras + FISCAL_STAMP, 3)
    year = datetime.date.today().year
    with db.connect() as con:
        n = con.execute("SELECT COUNT(*) FROM invoices WHERE number LIKE ?", (f"{INVOICE_PREFIX}{year}-%",)).fetchone()[0]
        number = f"{INVOICE_PREFIX}{year}-{n + 1:04d}"
        con.execute("INSERT INTO invoices(number, in_check_id, total, created, created_by) VALUES(?,?,?,?,?)",
                    (number, in_check_id, total, time.time() if now is None else now, by))
    return invoice_for(in_check_id)


def deposit_detail(out):
    try:
        return json.loads(out["deposit_detail"]) if out and out["deposit_detail"] else None
    except ValueError:
        return None


def invoice_data(in_check_id):
    """Tout ce qu'il faut pour la facture (PDF et pages)."""
    inv = invoice_for(in_check_id)
    if not inv:
        return None
    c = db.get_check(in_check_id)
    out = db.get_check(c["out_check_id"])
    car = planning.get_car(c["car"]) or {"name": c["car"], "price_day": None}
    det = deposit_detail(out) or {"fuel": 0, "km": 0, "damages": 0, "other": 0, "returned": 0, "still_due": 0, "note": ""}
    s = billing.summary(c)
    days = out["rental_days"] or 1
    name = car["name"] if car.get("name") and car["name"] != c["car"] else ""
    lines = [(f"Location {name + ' (' + c['car'] + ')' if name else c['car']} : {days} jour(s)", default_price(out))]
    if det.get("fuel"):
        lines.append((f"Carburant manquant ({billing.eighths(s.get('fuel_out'))} -> {billing.eighths(s.get('fuel_in'))})", det["fuel"]))
    if det.get("km"):
        lines.append((f"Dépassement kilométrique ({billing.fr(s.get('extra_km', 0))} km)", det["km"]))
    if det.get("damages"):
        lines.append(("Dégâts constatés au retour" + (f" : {det['note']}" if det.get("note") else ""), det["damages"]))
    if det.get("other"):
        lines.append(("Autres frais", det["other"]))
    if FISCAL_STAMP:
        lines.append(("Timbre fiscal", FISCAL_STAMP))
    total = round(sum(v for _, v in lines), 3)
    vat = round(total - total / (1 + VAT_RATE / 100), 3) if VAT_RATE else 0.0
    return {"invoice": inv, "check": c, "out": out, "car": car, "lines": lines, "total": total,
            "vat": vat, "vat_rate": VAT_RATE, "deposit": out["deposit_amount"] or 0.0,
            "deposit_method": out["deposit_method"], "retained": out["deposit_retained"] or 0.0,
            "returned": det.get("returned", 0.0), "still_due": det.get("still_due", 0.0),
            "km": s if s.get("ready") else None}
