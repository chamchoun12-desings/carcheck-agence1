"""Pages Planning, Voitures (agence) et Réserver (client, sans connexion)."""
import math
import time
import urllib.parse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from . import bookdocs, extensions, intake, maintenance, messages, planning, report, users
from .app import e, page, staff, who
from .config import (AGENCY_NAME, BASE_URL, BOOKING_AUTO_CONFIRM, BOOKING_DOCS_REQUIRED, CURRENCY, OWNER_PHONE,
                     WA_TPL_BOOKING_OK, WA_TPL_NEW_BOOKING)

router = APIRouter()
DAYS_FR = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
STATE_FR = {"free": "Disponible", "rented": "Louée", "reserved": "Réservée", "pending": "Demande en attente"}
STATUS_FR = {"pending": "En attente de confirmation", "confirmed": "Confirmée ✓", "refused": "Refusée",
             "cancelled": "Annulée", "converted": "Voiture remise ✓"}


# ---------- petites aides ----------
def parse_dt(v):
    return time.mktime(time.strptime(v, "%Y-%m-%dT%H:%M"))


def to_input(ts):
    return time.strftime("%Y-%m-%dT%H:%M", time.localtime(ts))


def nice(ts):
    lt = time.localtime(ts)
    return f"{DAYS_FR[lt.tm_wday]} {time.strftime('%d/%m %H:%M', lt)}"


def default_period():
    lt = time.localtime(time.time() + 86400)
    start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 10, 0, 0, 0, 0, -1))
    return start, start + 3 * 86400


def n_days(start, end):
    return max(1, math.ceil((end - start - 3600) / 86400))     # 1 h de tolérance


def price(car, start, end):
    if car["price_day"] is None:
        return ""
    d = n_days(start, end)
    return f"{d} j × {car['price_day']:g} = <b>{car['price_day'] * d:g} {e(CURRENCY)}</b>"


def car_title(c):
    extra = " · ".join(x for x in (c["category"], c["gearbox"], f"{c['seats']} places" if c["seats"] else "") if x)
    return f"<b>{e(c['name'])}</b> <span class='muted'>{e(c['plate'])}{' · ' + e(extra) if extra else ''}</span>"


def period_from(request, start_key="start", end_key="end"):
    q = request.query_params
    s0, e0 = default_period()
    try:
        s = parse_dt(q[start_key]) if q.get(start_key) else s0
        t = parse_dt(q[end_key]) if q.get(end_key) else e0
    except ValueError:
        s, t = s0, e0
    return s, t


def notify(phone, params, template, lang=None):
    try:
        return report.send_template(phone, params, template, lang) if phone else {"skipped": "no phone"}
    except Exception as err:          # une notification ne doit jamais bloquer une réservation
        return {"error": str(err)}


PLAN_CSS = """<style>
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:12px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.kpi b{display:block;font-size:1.6rem;line-height:1.1}.kpi span{font-size:.85rem;color:var(--mute)}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table.plan{border-collapse:separate;border-spacing:2px;min-width:760px}
table.plan th{font-size:.75rem;color:var(--mute);font-weight:600;text-align:center;padding:4px}
table.plan th.car,table.plan td.car{text-align:left;white-space:nowrap;padding:6px 8px;font-size:.85rem;position:sticky;left:0;background:var(--bg);z-index:1}
table.plan td.c{height:30px;min-width:40px;border-radius:5px;padding:0}
.free{background:#d3f9d8}.rented{background:#4263eb}.reserved{background:#f59f00}.pending{background:repeating-linear-gradient(45deg,#ffe8a1,#ffe8a1 5px,#fff3bf 5px,#fff3bf 10px)}
.late{background:#e03131}
@media (prefers-color-scheme:dark){.free{background:#1f3d2a}.pending{background:repeating-linear-gradient(45deg,#5c4a12,#5c4a12 5px,#40340d 5px,#40340d 10px)}}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:.85rem;margin:8px 0}.legend i{display:inline-block;width:14px;height:14px;border-radius:3px;vertical-align:-2px;margin-right:4px}
.cars{display:grid;gap:10px}.carrow{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}@media (max-width:520px){.row2{grid-template-columns:1fr}}
.msg{border-left:4px solid var(--accent)}
</style>"""


DOCS_TEXT = ("J’accepte que l’agence conserve ces photos jusqu’à la fin de ma location, uniquement pour vérifier "
             "mon identité et mon permis. Elles ne sont pas publiées ni utilisées par l’IA, et sont supprimées ensuite.")


def docs_fields(note=""):
    req = "required" if BOOKING_DOCS_REQUIRED else ""
    return f"""<fieldset class="card"><legend><b>Vos documents</b> · وثائقك</legend>
{f'<div class="card msg">{e(note)}</div>' if note else ''}
<p class="muted">Photos nettes, lisibles, sans reflet. Vous présenterez les originaux à l’agence au départ.</p>
<label for="id_type">Pièce d’identité</label>
<select id="id_type" name="id_type" onchange="document.getElementById('idb').hidden=this.value!=='cin';document.getElementById('idx').required=this.value==='passport'">
<option value="cin">Carte d’identité (CIN)</option><option value="passport">Passeport</option></select>
<label for="id_front">Recto de la CIN (ou page photo du passeport)</label><input id="id_front" name="id_front" type="file" accept="image/*,application/pdf" {req}>
<div id="idb"><label for="id_back">Verso de la CIN</label><input id="id_back" name="id_back" type="file" accept="image/*,application/pdf"></div>
<label for="idx">Date d’expiration de la pièce (obligatoire pour un passeport)</label><input id="idx" name="id_expiry" type="date">
<label for="license_front">Permis de conduire · recto</label><input id="license_front" name="license_front" type="file" accept="image/*,application/pdf" {req}>
<label for="license_back">Permis de conduire · verso (facultatif)</label><input id="license_back" name="license_back" type="file" accept="image/*,application/pdf">
<label for="lx">Permis valable jusqu’au</label><input id="lx" name="license_expiry" type="date" {req}>
<label style="display:flex;gap:8px;align-items:flex-start;font-weight:400"><input type="checkbox" name="consent" value="1" {req} style="width:auto;margin-top:4px"> {e(DOCS_TEXT)}</label>
</fieldset>"""


async def read_docs(id_front, id_back, license_front, license_back):
    out = {}
    for k, f in (("id_front", id_front), ("id_back", id_back), ("license_front", license_front), ("license_back", license_back)):
        out[k] = (await f.read(bookdocs.MAX_BYTES + 1)) if f is not None else b""
    return out


def docs_summary(r):
    """Une ligne pour l'agence : ce que le client a envoyé."""
    if r["docs_purged_at"]:
        return "documents supprimés"
    if (r["docs_status"] or "none") == "none":
        return "pas de documents" + (" (réservation par l’agence)" if r["source"] == "staff" else "")
    lic = f"permis valable jusqu’au {r['license_expiry'][8:10]}/{r['license_expiry'][5:7]}/{r['license_expiry'][:4]}" if r["license_expiry"] else "permis sans date"
    st = {"received": "à vérifier", "verified": "conformes ✓", "rejected": "à refaire"}.get(r["docs_status"], "")
    return f"{bookdocs.ID_TYPES.get(r['id_doc_type'], 'pièce')} + permis · {lic} · {st}"


def period_form(action, s, t, label="Voir les voitures libres", extra=""):
    return f"""<form method="get" action="{action}" class="card"><div class="row2">
<div><label for="start">Départ</label><input type="datetime-local" id="start" name="start" value="{to_input(s)}" required></div>
<div><label for="end">Retour</label><input type="datetime-local" id="end" name="end" value="{to_input(t)}" required></div></div>
{extra}<br><button>{label}</button></form>"""


# ---------- AGENCE : planning ----------
@router.get("/planning", response_class=HTMLResponse)
def planning_page(request: Request, user=Depends(staff)):
    q = request.query_params
    try:
        day0 = time.mktime(time.strptime(q["from"], "%Y-%m-%d")) if q.get("from") else None
    except ValueError:
        day0 = None
    if day0 is None:
        lt = time.localtime()
        day0 = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    days = 14
    ag = users.scope(user)
    t = planning.today(agency_id=ag)
    pending = planning.reservations("pending", agency_id=ag)
    msg = f'<div class="card msg">{e(q["msg"])}</div>' if q.get("msg") else ""

    kpis = f"""<div class="kpis">
<div class="kpi"><b>{len(t['free_now'])}</b><span>disponibles maintenant</span></div>
<div class="kpi"><b>{len(t['rented'])}</b><span>en location{f" · <b style='display:inline;font-size:1em;color:#e03131'>{len(t['late'])} en retard</b>" if t['late'] else ''}</span></div>
<div class="kpi"><b>{len(t['returns_today'])}</b><span>retours prévus aujourd’hui</span></div>
<div class="kpi"><b>{len(t['departures_today'])}</b><span>départs réservés aujourd’hui</span></div>
<div class="kpi"><b>{len(pending)}</b><span>demandes à confirmer</span></div></div>"""

    # retards, prolongations demandées sur WhatsApp, entretien
    late = extensions.late_now(ag)
    late_html = "".join(
        f"""<div class="card bad carrow"><div><b>{e(planning.get_car(r['car'])['name'] if planning.get_car(r['car']) else r['car'])}</b> {e(r['car'])} ·
{e(r['client_name'] or '')} {e(r['client_phone'] or '')}<br>retour prévu {nice(r['planned_return_ts'])} · en retard de
{(time.time() - r['planned_return_ts']) / 3600:.0f} h · {'alerte envoyée ✓' if r['late_alert_sent'] else 'alerte en attente'}</div>
<a class="btn" href="/check/{e(r['id'])}">Ouvrir</a></div>""" for r in late)
    late_html = f"<h2>En retard ({len(late)})</h2>{late_html}" if late else ""
    ext = extensions.pending(ag)
    ext_html = "".join(
        f"""<div class="card warn carrow"><div><b>{e(r['client_name'] or r['client_phone'] or '')}</b> demande <b>+{r['days']} jour(s)</b>
pour {e(r['car'])} · « {e(r['text'] or '')} »<br>retour actuel {nice(r['planned_return_ts'])} → nouveau {nice(r['planned_return_ts'] + r['days'] * 86400)}
· {'arabe' if r['client_lang'] == 'ar' else 'français'}</div>
<form method="post" action="/extensions/{r['id']}"><button name="s" value="approve" class="btn ok">Valider</button>
<button name="s" value="refuse" class="btn grey">Refuser</button></form></div>""" for r in ext)
    ext_html = f"<h2>Prolongations demandées sur WhatsApp ({len(ext)})</h2>{ext_html}" if ext else ""
    maint = [(c, [a for a in al if a["level"] == "due" or "non saisi" not in a["text"]]) for c, al in maintenance.fleet_alerts(ag)]
    maint = [(c, al) for c, al in maint if al]
    maint_html = "".join(
        f"""<div class="card {'bad' if any(a['level'] == 'due' for a in al) else 'warn'}"><a href="/cars/{e(c['plate'])}"><b>{e(c['name'])}</b> {e(c['plate'])}</a> ·
{' · '.join(e(a['text']) for a in al)}</div>""" for c, al in maint)
    maint_html = f"<h2>Entretien ({len(maint)})</h2>{maint_html}" if maint else ""

    # « Un client appelle » : voitures libres sur une période
    s, tt = period_from(request, "qs", "qe")
    if q.get("qs"):
        free = planning.available(s, tt, agency_id=ag)
        items = "".join(f"""<div class="card carrow"><div>{car_title(c)}<br><span class="muted">{price(c, s, tt)}</span></div>
<a class="btn" href="/planning?{urllib.parse.urlencode({'book': c['plate'], 'qs': to_input(s), 'qe': to_input(tt)})}#nouvelle">Réserver pour un client</a></div>"""
                        for c in free) or '<div class="card">Aucune voiture libre sur cette période.</div>'
        answer = f"<h3>{len(free)} voiture(s) libre(s) du {nice(s)} au {nice(tt)}</h3>{items}"
    else:
        answer = ""
    search = f"""<h2>Un client appelle : quelles voitures sont libres ?</h2>
<form method="get" action="/planning" class="card"><div class="row2">
<div><label for="qs">Départ</label><input type="datetime-local" id="qs" name="qs" value="{to_input(s)}" required></div>
<div><label for="qe">Retour</label><input type="datetime-local" id="qe" name="qe" value="{to_input(tt)}" required></div></div><br>
<button>Chercher</button></form>{answer}"""

    # demandes en attente
    reqs = "".join(f"""<div class="card carrow"><div><b>{e(r['client_name'])}</b> · {e(r['client_phone'])}<br>
{e(r['car_name'] or r['car'])} <span class="muted">{e(r['car'])}</span> · {nice(r['start_ts'])} → {nice(r['end_ts'])}<br>
<span class="muted">Documents : {e(docs_summary(r))}</span> {f'<a href="/reservations/{r["id"]}/docs">voir</a>' if bookdocs.files_of(r['id']) else ''}</div>
<form method="post" action="/reservations/{r['id']}/status"><button name="s" value="confirmed" class="btn ok">Confirmer</button>
<button name="s" value="refused" class="btn grey">Refuser</button></form></div>""" for r in pending)
    reqs = f"<h2>Demandes de réservation à confirmer ({len(pending)})</h2>{reqs}" if pending else ""

    # grille
    head = "".join(f"<th>{DAYS_FR[time.localtime(day0 + i * 86400).tm_wday]}<br>{time.strftime('%d/%m', time.localtime(day0 + i * 86400))}</th>"
                   for i in range(days))
    body = ""
    for row in planning.grid(day0, days, agency_id=ag):
        cells = "".join(
            f'<td class="c {"late" if c.get("late") else c["state"]}" title="{e(c.get("title") or STATE_FR[c["state"]])}"></td>'
            for c in row["cells"])
        body += f'<tr><td class="car">{e(row["car"]["name"])}<br><span class="muted">{e(row["car"]["plate"])}</span></td>{cells}</tr>'
    prev_ = time.strftime("%Y-%m-%d", time.localtime(day0 - 7 * 86400))
    next_ = time.strftime("%Y-%m-%d", time.localtime(day0 + 7 * 86400))
    grid = f"""<h2>Planning des {days} prochains jours</h2>
<div class="legend"><span><i class="free"></i>Disponible</span><span><i class="rented"></i>Louée</span>
<span><i class="reserved"></i>Réservée</span><span><i class="pending"></i>Demande en attente</span><span><i class="late"></i>En retard</span></div>
<div class="scroll"><table class="plan"><tr><th class="car">Voiture</th>{head}</tr>{body or '<tr><td>Aucune voiture : ajoutez-les dans Voitures.</td></tr>'}</table></div>
<p><a href="/planning?from={prev_}">← semaine précédente</a> · <a href="/planning">aujourd’hui</a> · <a href="/planning?from={next_}">semaine suivante →</a></p>
<p class="muted">Touchez une case pour voir le détail (client, dates).</p>"""

    # nouvelle réservation (téléphone / agence)
    book = q.get("book", "")
    opts = "".join(f'<option value="{e(c["plate"])}" {"selected" if c["plate"] == book else ""}>{e(c["name"])} · {e(c["plate"])}</option>'
                   for c in planning.cars(agency_id=ag))
    new = f"""<h2 id="nouvelle">Nouvelle réservation (client au téléphone ou à l’agence)</h2>
<form method="post" action="/planning/reserve" class="card">
<label for="car">Voiture</label><select id="car" name="car" required>{opts}</select>
<div class="row2"><div><label for="ns">Départ</label><input type="datetime-local" id="ns" name="start" value="{to_input(s)}" required></div>
<div><label for="ne">Retour</label><input type="datetime-local" id="ne" name="end" value="{to_input(tt)}" required></div></div>
<div class="row2"><div><label for="nn">Nom du client</label><input id="nn" name="name" required></div>
<div><label for="np">WhatsApp du client</label><input id="np" name="phone" inputmode="tel" placeholder="21698000000" required></div></div>
<div class="row2"><div><label for="note">Note</label><input id="note" name="note" placeholder="siège bébé, livraison aéroport…"></div>
<div><label for="nl">Langue des messages</label><select id="nl" name="lang"><option value="fr">Français</option><option value="ar">العربية</option></select></div></div><br>
<button>Enregistrer la réservation (confirmée)</button></form>"""

    upcoming = planning.reservations("confirmed", since=time.time(), agency_id=ag)
    up = "".join(f"""<div class="card carrow"><div><b>{e(r['client_name'])}</b> · {e(r['client_phone'])}{' · ' + e(r['note']) if r['note'] else ''}<br>
{e(r['car_name'] or r['car'])} · {nice(r['start_ts'])} → {nice(r['end_ts'])} <span class="muted">({'en ligne' if r['source'] == 'client' else 'agence, par ' + who(r['created_by'])}{' · confirmée par ' + who(r['decided_by']) if r['decided_by'] else ''})</span></div>
<form method="post" action="/reservations/{r['id']}/status"><button name="s" value="cancelled" class="btn grey">Annuler</button></form></div>"""
                 for r in upcoming)
    up = f"<h2>Réservations confirmées à venir ({len(upcoming)})</h2>{up}" if upcoming else ""

    link = f'<p class="muted">Page de réservation pour vos clients (à partager sur WhatsApp, Facebook…) : <a href="/reserver">{e(BASE_URL)}/reserver</a></p>'
    return page("Planning", PLAN_CSS + msg + kpis + late_html + ext_html + reqs + maint_html + search + grid + new + up + link)


@router.post("/planning/reserve")
def staff_reserve(car: str = Form(...), start: str = Form(...), end: str = Form(...), name: str = Form(...),
                  phone: str = Form(...), note: str = Form(""), lang: str = Form("fr"), user=Depends(staff)):
    try:
        r = planning.create_reservation(car, name, phone, parse_dt(start), parse_dt(end), source="staff", note=note,
                                        by=user["username"], lang=lang)
        msg = f"Réservation enregistrée : {r['client_name']}, {nice(r['start_ts'])} → {nice(r['end_ts'])}."
    except ValueError:
        msg = "Refusé : date invalide."
    except planning.Conflict as err:
        msg = f"Refusé : {err}."
    return RedirectResponse("/planning?" + urllib.parse.urlencode({"msg": msg}), 303)


@router.post("/reservations/{rid}/status")
def reservation_status(rid: int, s: str = Form(...), user=Depends(staff)):
    if s not in ("confirmed", "refused", "cancelled"):
        raise HTTPException(400)
    try:
        r = planning.set_status(rid, s, user["username"])
        msg = f"Réservation de {r['client_name']} : {STATUS_FR[s].lower()}."
        if s == "confirmed":
            car = planning.get_car(r["car"]) or {"name": r["car"]}
            # Modèle « reservation_confirmee » : {{1}} voiture, {{2}} départ, {{3}} retour, {{4}} agence, {{5}} lien
            notify(r["client_phone"], [car["name"], messages.date(r["start_ts"]), messages.date(r["end_ts"]), AGENCY_NAME,
                                       f"{BASE_URL}/reservation/{r['token']}"], WA_TPL_BOOKING_OK, r["client_lang"])
    except planning.Conflict as err:
        msg = f"Refusé : {err}."
    return RedirectResponse("/planning?" + urllib.parse.urlencode({"msg": msg}), 303)


@router.post("/extensions/{eid}")
def extension_decide(eid: int, s: str = Form(...), user=Depends(staff)):
    if s not in ("approve", "refuse"):
        raise HTTPException(400)
    try:
        r = extensions.decide(eid, s == "approve", user["username"])
        msg = ("Prolongation validée. " if r["status"] == "approved" else
               "Prolongation refusée" + (" : voiture réservée ensuite. " if r["reason"] == "reason_booked" else ". "))
        msg += "Message envoyé au client."
    except planning.Conflict as err:
        msg = f"Refusé : {err}."
    return RedirectResponse("/planning?" + urllib.parse.urlencode({"msg": msg}), 303)


# ---------- AGENCE : voitures ----------
@router.get("/cars", response_class=HTMLResponse)
def cars_page(request: Request, user=Depends(staff)):
    def form(c):
        c = c or {"plate": "", "name": "", "category": "", "price_day": None, "gearbox": "", "seats": None,
                  "active": 1, "public": 1}
        new = not c["plate"]
        return f"""<form method="post" action="/cars" class="card">
<div class="row2"><div><label>Immatriculation</label><input name="plate" value="{e(c['plate'])}" {'' if new else 'readonly'} required placeholder="123 TU 4567"></div>
<div><label>Modèle</label><input name="name" value="{e(c['name'] or '')}" required placeholder="Peugeot 208"></div></div>
<div class="row2"><div><label>Catégorie</label><input name="category" value="{e(c['category'] or '')}" placeholder="citadine, berline, SUV"></div>
<div><label>Prix par jour ({e(CURRENCY)})</label><input type="number" step="0.5" min="0" name="price_day" value="{'' if c['price_day'] is None else f"{c['price_day']:g}"}"></div></div>
<div class="row2"><div><label>Boîte</label><select name="gearbox">{''.join(f'<option {"selected" if (c["gearbox"] or "manuelle") == g else ""}>{g}</option>' for g in ("manuelle", "automatique"))}</select></div>
<div><label>Places</label><input type="number" min="1" max="9" name="seats" value="{c['seats'] or ''}"></div></div>
<label><input type="checkbox" name="public" value="1" {'checked' if c['public'] else ''} style="width:auto"> Visible sur la page client « Réserver » (prix obligatoire)</label>
<label><input type="checkbox" name="active" value="1" {'checked' if c['active'] else ''} style="width:auto"> Dans la flotte</label><br>
<button>{'Ajouter la voiture' if new else 'Enregistrer'}</button></form>"""
    all_cars = planning.cars(active_only=False, agency_id=users.scope(user))
    rows = "".join(f"<details class='card'><summary>{car_title(c)} · <a href='/cars/{e(c['plate'])}'>fiche</a>"
                   f"{'' if c['active'] else ' · <span class=tag>hors flotte</span>'}"
                   f"{' · <span class=tag>en ligne</span>' if c['public'] and c['price_day'] is not None else ''}</summary>{form(c)}</details>"
                   for c in all_cars)
    msg = f'<div class="card msg">{e(request.query_params["msg"])}</div>' if request.query_params.get("msg") else ""
    return page("Voitures", PLAN_CSS + msg + "<p class='muted'>Les voitures filmées sont ajoutées automatiquement : "
                "complétez le modèle et le prix pour les montrer aux clients.</p>"
                + rows + "<h2>Ajouter une voiture</h2>" + form(None))


@router.post("/cars")
def cars_save(plate: str = Form(...), name: str = Form(...), category: str = Form(""), price_day: str = Form(""),
              gearbox: str = Form(""), seats: str = Form(""), public: str = Form(""), active: str = Form(""),
              user=Depends(staff)):
    p = intake.normalize_plate(plate)
    if not p:
        return RedirectResponse("/cars?msg=Immatriculation+manquante", 303)
    try:
        pr = float(price_day) if price_day.strip() else None
        st = int(seats) if seats.strip() else None
    except ValueError:
        return RedirectResponse("/cars?msg=Prix+ou+places+invalides", 303)
    planning.upsert_car(p, name.strip()[:60], category.strip()[:30], pr, gearbox[:20], st, bool(active), bool(public),
                        user.get("agency_id"))
    return RedirectResponse("/cars?" + urllib.parse.urlencode({"msg": f"{name} enregistrée."}), 303)


# ---------- CLIENT : réserver (sans connexion) ----------
@router.get("/reserver", response_class=HTMLResponse)
def public_search(request: Request):
    s, t = period_from(request)
    err = ""
    if t <= s:
        err, t = '<div class="card msg">Le retour doit être après le départ.</div>', s + 86400
    free = planning.available(s, t, public_only=True)
    q = urllib.parse.urlencode({"start": to_input(s), "end": to_input(t)})
    items = "".join(f"""<div class="card carrow"><div>{car_title(c)}<br>{price(c, s, t)}</div>
<a class="btn" href="/reserver/{e(c['plate'])}?{q}">Réserver</a></div>""" for c in free)
    items = items or '<div class="card">Aucune voiture libre sur ces dates. Essayez d’autres dates ou appelez l’agence.</div>'
    return page(f"{AGENCY_NAME} · Réserver une voiture",
                PLAN_CSS + period_form("/reserver", s, t) + err +
                f"<h2>{len(free)} voiture(s) disponible(s)</h2><p class='muted'>{nice(s)} → {nice(t)}</p>" + items, nav=False)


@router.get("/reserver/{plate}", response_class=HTMLResponse)
def public_form(plate: str, request: Request):
    c = planning.get_car(plate)
    if not c or not c["active"] or not c["public"] or c["price_day"] is None:
        raise HTTPException(404)
    s, t = period_from(request)
    busy = planning.conflicts(plate, s, t)
    warn = '<div class="card msg">Cette voiture vient d’être prise sur ces dates. <a href="/reserver">Voir les autres voitures</a></div>' if busy else ""
    return page("Votre réservation", PLAN_CSS + f"""<div class="card">{car_title(c)}<br>{nice(s)} → {nice(t)}<br>{price(c, s, t)}</div>{warn}
<form method="post" action="/reserver/{e(plate)}" class="card" enctype="multipart/form-data">
<input type="hidden" name="start" value="{to_input(s)}"><input type="hidden" name="end" value="{to_input(t)}">
<label for="name">Nom et prénom</label><input id="name" name="name" required autocomplete="name">
<label for="phone">Numéro WhatsApp</label><input id="phone" name="phone" required inputmode="tel" placeholder="+216 98 000 000" autocomplete="tel">
<label for="lang">Langue des messages · لغة الرسائل</label><select id="lang" name="lang"><option value="fr">Français</option><option value="ar">العربية</option></select>
<div style="position:absolute;left:-5000px" aria-hidden="true"><input name="website" tabindex="-1" autocomplete="off"></div>
{docs_fields()}
<p class="muted">{'Votre réservation est confirmée tout de suite.' if BOOKING_AUTO_CONFIRM else 'L’agence vérifie vos documents et confirme votre demande sur WhatsApp. La voiture vous est gardée en attendant.'}
Paiement et originaux des documents à l’agence au départ.</p>
<button>{'Réserver' if BOOKING_AUTO_CONFIRM else 'Envoyer ma demande'}</button></form>""", nav=False)


@router.post("/reserver/{plate}")
async def public_book(plate: str, start: str = Form(...), end: str = Form(...), name: str = Form(...),
                      phone: str = Form(...), website: str = Form(""), lang: str = Form("fr"),
                      id_type: str = Form("cin"), id_expiry: str = Form(""), license_expiry: str = Form(""),
                      consent: str = Form(""), id_front: UploadFile | None = File(None),
                      id_back: UploadFile | None = File(None), license_front: UploadFile | None = File(None),
                      license_back: UploadFile | None = File(None)):
    if website:                                   # champ invisible rempli = robot
        raise HTTPException(400)
    c = planning.get_car(plate)
    if not c:
        raise HTTPException(404)
    files = await read_docs(id_front, id_back, license_front, license_back)
    sent = any(files.values())
    try:
        s_ts, e_ts = parse_dt(start), parse_dt(end)
        if BOOKING_DOCS_REQUIRED or sent:
            if not consent:
                raise bookdocs.DocError("cochez la case d’accord pour l’envoi de vos documents")
            dates = bookdocs.validate(files, id_type, id_expiry, license_expiry, e_ts, required=BOOKING_DOCS_REQUIRED)
        r = planning.create_reservation(plate, name, phone, s_ts, e_ts, source="client", lang=lang)
        if BOOKING_DOCS_REQUIRED or sent:
            bookdocs.save(r["id"], files, id_type, dates)
    except (ValueError, planning.Conflict, bookdocs.DocError) as err:
        reason = "date invalide" if isinstance(err, ValueError) else str(err)
        return page("Réservation impossible", f'<div class="card msg">{e(reason)}</div>'
                    f'<a class="btn" href="/reserver/{e(plate)}?{urllib.parse.urlencode({"start": start, "end": end})}">Corriger</a> '
                    f'<a class="btn grey" href="/reserver">Voir les voitures disponibles</a>', nav=False)
    # Modèle « nouvelle_reservation » à l'agence : {{1}} voiture, {{2}} départ, {{3}} retour, {{4}} client, {{5}} téléphone
    notify(OWNER_PHONE, [f"{c['name']} {c['plate']}", nice(r["start_ts"]), nice(r["end_ts"]),
                         r["client_name"], r["client_phone"]], WA_TPL_NEW_BOOKING)
    return RedirectResponse(f"/reservation/{r['token']}", 303)


@router.get("/reservation/{token}", response_class=HTMLResponse)
def public_status(token: str):
    r = planning.get_reservation(token=token)
    if not r:
        raise HTTPException(404)
    c = planning.get_car(r["car"]) or {"name": r["car"], "plate": r["car"], "category": "", "gearbox": "",
                                        "seats": None, "price_day": None}
    can_cancel = r["status"] in ("pending", "confirmed") and r["start_ts"] > time.time()
    st = r["docs_status"] or "none"
    if r["docs_purged_at"]:
        docs_block = '<div class="card">Vos documents ont été supprimés.</div>'
    elif (st == "rejected" or (st == "none" and r["source"] == "client")) and r["status"] in ("pending", "confirmed") \
            and r["start_ts"] > time.time():
        ask = (f"L’agence demande de renvoyer vos documents : {r['docs_note']}" if st == "rejected" and r["docs_note"]
               else "L’agence demande de renvoyer vos documents." if st == "rejected" else "")
        docs_block = (f'<form method="post" action="/reservation/{e(token)}/docs" enctype="multipart/form-data">'
                      f'{docs_fields(ask)}<button>Envoyer mes documents</button></form>') if (st == "rejected" or BOOKING_DOCS_REQUIRED) else ""
    else:
        docs_block = f'<div class="card">Documents : {"reçus, en cours de vérification" if st == "received" else "vérifiés ✓" if st == "verified" else "—"}</div>'
    cancel = (f'<form method="post" action="/reservation/{e(token)}/cancel"><button class="btn grey">Annuler ma réservation</button></form>'
              if can_cancel else "")
    return page("Ma réservation", PLAN_CSS + f"""<div class="card"><h2 style="margin-top:0">{e(STATUS_FR[r['status']])}</h2>
{car_title(c)}<br>{nice(r['start_ts'])} → {nice(r['end_ts'])}<br>{price(c, r['start_ts'], r['end_ts'])}<br>
<span class="muted">Au nom de {e(r['client_name'])} · {e(r['client_phone'])}</span></div>
{docs_block}
<p class="muted">Gardez ce lien : il montre l’état de votre réservation. {e(AGENCY_NAME)}</p>{cancel}""", nav=False)


@router.post("/reservation/{token}/docs")
async def public_docs(token: str, id_type: str = Form("cin"), id_expiry: str = Form(""), license_expiry: str = Form(""),
                      consent: str = Form(""), id_front: UploadFile | None = File(None), id_back: UploadFile | None = File(None),
                      license_front: UploadFile | None = File(None), license_back: UploadFile | None = File(None)):
    r = planning.get_reservation(token=token)
    if not r or r["status"] not in ("pending", "confirmed"):
        raise HTTPException(404)
    files = await read_docs(id_front, id_back, license_front, license_back)
    try:
        if not consent:
            raise bookdocs.DocError("cochez la case d’accord pour l’envoi de vos documents")
        dates = bookdocs.validate(files, id_type, id_expiry, license_expiry, r["end_ts"])
        bookdocs.purge(r["id"])                       # on remplace l'ancien envoi
        bookdocs.save(r["id"], files, id_type, dates)
    except bookdocs.DocError as err:
        return page("Documents refusés", f'<div class="card msg">{e(str(err))}</div>'
                    f'<a class="btn" href="/reservation/{e(token)}">Recommencer</a>', nav=False)
    return RedirectResponse(f"/reservation/{token}", 303)


# ---------- AGENCE : documents d'une réservation (connexion obligatoire) ----------
@router.get("/reservations/{rid}/docs", response_class=HTMLResponse)
def staff_docs(rid: int, user=Depends(staff)):
    r = planning.get_reservation(rid)
    if not r:
        raise HTTPException(404)
    files = bookdocs.files_of(rid)
    end = time.strftime("%d/%m/%Y", time.localtime(r["end_ts"]))
    imgs = "".join(
        f'<div class="card"><b>{e(bookdocs.SLOTS[k])}</b><br>' + (
            f'<a class="btn" href="/bookdocs/{rid}/{k}">Ouvrir le PDF</a>' if p.suffix == ".pdf"
            else f'<img src="/bookdocs/{rid}/{k}" alt="{e(bookdocs.SLOTS[k])}" style="max-width:100%;border-radius:8px">') + "</div>"
        for k, p in sorted(files.items()))
    def d(v):
        return f"{v[8:10]}/{v[5:7]}/{v[:4]}" if v else "non indiquée"
    return page(f"Documents · {r['client_name']}", PLAN_CSS + f"""
<div class="card">{e(r['client_name'])} · {e(r['client_phone'])} · location jusqu’au <b>{end}</b><br>
{e(bookdocs.ID_TYPES.get(r['id_doc_type'], '—'))} · expiration {d(r['id_expiry'])} · permis valable jusqu’au <b>{d(r['license_expiry'])}</b><br>
<span class="muted">État : {e(docs_summary(r))}{' · vérifié par ' + who(r['docs_checked_by']) if r['docs_checked_by'] else ''}</span></div>
<p class="muted">Vérifiez : même nom que la réservation, photo lisible, dates. Données personnelles : ne pas copier ni partager.
Supprimées automatiquement à la clôture de la location.</p>
{imgs or '<div class="card">Aucun document.</div>'}
<form method="post" action="/reservations/{rid}/docs" class="card">
<label for="note">Note pour le client (si à refaire)</label><input id="note" name="note" placeholder="Photo du permis floue, renvoyez-la">
<br><br><button name="ok" value="1" class="btn ok">Documents conformes</button>
<button name="ok" value="0" class="btn grey">À refaire</button></form>
<a href="/planning">← Planning</a>""")


@router.post("/reservations/{rid}/docs")
def staff_docs_check(rid: int, ok: int = Form(...), note: str = Form(""), user=Depends(staff)):
    r = planning.get_reservation(rid)
    if not r:
        raise HTTPException(404)
    bookdocs.check(rid, bool(ok), note, user["username"])
    msg = (f"Documents de {r['client_name']} conformes." if ok else
           f"Documents de {r['client_name']} à refaire : le client peut les renvoyer depuis son lien de suivi.")
    return RedirectResponse("/planning?" + urllib.parse.urlencode({"msg": msg}), 303)


@router.get("/bookdocs/{rid}/{slot}")
def staff_doc_file(rid: int, slot: str, user=Depends(staff)):
    """Seulement pour l'agence connectée. Jamais de lien public vers ces fichiers."""
    p = bookdocs.files_of(rid).get(slot)
    if not p:
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@router.post("/reservation/{token}/cancel")
def public_cancel(token: str):
    r = planning.get_reservation(token=token)
    if not r:
        raise HTTPException(404)
    if r["status"] in ("pending", "confirmed") and r["start_ts"] > time.time():
        planning.set_status(r["id"], "cancelled")
    return RedirectResponse(f"/reservation/{token}", 303)
