"""Fiche voiture et chiffres : historique des locations, dégâts, réparations, coûts, occupation."""
import json
import time

from . import db, maintenance, money, planning


def rentals(plate=None, since=None, until=None, agency_id=None):
    """Une ligne par location (sortie + retour éventuel), la plus récente d'abord."""
    q, a = ("SELECT o.*, i.id AS in_id, i.created AS in_created, i.km AS km_in, i.fuel AS fuel_in, i.status AS in_status"
            " FROM checks o LEFT JOIN checks i ON i.out_check_id=o.id"
            " WHERE o.kind='out' AND o.status NOT IN ('error','purged')"), []
    if plate:
        q += " AND o.car=?"
        a.append(plate)
    if until:
        q += " AND o.created<?"
        a.append(until)
    if since:
        q += " AND COALESCE(i.created, ?)>=?"
        a += [time.time(), since]
    if agency_id:
        q += " AND o.car IN (SELECT plate FROM cars WHERE agency_id=?)"
        a.append(agency_id)
    with db.connect() as con:
        rows = [dict(r) for r in con.execute(q + " ORDER BY o.created DESC", a)]
        for r in rows:
            r["new_marks"] = con.execute("SELECT COUNT(*) FROM marks WHERE check_id=? AND status='confirmed' AND is_new=1",
                                         (r["in_id"],)).fetchone()[0] if r["in_id"] else 0
            inv = con.execute("SELECT * FROM invoices WHERE in_check_id=?", (r["in_id"],)).fetchone() if r["in_id"] else None
            r["invoice"] = dict(inv) if inv else None
            r["detail"] = money.deposit_detail(r) or {}
    return rows


def damages(plate):
    """Nouveaux dégâts confirmés au retour, avec la réparation liée s'il y en a une."""
    with db.connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT m.*, c.server_time, c.client_phone FROM marks m JOIN checks c ON c.id=m.check_id"
            " WHERE m.car=? AND m.kind_of_check='in' AND m.is_new=1 AND m.status='confirmed' ORDER BY m.created DESC", (plate,))]
        for r in rows:
            rep = con.execute("SELECT * FROM repairs WHERE mark_id=?", (r["id"],)).fetchone()
            r["repair"] = dict(rep) if rep else None
    return rows


def totals(plate):
    rs = rentals(plate)
    reps = maintenance.repairs(plate)
    revenue = sum(r["invoice"]["total"] for r in rs if r["invoice"])
    days = sum(r["rental_days"] or 0 for r in rs if r["in_id"])
    repair_cost = sum(x["cost"] or 0 for x in reps if x["kind"] == "réparation")
    upkeep = sum(x["cost"] or 0 for x in reps if x["kind"] != "réparation")
    retained_dmg = sum((r["detail"] or {}).get("damages", 0) for r in rs)
    return {"rentals": len([r for r in rs if r["in_id"]]), "days": days, "revenue": round(revenue, 3),
            "repairs": round(repair_cost, 3), "upkeep": round(upkeep, 3), "retained_damages": round(retained_dmg, 3),
            "margin": round(revenue - repair_cost - upkeep, 3)}


def occupancy(plate, start, end, now=None):
    """Part du temps où la voiture était louée entre start et end (0 à 1)."""
    now = time.time() if now is None else now
    busy = 0.0
    for r in rentals(plate):
        a = r["created"]
        b = r["in_created"] or now
        lo, hi = max(a, start), min(b, end)
        if hi > lo:
            busy += hi - lo
    return min(1.0, busy / max(1.0, end - start))


def month_figures(start, end, agency_id=None):
    """Bilan : chiffre d'affaires, locations, occupation par voiture, coût des dégâts, cautions retenues."""
    with db.connect() as con:
        inv = [dict(r) for r in con.execute("SELECT i.*, c.car FROM invoices i JOIN checks c ON c.id=i.in_check_id"
                                            " WHERE i.created>=? AND i.created<?", (start, end))]
    cars = planning.cars(agency_id=agency_id)
    plates = {c["plate"] for c in cars}
    if agency_id:
        inv = [i for i in inv if i["car"] in plates]
    day0 = time.strftime("%Y-%m-%d", time.localtime(start))
    lt = time.localtime(end)
    # jour de fin exclu seulement si la période s'arrête pile à minuit
    day1 = time.strftime("%Y-%m-%d", lt if lt[3:6] == (0, 0, 0) else time.localtime(end + 86400))
    reps = [r for r in maintenance.repairs(since=day0, until=day1) if r["car"] in plates]
    closed = [r for r in rentals(since=start, agency_id=agency_id) if r["in_created"] and start <= r["in_created"] < end]
    per_car = []
    for c in cars:
        rev = sum(i["total"] for i in inv if i["car"] == c["plate"])
        cost = sum(r["cost"] or 0 for r in reps if r["car"] == c["plate"])
        per_car.append({"car": c, "occupancy": occupancy(c["plate"], start, end), "revenue": round(rev, 3),
                        "costs": round(cost, 3)})
    per_car.sort(key=lambda x: -x["revenue"])
    return {
        "revenue": round(sum(i["total"] for i in inv), 3),
        "invoices": len(inv),
        "rentals": len(closed),
        "days": sum(r["rental_days"] or 0 for r in closed),
        "repairs": round(sum(r["cost"] or 0 for r in reps if r["kind"] == "réparation"), 3),
        "upkeep": round(sum(r["cost"] or 0 for r in reps if r["kind"] != "réparation"), 3),
        "retained": round(sum(r["deposit_retained"] or 0 for r in closed), 3),
        "retained_damages": round(sum((r["detail"] or {}).get("damages", 0) for r in closed), 3),
        "new_damages": sum(r["new_marks"] for r in closed),
        "occupancy": round(sum(x["occupancy"] for x in per_car) / max(1, len(per_car)), 3),
        "per_car": per_car,
    }


def detail_json(r):
    return json.dumps(r.get("detail") or {}, ensure_ascii=False)
