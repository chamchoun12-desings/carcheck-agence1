"""Nouvelle application agence : une seule page (static/agence.html) et une API JSON sous /api/a/.
La même page tourne dans le navigateur (fetch) et dans l'application Android (pont natif, hors ligne compris).
Page client séparée : /reserver (static/client.html) et son API publique /api/public/.
Tout ce qui change quelque chose est noté dans le journal de l'équipe (qui, quoi, quand)."""
import datetime
import html
import pathlib
import time

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import (ai, billing, bookdocs, compare, db, extensions, fleet, intake, maintenance, messages, money, pipeline,
               planning, report, users)
from .app import owner, staff
from .config import (AGENCY_NAME, BASE_URL, BOOKING_DOCS_REQUIRED, DOC_WARN_DAYS, OIL_EVERY_KM, OIL_WARN_KM,
                     OWNER_PHONE, WA_TPL_BOOKING_OK, WA_TPL_NEW_BOOKING)
from .web_planning import notify
from .zones import KIND_LABELS, KIND_LABELS_AR, KINDS, ZONE_LABELS, ZONE_LABELS_AR, ZONES

router = APIRouter()
STATIC = pathlib.Path(__file__).parent / "static"
DAY = 86400
JOBS = ("out", "in", "book", "maint", "cash")
PAY = {"cash": "espèces", "card": "carte", "cheque": "chèque", "transfer": "virement"}
CATEGORIES = ("citadine", "berline", "SUV", "utilitaire", "minibus")
STATE_OF = {"rented": "rented", "reserved": "booked", "pending": "pending"}
PICKUP_HOUR = 10          # page client : départ et retour à 10 h


def fail(msg, code=422):
    return JSONResponse({"ok": False, "error": str(msg)}, status_code=code)


def _static(name):
    return HTMLResponse((STATIC / name).read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


def _num(v, cast=float):
    """'' -> None, '12,5' -> 12.5 ; lève ValueError si illisible."""
    v = str(v if v is not None else "").strip().replace(",", ".").replace(" ", "")
    return cast(float(v)) if v else None


def _date_ok(v):
    if v:
        datetime.date.fromisoformat(v)
    return v or None


# ---------- pages ----------
@router.get("/", response_class=HTMLResponse)
def agence_page(user=Depends(staff)):
    return _static("agence.html")


@router.get("/reserver", response_class=HTMLResponse)
def client_page():
    page = (STATIC / "client.html").read_text(encoding="utf-8").replace("{{AGENCY}}", html.escape(AGENCY_NAME, quote=True))
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@router.get("/reservation/{token}")
def old_status_link(token: str):
    """Anciens liens envoyés aux clients : vers le suivi de la nouvelle page."""
    return RedirectResponse(f"/reserver?suivi={token}", 303)


# ---------- voitures : état, entretien, planning de la semaine ----------
def _papers(c, today=None):
    today = today or datetime.date.today()
    out = []
    for field, k in (("insurance_until", "ins"), ("inspection_until", "vis"), ("vignette_until", "vig")):
        v = c.get(field)
        if not v:
            out.append({"k": k, "d": None, "n": None, "lvl": 1})          # date non saisie : à surveiller
            continue
        n = (datetime.date.fromisoformat(v) - today).days
        out.append({"k": k, "d": v, "n": n, "lvl": 2 if n < 0 else 1 if n <= DOC_WARN_DAYS else 0})
    return out


def _oil(c, km):
    every = c.get("oil_every_km") or OIL_EVERY_KM
    if c.get("last_oil_km") is None or km is None:
        return {"next": None, "left": None, "lvl": 0, "every": every}
    nxt = c["last_oil_km"] + every
    left = nxt - km
    return {"next": nxt, "left": left, "lvl": 2 if left < 0 else 1 if left <= OIL_WARN_KM else 0, "every": every}


def _day0(now):
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def _docs_of(rid):
    return {slot: f"/bookdocs/{rid}/{slot}" for slot in bookdocs.files_of(rid)}


def _res_json(r):
    c = planning.get_car(r["car"]) or {}
    n = max(1, round((r["end_ts"] - r["start_ts"]) / DAY))
    return {"id": r["id"], "car": r["car"], "car_name": c.get("name") or r["car"], "name": r["client_name"] or "",
            "phone": r["client_phone"] or "", "lang": r["client_lang"] or "fr", "start": r["start_ts"], "end": r["end_ts"],
            "days": n, "status": r["status"], "price_day": r.get("price_day"), "license_expiry": r.get("license_expiry"),
            "id_type": r.get("id_doc_type"), "docs_status": r.get("docs_status") or "none",
            "docs": {} if r.get("docs_purged_at") else _docs_of(r["id"]), "source": r["source"]}


def car_json(c, now=None):
    now = time.time() if now is None else now
    km = maintenance.current_km(c["plate"])
    papers = _papers(c)
    oil = _oil(c, km)
    periods = planning.busy(c["plate"], now)
    d0 = _day0(now)
    days = []
    for i in range(7):
        a, b = d0 + i * DAY, d0 + (i + 1) * DAY
        hit = [p for p in periods if p["start"] < b and a < p["end"]]
        if not hit:
            days.append("free")
            continue
        top = max(hit, key=lambda p: planning.PRIORITY[p["kind"]])
        days.append("late" if top["late"] else STATE_OF[top["kind"]])
    j = {"plate": c["plate"], "name": c["name"] or c["plate"], "category": c.get("category") or "",
         "dt": c.get("dash_type") or 0, "km": km, "oil": oil, "papers": papers,
         "blocked": any(p["lvl"] == 2 for p in papers), "lvl": max([oil["lvl"]] + [p["lvl"] for p in papers]),
         "public": c.get("public", 1), "days": days, "st": "free"}
    rent = [p for p in periods if p["kind"] == "rented"]
    if rent:
        p = rent[0]
        out = db.get_check(p["ref"]) or {}
        j.update(st="late" if p["late"] else "rented", ret=p["planned"], out_id=p["ref"],
                 client=out.get("client_name") or out.get("client_phone") or "",
                 fuel_out8=None if out.get("fuel") is None else round(out["fuel"] * 8), km_out=out.get("km"))
    else:
        soon = [p for p in periods if p["kind"] == "reserved" and p["start"] < now + DAY and p["end"] > now]
        if soon:
            r = planning.get_reservation(soon[0]["ref"])
            j.update(st="booked", start=r["start_ts"], end=r["end_ts"], res=_res_json(r))
    return j


def _me(user):
    with db.connect() as con:
        r = con.execute("SELECT jobs, phone FROM users WHERE username=?", (user["username"],)).fetchone()
    return {"username": user["username"], "name": user.get("name") or users.display(user["username"]),
            "role": user["role"], "agency": users.agency_name(user.get("agency_id")),
            "jobs": [j for j in ((r[0] if r else "") or "").split(",") if j]}


def todo(agency_id=None, now=None):
    """Contrôles envoyés qui attendent l'employé : dégâts à vérifier (sortie), retour à terminer (caution, facture)."""
    now = time.time() if now is None else now
    out = []
    for c in db.list_checks(limit=60, agency_id=agency_id):
        if c["created"] < now - 14 * DAY or c["status"] in ("purged", "reported"):
            continue
        if c["kind"] == "in" and money.invoice_for(c["id"]):
            continue
        busy = c["status"] in ("uploaded", "analyzing")
        if c["kind"] == "out":
            if busy:
                what = "analyzing"
            elif any(m["status"] == "ai" for m in db.marks_for(c["id"])):
                what = "dmg"
            else:
                continue
        else:
            what = "analyzing" if busy else "finish"
        car = planning.get_car(c["car"]) or {}
        out.append({"id": c["id"], "kind": c["kind"], "car": c["car"], "car_name": car.get("name") or c["car"],
                    "client": c["client_name"] or "", "what": what, "ts": c["created"]})
    return out


@router.get("/api/a/state")
def state(user=Depends(staff)):
    """Tout ce qu'il faut pour l'accueil, le planning et les voitures (gardé par le téléphone pour le hors ligne)."""
    ag = users.scope(user)
    now = time.time()
    cars = [car_json(c, now) for c in planning.cars(agency_id=ag)]
    nreq = len(planning.reservations("pending", agency_id=ag)) + len(extensions.pending(ag))
    return {"ok": True, "me": _me(user), "agency": AGENCY_NAME, "now": now, "day0": _day0(now), "cars": cars,
            "requests": nreq, "todo": todo(ag, now)}


def _event_json(e):
    car = planning.get_car(e["car"]) if e["car"] else None
    return {"ts": e["ts"], "who": e["who"], "who_name": users.display(e["who"]), "kind": e["kind"], "car": e["car"],
            "car_name": (car or {}).get("name") or e["car"] or "", "detail": e["detail"] or ""}


@router.get("/api/a/cars/{plate}")
def car_detail(plate: str, user=Depends(staff)):
    c = planning.get_car(plate)
    if not c:
        raise HTTPException(404)
    j = car_json(c)
    j["history"] = [_event_json(e) for e in db.events(car=plate, limit=60)]
    if user["role"] == "owner":
        j["totals"] = fleet.totals(plate)
    return j


@router.post("/api/a/cars")
def car_save(plate: str = Form(...), name: str = Form(...), km: str = Form(""), dt: str = Form("0"),
             category: str = Form(""), oil_next: str = Form(""), ins: str = Form(""), vis: str = Form(""),
             vig: str = Form(""), public: str = Form("1"), old_plate: str = Form(""), user=Depends(owner)):
    """Ajouter ou modifier une voiture (patron)."""
    p = intake.normalize_plate(plate)
    old = intake.normalize_plate(old_plate) or None
    if not p or not (name or "").strip():
        return fail("modèle et plaque obligatoires")
    if old and old != p:
        return fail("la plaque ne se change pas : retirez la voiture puis ajoutez-la de nouveau")
    try:
        kmv, nxt = _num(km, int), _num(oil_next, int)
        dtv = int(dt or 0)
        ins, vis, vig = _date_ok(ins), _date_ok(vis), _date_ok(vig)
    except ValueError:
        return fail("kilomètres ou date invalides")
    if (kmv is not None and not 0 <= kmv <= 2_000_000) or dtv not in (0, 1, 2):
        return fail("kilomètres invalides")
    existing = planning.get_car(p)
    if not old and existing and existing["active"]:
        return fail("cette plaque est déjà dans la flotte")
    cat = category if category in CATEGORIES else ""
    with db.connect() as con:
        if existing:
            con.execute("UPDATE cars SET name=?, category=?, dash_type=?, active=1, public=?, insurance_until=?,"
                        " inspection_until=?, vignette_until=? WHERE plate=?",
                        (name.strip()[:60], cat, dtv, int(public == "1"), ins, vis, vig, p))
        else:
            con.execute("INSERT INTO cars(plate, name, category, active, public, created, agency_id, dash_type,"
                        " insurance_until, inspection_until, vignette_until) VALUES(?,?,?,1,?,?,?,?,?,?,?)",
                        (p, name.strip()[:60], cat, int(public == "1"), time.time(), user.get("agency_id"), dtv,
                         ins, vis, vig))
        if kmv is not None:
            con.execute("UPDATE cars SET km_start=? WHERE plate=?", (kmv, p))
    c = planning.get_car(p)
    if nxt is not None:
        every = c.get("oil_every_km") or OIL_EVERY_KM
        with db.connect() as con:
            con.execute("UPDATE cars SET last_oil_km=? WHERE plate=?", (nxt - every, p))
    db.log_event(user["username"], "edit" if existing and existing["active"] else "add", p, name.strip())
    return {"ok": True, "car": car_json(planning.get_car(p))}


@router.post("/api/a/cars/{plate}/remove")
def car_remove(plate: str, user=Depends(owner)):
    c = planning.get_car(plate)
    if not c:
        raise HTTPException(404)
    if db.latest_open_out(plate):
        return fail("la voiture est louée : attendez son retour")
    if [r for r in planning.reservations(since=time.time()) if r["car"] == plate and r["status"] in planning.ACTIVE]:
        return fail("des réservations sont prévues pour cette voiture : refusez-les d'abord")
    with db.connect() as con:
        con.execute("UPDATE cars SET active=0, public=0 WHERE plate=?", (plate,))
    db.log_event(user["username"], "remove", plate, c["name"])
    return {"ok": True}


@router.post("/api/a/cars/{plate}/oil")
def car_oil(plate: str, km: str = Form(""), user=Depends(staff)):
    if not planning.get_car(plate):
        raise HTTPException(404)
    try:
        kmv = _num(km, int)
    except ValueError:
        return fail("kilomètres invalides")
    kmv = kmv if kmv is not None else maintenance.current_km(plate)
    if kmv is None:
        return fail("kilométrage inconnu : tapez-le")
    maintenance.oil_done(plate, kmv, 0, user["username"])
    db.log_event(user["username"], "oil", plate, f"{kmv} km")
    return {"ok": True, "car": car_json(planning.get_car(plate))}


@router.get("/api/a/free")
def free_cars(start: str = "", end: str = "", user=Depends(staff)):
    try:
        s, e = _client_period(start, end, check_past=False)
    except ValueError as err:
        return fail(err)
    return {"ok": True, "cars": [c["plate"] for c in planning.available(s, e, agency_id=users.scope(user))]}


# ---------- sortie et retour ----------
@router.post("/api/a/dash-read")
async def dash_read(photo: UploadFile = File(...), user=Depends(staff)):
    """Lecture du compteur par l'IA, avant l'envoi (l'employé confirme ou corrige)."""
    b = await photo.read()
    if not b or len(b) > 20_000_000:
        return fail("photo vide ou trop lourde")
    try:
        r = ai.read_dashboard(b)
    except Exception:
        r = None
    if not r:
        return {"ok": True, "read": None}
    return {"ok": True, "read": {"km": r["km"], "fuel8": None if r["fuel"] is None else round(r["fuel"] * 8),
                                 "dash_type": r.get("dash_type"), "problem": r.get("problem"), "unit": r.get("unit")}}


@router.post("/api/a/checks")
async def check_create(bg: BackgroundTasks, kind: str = Form(...), car: str = Form(...),
                       client_name: str = Form(""), client_phone: str = Form(""), client_lang: str = Form("fr"),
                       license_expiry: str = Form(""), recorded_at: str = Form(""), phone_sha256: str = Form(""),
                       km: str = Form(""), fuel8: str = Form(""), days: str = Form(""), price_day: str = Form(""),
                       deposit: str = Form(""), pay: str = Form("cash"),
                       video: UploadFile = File(...), dash: UploadFile | None = File(None),
                       license: UploadFile | None = File(None), user=Depends(staff)):
    """Fin de l'assistant Sortie ou Retour (envoyé tout de suite, ou plus tard par le téléphone hors ligne)."""
    if kind not in ("out", "in"):
        return fail("type inconnu")
    plate = intake.normalize_plate(car)
    try:
        kmv, f8 = _num(km, int), _num(fuel8, int)
        nd, pd, dep = _num(days, int), _num(price_day), _num(deposit)
    except ValueError:
        return fail("nombre illisible (km, essence, jours, prix ou caution)")
    if kmv is None or not 0 <= kmv <= 2_000_000 or f8 is None or not 0 <= f8 <= 8:
        return fail("kilomètres et essence obligatoires")
    phone = planning.phone_digits(client_phone)
    if kind == "out":
        if not (client_name or "").strip() or not 8 <= len(phone) <= 15:
            return fail("nom et WhatsApp du client obligatoires")
        if nd is None or not 1 <= nd <= 365:
            return fail("nombre de jours invalide (1 à 365)")
        if pd is None or pd <= 0:
            return fail("tapez le prix par jour")
        if dep is None or dep < 0 or pay not in PAY:
            return fail("tapez le montant de la caution")
        try:
            lic = intake.parse_expiry(license_expiry)
        except intake.Refused as err:
            return fail(err)
        start = time.time()
        if not lic:
            return fail("date de validité du permis obligatoire")
        if lic < datetime.date.fromtimestamp(start + nd * DAY):
            return fail(f"permis valable jusqu'au {lic:%d/%m/%Y} seulement : il expire avant le retour")
        clash = [b for b in planning.conflicts(plate, start, start + nd * DAY, ignore_phone=phone)
                 if b["kind"] != "pending"]
        if clash:
            return fail("double location : " + planning.describe(clash[0]))
    data = await video.read()
    dash_b = (await dash.read()) if dash is not None else b""
    lic_b = (await license.read()) if license is not None else b""
    try:
        c = intake.save(plate, kind, data, None, phone or None, dash_b or None, signature=None,
                        license_bytes=lic_b or None, license_expiry=license_expiry if kind == "out" else "",
                        recorded_at=recorded_at or None, phone_sha256=phone_sha256 or None,
                        client_name=client_name, client_lang=client_lang, by=user["username"],
                        agency_id=user.get("agency_id"))
    except intake.Refused as err:
        return fail(err)
    db.set_dashboard(c["id"], kmv, f8 / 8, "confirmed", None, user["username"])
    if kind == "out":
        start = c["recorded_at"] or c["created"]
        ret = start + nd * DAY
        try:
            planning.convert_for_rental(c, ret)            # la réservation de ce client devient « remise »
        except planning.Conflict:
            pass                                           # déjà vérifié avant l'enregistrement
        db.set_rental(c["id"], nd, ret, None, user["username"], round(nd * pd, 3))
        money.take_deposit(c["id"], dep, PAY[pay], user["username"])
    db.log_event(user["username"], kind, plate, (client_name or "").strip() or c["client_name"] or "")
    bg.add_task(pipeline.process, c["id"])
    return {"ok": True, "check_id": c["id"], "car": c["car"], "server_time": c["server_time"]}


def _mark_json(c, m):
    before = compare.before_photo(c, m["photo"]) if c["kind"] == "in" and m["photo"] else None
    return {"id": m["id"], "zone": m["zone"], "kind": m["kind"], "size": m["size"], "status": m["status"],
            "is_new": bool(m["is_new"]), "source": m["source"],
            "fr": f"{KIND_LABELS.get(m['kind'], m['kind'])} · {ZONE_LABELS.get(m['zone'], m['zone'])}",
            "ar": f"{KIND_LABELS_AR.get(m['kind'], m['kind'])} · {ZONE_LABELS_AR.get(m['zone'], m['zone'])}",
            "photo": f"/s/media/{c['id']}/frames/{m['photo']}" if m["photo"] else None,
            "before": f"/s/media/{before[0]}/frames/{before[1]}" if before else None}


@router.get("/api/a/checks/{cid}")
def check_detail(cid: str, user=Depends(staff)):
    c = db.get_check(cid)
    if not c:
        raise HTTPException(404)
    car = planning.get_car(c["car"]) or {}
    j = {"ok": True, "id": cid, "kind": c["kind"], "car": c["car"], "car_name": car.get("name") or c["car"],
         "status": c["status"], "client": c["client_name"] or "", "ai_error": c["status"] == "error",
         "marks": [_mark_json(c, m) for m in db.marks_for(cid) if m["status"] != "rejected" or m["source"] == "ai"],
         "zones": [{"k": z, "fr": ZONE_LABELS[z], "ar": ZONE_LABELS_AR[z]} for z in ZONES],
         "kinds": [{"k": k, "fr": KIND_LABELS[k], "ar": KIND_LABELS_AR[k]} for k in KINDS]}
    if c["kind"] == "in":
        out = db.get_check(c["out_check_id"])
        s = billing.summary(c)
        sug = money.suggestion(c)
        late = (c["created"] - out["planned_return_ts"]) / 3600 if out.get("planned_return_ts") else 0
        j["money"] = {"deposit": out["deposit_amount"] or 0, "method": out["deposit_method"] or "",
                      "price": money.default_price(out), "days": out["rental_days"], "fuel": sug["fuel"], "km_cost": sug["km"],
                      "fuel_out8": None if out["fuel"] is None else round(out["fuel"] * 8),
                      "fuel_in8": None if c["fuel"] is None else round(c["fuel"] * 8),
                      "km_out": out["km"], "km_in": c["km"], "ready": s["ready"], "why": s.get("why", ""),
                      "late_h": round(late, 1) if late > 1 else 0}
        inv = money.invoice_for(cid)
        j["invoice"] = inv["number"] if inv else None
    return j


@router.post("/api/a/marks/{mid}")
def mark_set(mid: int, s: str = Form(...), user=Depends(staff)):
    if s not in ("confirmed", "rejected"):
        return fail("réponse inconnue")
    with db.connect() as con:
        r = con.execute("SELECT check_id FROM marks WHERE id=?", (mid,)).fetchone()
    if not r:
        raise HTTPException(404)
    db.set_mark_status(mid, s, user["username"])
    c = db.get_check(r[0])
    if c["kind"] == "in":
        compare.flag_new(c)
    return {"ok": True}


@router.post("/api/a/checks/{cid}/marks")
def mark_add(cid: str, zone: str = Form(...), kind: str = Form(...), user=Depends(staff)):
    """Dégât que l'IA n'a pas vu (ou analyse sans IA) : ajouté par l'employé, déjà confirmé."""
    c = db.get_check(cid)
    if not c:
        raise HTTPException(404)
    if zone not in ZONES or kind not in KINDS:
        return fail("choisissez l'endroit et le type de dégât")
    if c["status"] == "reported" or (c["kind"] == "in" and money.invoice_for(cid)):
        return fail("location déjà clôturée")
    db.add_mark(c, {"zone": zone, "kind": kind, "size": "medium", "photo": "", "photos": []},
                source="staff", status="confirmed", by=user["username"])
    if c["kind"] == "in":
        compare.flag_new(c)
    return check_detail(cid, user)


@router.post("/api/a/checks/{cid}/finish")
def check_finish(cid: str, damages: str = Form("0"), note: str = Form(""), user=Depends(staff)):
    """Sortie : tous les dégâts vérifiés. Retour : caution, facture, rapport WhatsApp au client."""
    c = db.get_check(cid)
    if not c:
        raise HTTPException(404)
    if c["status"] in ("uploaded", "analyzing"):
        return fail("analyse de la vidéo en cours : attendez un instant")
    marks = db.marks_for(cid)
    if c["kind"] == "out":
        if any(m["status"] == "ai" for m in marks):
            return fail("répondez d'abord Oui ou Non pour chaque dégât")
        return {"ok": True}
    for m in marks:                       # déjà présents à la sortie : rien de nouveau, confirmés d'office
        if m["status"] == "ai" and not m["is_new"]:
            db.set_mark_status(m["id"], "confirmed", user["username"])
    if any(m["status"] == "ai" and m["is_new"] for m in db.marks_for(cid)):
        return fail("répondez d'abord Oui ou Non pour chaque nouveau dégât")
    try:
        dmg = _num(damages) or 0.0
    except ValueError:
        return fail("montant des dégâts illisible")
    try:
        inv = money.settle(cid, dmg, 0.0, note, user["username"])
    except money.MoneyError as err:
        return fail(err)
    try:
        res = report.send(cid)
        sent = all("error" not in r and "skipped" not in r for r in res["results"].values())
    except ValueError:
        sent = False
    db.log_event(user["username"], "close", c["car"], inv["number"])
    d = money.invoice_data(cid)
    return {"ok": True, "invoice": inv["number"], "total": d["total"], "retained": d["retained"],
            "returned": d["returned"], "still_due": d["still_due"], "report_sent": sent,
            "link": f"{BASE_URL}/r/{c['share_token']}"}


# ---------- demandes : réservations des clients et prolongations ----------
@router.get("/api/a/requests")
def requests_list(user=Depends(staff)):
    ag = users.scope(user)
    res = [_res_json(r) for r in planning.reservations("pending", agency_id=ag)]
    ext = [{"id": e["id"], "car": e["car"], "car_name": (planning.get_car(e["car"]) or {}).get("name") or e["car"],
            "name": e["client_name"] or "", "phone": e["client_phone"] or "", "days": e["days"],
            "ret": e["planned_return_ts"]} for e in extensions.pending(ag)]
    return {"ok": True, "res": res, "ext": ext}


@router.post("/api/a/requests/res/{rid}")
def res_decide(rid: int, ok: str = Form(...), price_day: str = Form(""), user=Depends(staff)):
    r = planning.get_reservation(rid)
    if not r:
        raise HTTPException(404)
    if r["status"] != "pending":
        return fail("demande déjà traitée")
    car = planning.get_car(r["car"]) or {"name": r["car"]}
    lang = r["client_lang"] or "fr"
    n = max(1, round((r["end_ts"] - r["start_ts"]) / DAY))
    if ok == "1":
        try:
            pd = _num(price_day)
        except ValueError:
            pd = None
        if not pd or pd <= 0:
            return fail("tapez le prix par jour")
        try:
            planning.set_status(rid, "confirmed", user["username"])
        except planning.Conflict as err:
            return fail(err)
        with db.connect() as con:
            con.execute("UPDATE reservations SET price_day=? WHERE id=?", (round(pd, 3), rid))
        link = f"{BASE_URL}/reserver?suivi={r['token']}"
        # Modèle « reservation_confirmee » : {{1}} voiture, {{2}} départ, {{3}} retour, {{4}} agence, {{5}} lien (prix sur la page)
        notify(r["client_phone"], [car["name"], messages.date(r["start_ts"]), messages.date(r["end_ts"]), AGENCY_NAME, link],
               WA_TPL_BOOKING_OK, lang)
        report.send_text(r["client_phone"], messages.t(lang, "book_ok", car=car["name"], days=n, price=f"{pd:g}",
                                                       total=f"{n * pd:g}", link=link))
        db.log_event(user["username"], "book", r["car"], r["client_name"] or "")
        return {"ok": True, "status": "confirmed", "total": round(n * pd, 3)}
    planning.set_status(rid, "refused", user["username"])
    report.send_text(r["client_phone"], messages.t(lang, "book_refused", car=car["name"]))
    db.log_event(user["username"], "refuse", r["car"], r["client_name"] or "")
    return {"ok": True, "status": "refused"}


@router.post("/api/a/requests/ext/{eid}")
def ext_decide(eid: int, ok: str = Form(...), user=Depends(staff)):
    try:
        res = extensions.decide(eid, ok == "1", user["username"])
    except planning.Conflict as err:
        return fail(err)
    e = extensions.get(eid)
    out = db.get_check(e["out_check_id"])
    if res["status"] == "approved":
        db.log_event(user["username"], "more", out["car"], f"{out['client_name'] or ''} +{e['days']} j")
    return {"ok": True, "status": res["status"], "reason": res["reason"]}


# ---------- équipe et journal (patron) ----------
def _people():
    with db.connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT username, name, role, phone, jobs, active, agency_id FROM users ORDER BY active DESC, name")]
    for u in rows:
        u["jobs"] = [j for j in (u["jobs"] or "").split(",") if j]
        last = db.events(who=u["username"], limit=1)
        u["last"] = _event_json(last[0]) if last else None
    return rows


@router.get("/api/a/team")
def team(who: str = "", user=Depends(owner)):
    return {"ok": True, "people": _people(), "log": [_event_json(e) for e in db.events(who=who or None, limit=150)]}


@router.post("/api/a/team")
def team_save(username: str = Form(...), name: str = Form(...), phone: str = Form(""), jobs: str = Form(""),
              password: str = Form(""), role: str = Form("staff"), is_new: str = Form("0"), user=Depends(owner)):
    u = (username or "").strip().lower()
    js = ",".join(j for j in jobs.split(",") if j in JOBS)
    with db.connect() as con:
        old = con.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
    if u == user["username"] and role != "owner":
        return fail("vous ne pouvez pas retirer votre propre rôle de patron")
    try:
        if is_new == "1":
            if old:
                return fail("cet identifiant est déjà pris")
            users.add_user(u, name, password, role, user.get("agency_id"))
            db.log_event(user["username"], "staff", None, name.strip())
        elif not old:
            return fail("employé introuvable")
        elif password:
            users.add_user(u, name, password, role, old["agency_id"])
        else:
            if not (name or "").strip():
                return fail("écrivez le nom")
            if role not in users.ROLES:
                return fail("rôle inconnu")
            with db.connect() as con:
                con.execute("UPDATE users SET name=?, role=? WHERE username=?", (name.strip()[:60], role, u))
    except ValueError as err:
        return fail(err)
    with db.connect() as con:
        con.execute("UPDATE users SET phone=?, jobs=? WHERE username=?", (planning.phone_digits(phone), js, u))
    return {"ok": True}


@router.post("/api/a/team/{username}/remove")
def team_remove(username: str, user=Depends(owner)):
    if username == user["username"]:
        return fail("vous ne pouvez pas vous retirer vous-même")
    users.set_active(username, 0)
    return {"ok": True}


@router.get("/api/a/boss")
def boss(user=Depends(owner)):
    now = time.time()
    lt = time.localtime(now)
    start = time.mktime((lt.tm_year, lt.tm_mon, 1, 0, 0, 0, 0, 0, -1))
    f = fleet.month_figures(start, now, users.scope(user))
    return {"ok": True, "revenue": f["revenue"], "rentals": f["rentals"], "days": f["days"],
            "occupancy": f["occupancy"], "costs": round(f["repairs"] + f["upkeep"], 3), "retained": f["retained"],
            "per_car": [{"plate": x["car"]["plate"], "name": x["car"]["name"] or x["car"]["plate"],
                         "occ": round(x["occupancy"], 3), "revenue": x["revenue"]} for x in f["per_car"]]}


# ---------- page client : voitures libres (sans prix), demande avec documents, suivi ----------
def _client_period(start, end, check_past=True):
    try:
        a = datetime.date.fromisoformat(start)
        b = datetime.date.fromisoformat(end)
    except (TypeError, ValueError):
        raise ValueError("dates invalides")
    if b <= a:
        raise ValueError("la date de retour doit être après la date de départ")
    if check_past and a < datetime.date.today():
        raise ValueError("la date de départ est déjà passée")
    ts = lambda d: time.mktime((d.year, d.month, d.day, PICKUP_HOUR, 0, 0, 0, 0, -1))  # noqa: E731
    return ts(a), ts(b)


@router.get("/api/public/cars")
def public_cars(start: str = "", end: str = ""):
    try:
        s, e = _client_period(start, end)
    except ValueError as err:
        return fail(err)
    cars = [c for c in planning.available(s, e, public_only=True) if not maintenance.blocking(c["plate"])]
    return {"ok": True, "days": round((e - s) / DAY), "docs_required": BOOKING_DOCS_REQUIRED,
            "cars": [{"plate": c["plate"], "name": c["name"] or c["plate"], "category": c.get("category") or ""}
                     for c in cars]}


@router.post("/api/public/book")
async def public_book(car: str = Form(...), start: str = Form(...), end: str = Form(...), name: str = Form(...),
                      phone: str = Form(...), lang: str = Form("fr"), website: str = Form(""),
                      id_type: str = Form("cin"), id_expiry: str = Form(""), license_expiry: str = Form(""),
                      consent: str = Form(""), id_front: UploadFile | None = File(None),
                      id_back: UploadFile | None = File(None), license_front: UploadFile | None = File(None),
                      license_back: UploadFile | None = File(None)):
    if website:                                   # champ invisible rempli = robot
        return fail("refusé", 400)
    c = planning.get_car(car)
    if not c or not c["active"] or not c["public"]:
        return fail("voiture non disponible")
    files = {}
    for k, f in (("id_front", id_front), ("id_back", id_back), ("license_front", license_front),
                 ("license_back", license_back)):
        files[k] = (await f.read()) if f is not None else b""
    try:
        s, e = _client_period(start, end)
        sent = any(files.values())
        dates = None
        if BOOKING_DOCS_REQUIRED or sent:
            if not consent:
                raise bookdocs.DocError("cochez la case d’accord pour vos documents")
            dates = bookdocs.validate(files, id_type, id_expiry, license_expiry, e, required=BOOKING_DOCS_REQUIRED)
        r = planning.create_reservation(car, name, phone, s, e, source="client", lang=lang)
        if dates:
            bookdocs.save(r["id"], files, id_type, dates)
    except (ValueError, planning.Conflict, bookdocs.DocError) as err:
        return fail(err)
    # Modèle « nouvelle_reservation » à l'agence : {{1}} voiture, {{2}} départ, {{3}} retour, {{4}} client, {{5}} téléphone
    notify(OWNER_PHONE, [f"{c['name']} {c['plate']}", messages.date(r["start_ts"]), messages.date(r["end_ts"]),
                         r["client_name"], r["client_phone"]], WA_TPL_NEW_BOOKING)
    return {"ok": True, "token": r["token"]}


@router.get("/api/public/res/{token}")
def public_res(token: str):
    r = planning.get_reservation(token=token)
    if not r:
        return fail("réservation introuvable", 404)
    c = planning.get_car(r["car"]) or {}
    n = max(1, round((r["end_ts"] - r["start_ts"]) / DAY))
    pd = r.get("price_day") if r["status"] in ("confirmed", "converted") else None
    return {"ok": True, "status": r["status"], "car_name": c.get("name") or r["car"], "category": c.get("category") or "",
            "start": r["start_ts"], "end": r["end_ts"], "days": n, "price_day": pd,
            "total": round(n * pd, 3) if pd else None, "name": r["client_name"] or "",
            "docs_status": r.get("docs_status") or "none", "docs_note": r.get("docs_note") or "",
            "can_cancel": r["status"] in ("pending", "confirmed") and r["start_ts"] > time.time(),
            "agency": AGENCY_NAME}


@router.post("/api/public/res/{token}/cancel")
def public_res_cancel(token: str):
    r = planning.get_reservation(token=token)
    if not r:
        return fail("réservation introuvable", 404)
    if r["status"] not in ("pending", "confirmed") or r["start_ts"] <= time.time():
        return fail("cette réservation ne peut plus être annulée")
    planning.set_status(r["id"], "cancelled", "client")
    return {"ok": True}
