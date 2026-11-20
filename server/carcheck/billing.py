"""Kilométrage et carburant au retour : km parcourus, dépassement, carburant manquant, montants.
Calculé seulement à partir des valeurs CONFIRMÉES par l'employé (sortie et retour)."""
from . import db
from .config import (CURRENCY, EXTRA_KM_PRICE, FUEL_BILLING, FUEL_FEE, FUEL_PRICE, KM_BILLING,
                     KM_PER_DAY, TANK_LITERS)


def eighths(fuel):
    return "?" if fuel is None else f"{round(fuel * 8)}/8"


def fr(x):
    """12.5 -> '12,5' ; 10.0 -> '10' ; 1250 -> '1 250'."""
    t = f"{x:,.3f}".rstrip("0").rstrip(".")
    return t.replace(",", " ").replace(".", ",")


def money(x):
    return f"{x:,.3f}".replace(",", " ").replace(".", ",") + f" {CURRENCY}"


def summary(in_check):
    out = db.get_check(in_check["out_check_id"]) if in_check.get("out_check_id") else None
    if not out:
        return {"ready": False, "why": "pas de sortie liée"}
    missing = [n for n, c in (("sortie", out), ("retour", in_check)) if c["dash_status"] != "confirmed"]
    if missing:
        return {"ready": False, "why": "compteur à confirmer : " + " et ".join(missing)}

    dist = in_check["km"] - out["km"]
    if dist < 0:
        return {"ready": False, "why": f"km au retour ({in_check['km']}) plus petit qu'à la sortie ({out['km']}) : corrigez la saisie"}
    days = out["rental_days"] or 1
    per_day = KM_PER_DAY if out["km_per_day"] is None else out["km_per_day"]
    allowed = days * per_day if (KM_BILLING and per_day > 0) else None   # sans facturation : km notés seulement
    extra_km = max(0, dist - allowed) if allowed is not None else 0
    km_cost = round(extra_km * EXTRA_KM_PRICE, 3)

    missing_fuel = max(0.0, out["fuel"] - in_check["fuel"])
    if missing_fuel < 1 / 8 - 1e-9:            # la jauge se lit au huitième près
        missing_fuel = 0.0
    liters = round(missing_fuel * TANK_LITERS, 2)
    fuel_cost = round(liters * FUEL_PRICE + (FUEL_FEE if liters else 0), 3) if FUEL_BILLING else 0.0

    return {
        "ready": True, "km_out": out["km"], "km_in": in_check["km"], "distance": dist,
        "days": days, "km_per_day": per_day, "allowed": allowed, "extra_km": extra_km,
        "km_cost": km_cost, "fuel_out": out["fuel"], "fuel_in": in_check["fuel"],
        "fuel_missing_liters": liters, "fuel_cost": fuel_cost,
        "total": round(km_cost + fuel_cost, 3),
    }


def lines(s):
    """Texte court en français, pour les pages et le rapport."""
    if not s["ready"]:
        return [s["why"]]
    km = f"{fr(s['distance'])} km parcourus ({fr(s['km_out'])} → {fr(s['km_in'])})"
    if not KM_BILLING:
        out = [f"Kilométrage : {km}"]
    else:
        allowed = ("km illimités" if s["allowed"] is None
                   else f"{fr(s['allowed'])} km inclus ({s['days']} j × {fr(s['km_per_day'])})")
        out = [f"{km} · {allowed}"]
        out.append(f"Dépassement : {fr(s['extra_km'])} km × {fr(EXTRA_KM_PRICE)} = {money(s['km_cost'])}"
                   if s["extra_km"] else "Pas de dépassement de km")
    if not FUEL_BILLING:
        out.append(f"Carburant : {eighths(s['fuel_out'])} → {eighths(s['fuel_in'])}"
                   + (f", {fr(s['fuel_missing_liters'])} L manquants" if s["fuel_missing_liters"] else ""))
    elif s["fuel_missing_liters"]:
        out.append(f"Carburant : {eighths(s['fuel_out'])} → {eighths(s['fuel_in'])}, {fr(s['fuel_missing_liters'])} L manquants"
                   f" × {fr(FUEL_PRICE)} + frais {fr(FUEL_FEE)} = {money(s['fuel_cost'])}")
    else:
        out.append(f"Carburant : {eighths(s['fuel_out'])} → {eighths(s['fuel_in'])}, rien à payer")
    if KM_BILLING or FUEL_BILLING:
        out.append(f"À payer : {money(s['total'])}")
    return out
