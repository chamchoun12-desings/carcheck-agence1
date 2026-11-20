"""Web server. Run:  uvicorn carcheck.app:app --host 127.0.0.1 --port 8000
Put it behind HTTPS (Caddy or nginx). Staff pages need the STAFF_PASSWORD login.
The client report link /r/<token> is secret: only people with the link can open it."""
import html
import json
import pathlib
import secrets
import time

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import billing, compare, db, extensions, intake, money, pipeline, planning, report, users
from .config import (AGENCY_NAME, KM_BILLING, KM_PER_DAY, LATE_GRACE_MIN, REMINDER_HOURS, STAFF_PASSWORD, STAFF_USER,
                     VAULT, WA_VERIFY_TOKEN)
from .zones import KIND_LABELS, KINDS, SIZE_LABELS, SIZES, ZONE_LABELS, ZONES

app = FastAPI(title="AI Car Check")
security = HTTPBasic()
e = html.escape
db.init()


def staff(cred: HTTPBasicCredentials = Depends(security)):
    """Chaque employé se connecte avec son identifiant : on sait qui a filmé, validé, encaissé."""
    u = users.authenticate(cred.username, cred.password)
    if not u:
        raise HTTPException(401, "login required", headers={"WWW-Authenticate": "Basic"})
    return u


def owner(user=Depends(staff)):
    if user["role"] != "owner":
        raise HTTPException(403, "réservé au propriétaire")
    return user


def who(username):
    return e(users.display(username))


CSS = """<style>
:root{--ink:#14161a;--mute:#6b7280;--line:#e5e7eb;--accent:#d9480f;--ok:#2b8a3e;--bg:#fff;--card:#f8f9fa}
@media (prefers-color-scheme:dark){:root{--ink:#e9ecef;--mute:#9aa0a6;--line:#2c2f36;--bg:#111317;--card:#1a1d23}}
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--ink);
max-width:900px;margin:0 auto;padding:16px}a{color:var(--accent)}h1{font-size:1.4rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:12px 0}
label{display:block;margin:10px 0 4px;font-weight:600}input,select{width:100%;padding:10px;font-size:1rem;
border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
button,.btn{display:inline-block;padding:10px 16px;border:0;border-radius:8px;background:var(--accent);color:#fff;
font-size:1rem;cursor:pointer;text-decoration:none}.btn.ok{background:var(--ok)}.btn.grey{background:#6b7280}
.muted{color:var(--mute);font-size:.9rem}.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pair img,.shot{width:100%;border-radius:8px;border:1px solid var(--line)}.tag{display:inline-block;padding:2px 8px;
border-radius:99px;font-size:.8rem;background:var(--line)}.tag.new{background:var(--accent);color:#fff}
.tag.confirmed{background:var(--ok);color:#fff}table{width:100%;border-collapse:collapse}
td,th{padding:8px;border-bottom:1px solid var(--line);text-align:left;font-size:.95rem}
nav{display:flex;flex-wrap:wrap;gap:4px 14px}.warn{border-left:4px solid #e8590c}.bad{border-left:4px solid #e03131}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}@media (max-width:520px){.row2{grid-template-columns:1fr}}code{font-size:.8rem;word-break:break-all}</style>"""


def page(title, body, nav=True):
    links = ('<nav><a href="/">Application</a><a href="/ancien">Nouveau film</a><a href="/planning">Planning</a><a href="/checks">Contrôles</a>'
             '<a href="/cars">Voitures</a><a href="/monthly">Bilan</a><a href="/users">Équipe</a></nav>') if nav else ""
    return HTMLResponse(f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>{CSS}</head>
<body>{links}<h1>{e(title)}</h1>{body}</body></html>""")


# ---------- 1. Upload (staff phone) ----------
@app.get("/ancien", response_class=HTMLResponse)
def upload_form(user=Depends(staff)):
    """Ancien formulaire d'envoi (la nouvelle application est à la racine « / »)."""
    return page(f"{AGENCY_NAME} · Car check", """
<div class="card"><p class="muted">Un tour lent : avant → droite → arrière → gauche, puis intérieur et compteur.
60 à 120 secondes. Moins de 45 s = refusé. Ne filmez pas les visages.</p>
<form method="post" action="/upload" enctype="multipart/form-data" id="f">
<label>Immatriculation</label><input name="car" placeholder="123 TU 4567 (vide = lue dans la vidéo)">
<label>Type</label><select name="kind"><option value="out">Sortie (départ)</option><option value="in">Retour</option></select>
<label>WhatsApp du client (sortie seulement)</label><input name="client_phone" placeholder="21698000000" inputmode="tel">
<label>Nom du client</label><input name="client_name" autocomplete="off">
<label>Langue des messages au client</label><select name="client_lang"><option value="fr">Français</option><option value="ar">العربية</option></select>
<label>Vidéo</label><input type="file" name="video" accept="video/*" capture="environment" required>
<label>Photo du compteur (km + carburant)</label><input type="file" name="dash" accept="image/*">
<p class="muted">Contact mis, photo nette du compteur kilométrique et de la jauge.</p>
<fieldset class="card" id="lic"><legend>Permis du client (sortie)</legend>
<label>Date d’expiration</label><input type="date" name="license_expiry">
<label>Photo du permis</label><input type="file" name="license" accept="image/*">
<p class="muted">Données personnelles (INPDP) : visible par l’agence seulement, jamais envoyée à l’IA, supprimée à la clôture de la location.</p></fieldset>
<label>Signature du client</label>
<canvas id="sig" width="600" height="200" style="width:100%;height:160px;border:1px solid var(--line);border-radius:8px;background:#fff;touch-action:none"></canvas>
<button type="button" class="btn grey" id="sigclear" style="margin-top:6px">Effacer la signature</button>
<input type="hidden" name="signature" id="sigdata">
<input type="hidden" name="gps" id="gps"><br><br><button>Envoyer</button></form></div>
<script>(function(){var c=document.getElementById('sig'),x=c.getContext('2d'),d=false,used=false;
x.lineWidth=3;x.lineCap='round';x.strokeStyle='#111';
function pt(ev){var r=c.getBoundingClientRect();return[(ev.clientX-r.left)*c.width/r.width,(ev.clientY-r.top)*c.height/r.height]}
c.addEventListener('pointerdown',function(ev){d=true;used=true;var p=pt(ev);x.beginPath();x.moveTo(p[0],p[1]);c.setPointerCapture(ev.pointerId)});
c.addEventListener('pointermove',function(ev){if(!d)return;var p=pt(ev);x.lineTo(p[0],p[1]);x.stroke()});
c.addEventListener('pointerup',function(){d=false});
document.getElementById('sigclear').onclick=function(){x.clearRect(0,0,c.width,c.height);used=false};
document.getElementById('f').addEventListener('submit',function(){document.getElementById('sigdata').value=used?c.toDataURL('image/png'):''});
var k=document.querySelector('select[name=kind]');k.onchange=function(){document.getElementById('lic').hidden=k.value!=='out'}})();</script>
<script>navigator.geolocation&&navigator.geolocation.getCurrentPosition(p=>{
document.getElementById('gps').value=JSON.stringify({lat:p.coords.latitude,lon:p.coords.longitude,acc:p.coords.accuracy})});</script>""")


async def _read(f):
    return (await f.read()) if f is not None else b""


async def _save_upload(car, kind, client_phone, gps, video, dash, signature, license, license_expiry,
                       recorded_at, phone_sha256, client_name="", client_lang="fr", user=None):
    data = await _read(video)
    plate_source = "typed"
    if not intake.normalize_plate(car):
        found = intake.read_plate_from_video(data)
        if not found:
            raise intake.Refused("plaque non lue dans la vidéo : tapez-la et renvoyez")
        car, plate_source = found["plate"], "ai"
    try:
        gps_obj = json.loads(gps) if gps else None
    except ValueError:
        gps_obj = None
    sig = signature if isinstance(signature, str) else await _read(signature)
    return intake.save(car, kind, data, gps_obj, client_phone.strip() or None, (await _read(dash)) or None,
                       signature=sig or None, license_bytes=(await _read(license)) or None,
                       license_expiry=license_expiry, recorded_at=recorded_at or None,
                       phone_sha256=phone_sha256 or None, plate_source=plate_source,
                       client_name=client_name, client_lang=client_lang,
                       by=(user or {}).get("username"), agency_id=(user or {}).get("agency_id"))


@app.post("/upload")
async def upload(bg: BackgroundTasks, car: str = Form(""), kind: str = Form(...),
                 client_phone: str = Form(""), gps: str = Form(""),
                 video: UploadFile = File(...), dash: UploadFile | None = File(None),
                 signature: str = Form(""), license: UploadFile | None = File(None),
                 license_expiry: str = Form(""), client_name: str = Form(""), client_lang: str = Form("fr"),
                 user=Depends(staff)):
    try:
        c = await _save_upload(car, kind, client_phone, gps, video, dash, signature, license,
                               license_expiry, "", "", client_name, client_lang, user)
    except intake.Refused as err:
        return page("Refusé", f'<div class="card">{e(str(err))}</div><a class="btn" href="/ancien">Recommencer</a>')
    bg.add_task(pipeline.process, c["id"])
    return page("Enregistré ✓", f"""<div class="card"><p><b>saved</b> · {e(c['car'])} · {e(c['kind'])}</p>
<p>Heure serveur : <b>{e(c['server_time'])}</b></p><p>SHA-256 : <code>{e(c['sha256'])}</code></p>
<p class="muted">Analyse en cours…</p></div><a class="btn" href="/check/{e(c['id'])}">Voir le contrôle</a>""")


@app.post("/api/upload")
async def api_upload(bg: BackgroundTasks, car: str = Form(""), kind: str = Form(...),
                     client_phone: str = Form(""), gps: str = Form(""),
                     video: UploadFile = File(...), dash: UploadFile | None = File(None),
                     signature: UploadFile | None = File(None), license: UploadFile | None = File(None),
                     license_expiry: str = Form(""), recorded_at: str = Form(""), phone_sha256: str = Form(""),
                     client_name: str = Form(""), client_lang: str = Form("fr"), user=Depends(staff)):
    """Envoi depuis l'application (y compris contrôles filmés hors ligne). Réponse JSON."""
    try:
        c = await _save_upload(car, kind, client_phone, gps, video, dash, signature, license,
                               license_expiry, recorded_at, phone_sha256, client_name, client_lang, user)
    except intake.Refused as err:
        return JSONResponse({"ok": False, "error": str(err)}, status_code=422)
    bg.add_task(pipeline.process, c["id"])
    return {"ok": True, "check_id": c["id"], "car": c["car"], "server_time": c["server_time"],
            "plate_source": c["plate_source"], "url": f"/check/{c['id']}"}


# ---------- 2. Staff review ----------
@app.get("/checks", response_class=HTMLResponse)
def checks(user=Depends(staff)):
    def ret(c):
        if c["kind"] != "out":
            return ""
        return e(c["planned_return"]) if c["planned_return"] else "<span class='tag new'>à saisir</span>"
    rows = "".join(
        f"<tr><td><a href='/check/{e(c['id'])}'>{e(c['car'])}</a></td><td>{e(c['kind'])}</td>"
        f"<td>{e(c['server_time'])}</td><td>{ret(c)}</td><td>{who(c['filmed_by'])}</td>"
        f"<td><span class='tag'>{e(c['status'])}</span></td></tr>"
        for c in db.list_checks(agency_id=users.scope(user)))
    return page("Contrôles", "<div style='overflow-x:auto'><table><tr><th>Voiture</th><th>Type</th><th>Heure</th>"
                             f"<th>Retour prévu</th><th>Filmé par</th><th>Statut</th></tr>{rows}</table></div>")


def _ts_label(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _rental_form(c, open_=True):
    days = c["rental_days"] or 3
    kmd = f'{(KM_PER_DAY if c["km_per_day"] is None else c["km_per_day"]):.0f}'
    car = planning.get_car(c["car"]) or {}
    price = "" if c["rental_price"] is None and not car.get("price_day") else (
        f'{c["rental_price"]:g}' if c["rental_price"] is not None else f'{car["price_day"] * days:g}')
    kmd_field = (f'<label for="kmd">Km inclus par jour (0 = illimité)</label><input type="number" name="km_per_day" '
                 f'id="kmd" min="0" max="5000" value="{kmd}">\n') if KM_BILLING else ""
    default = time.strftime("%Y-%m-%dT%H:%M", time.localtime(c["planned_return_ts"] or c["created"] + days * 86400))
    form = f"""<form method="post" action="/check/{e(c['id'])}/rental">
<label for="days">Durée (jours)</label><input type="number" name="days" id="days" min="1" max="365" value="{days}" required>
{kmd_field}<label for="price">Prix de la location (pour la facture)</label><input type="number" step="0.5" min="0" name="price" id="price" value="{price}">
<label for="ret">Date et heure de retour prévues</label><input type="datetime-local" name="ret" id="ret" value="{default}" required>
<p class="muted">Calculée depuis l’heure de sortie, modifiable. Rappel WhatsApp {REMINDER_HOURS:.0f} h avant, au client et à l’agence.</p>
<button>Enregistrer la location</button></form>
<script>(function(){{var d=document.getElementById('days'),r=document.getElementById('ret');d.oninput=function(){{
var t=new Date(({c['created']})*1000+d.value*864e5),p=function(n){{return String(n).padStart(2,'0')}};
r.value=t.getFullYear()+'-'+p(t.getMonth()+1)+'-'+p(t.getDate())+'T'+p(t.getHours())+':'+p(t.getMinutes())}}}})()</script>"""
    if open_:
        return f'<div class="card"><b>Obligatoire :</b> saisissez la durée de location avant de remettre la clé.{form}</div>'
    return f'<details class="card"><summary>Prolonger ou modifier la location</summary>{form}</details>'


def _rental_card(c):
    if not c["planned_return"]:
        return _rental_form(c)
    remind = _ts_label(c["planned_return_ts"] - REMINDER_HOURS * 3600)
    state = "envoyé ✓" if c["reminder_sent"] else f"programmé le {remind}"
    kmd = KM_PER_DAY if c["km_per_day"] is None else c["km_per_day"]
    kms = "km notés au compteur" if not KM_BILLING else "km illimités" if kmd <= 0 else f"{kmd:.0f} km/jour inclus"
    head = (f'<div class="card">Location : <b>{c["rental_days"]} jour(s)</b> · {kms} · retour prévu '
            f'<b>{e(c["planned_return"])}</b><br>Rappel WhatsApp {REMINDER_HOURS:.0f} h avant : {state}</div>')
    return head if db.has_return(c["id"]) else head + _rental_form(c, open_=False)


def return_status(in_check):
    """« à l'heure » ou « en retard de X h » pour un contrôle de retour."""
    out = db.get_check(in_check["out_check_id"]) if in_check.get("out_check_id") else None
    if not out or not out["planned_return_ts"]:
        return ""
    late = in_check["created"] - out["planned_return_ts"]
    when = f"retour prévu {e(out['planned_return'])}"
    if late > LATE_GRACE_MIN * 60:
        return f"{when} · <b>rendu en retard de {late / 3600:.1f} h</b>"
    return f"{when} · rendu à l’heure ✓"


@app.post("/check/{check_id}/rental")
def set_rental(check_id: str, days: int = Form(...), ret: str = Form(""),
               km_per_day: str = Form(""), price: str = Form(""), user=Depends(staff)):
    c = db.get_check(check_id)
    if not c or c["kind"] != "out":
        raise HTTPException(404)
    back = f'<a class="btn" href="/check/{e(check_id)}">Retour</a>'
    if not 1 <= days <= 365:
        return page("Refusé", f'<div class="card">La durée doit être entre 1 et 365 jours.</div>{back}')
    try:
        ts = time.mktime(time.strptime(ret, "%Y-%m-%dT%H:%M")) if ret else c["created"] + days * 86400
    except ValueError:
        return page("Refusé", f'<div class="card">Date de retour invalide.</div>{back}')
    if ts <= c["created"]:
        return page("Refusé", f'<div class="card">Le retour doit être après la sortie.</div>{back}')
    try:
        kmd = float(km_per_day) if km_per_day.strip() else None
    except ValueError:
        return page("Refusé", f'<div class="card">Km par jour invalide.</div>{back}')
    try:
        planning.convert_for_rental(c, ts)        # pas de double location avec une autre réservation
    except planning.Conflict as err:
        return page("Refusé", f'<div class="card">{e(str(err))}. Raccourcissez la location ou changez de voiture '
                              f'(voir le <a href="/planning">planning</a>).</div>{back}')
    try:
        pr = float(price) if price.strip() else None
    except ValueError:
        return page("Refusé", f'<div class="card">Prix invalide.</div>{back}')
    db.set_rental(check_id, days, ts, kmd, user["username"], pr)
    return RedirectResponse(f"/check/{check_id}", 303)


def _dash_card(c):
    """Photo du compteur : l'IA propose, l'employé confirme ou corrige."""
    cid = e(c["id"])
    has_photo = intake.dashboard_path(c) is not None
    photo = (f'<img class="shot" src="/s/media/{cid}/dashboard.jpg" alt="Compteur" style="max-width:420px">'
             if has_photo else '<p class="muted">Pas encore de photo du compteur.</p>')
    if c["dash_status"] == "confirmed":
        state = '<span class="tag confirmed">confirmé</span>'
    elif c["dash_status"] == "ai":
        state = f'<span class="tag">proposé par l’IA · {(c["dash_confidence"] or 0):.0%}</span> à vérifier'
    else:
        state = '<span class="tag new">à saisir</span>'
    fuel_now = None if c["fuel"] is None else round(c["fuel"] * 8)
    fuel_opts = "".join(f'<option value="{i}" {"selected" if i == fuel_now else ""}>{i}/8'
                        f'{" (vide)" if i == 0 else " (moitié)" if i == 4 else " (plein)" if i == 8 else ""}</option>'
                        for i in range(9))
    locked = c["status"] == "reported"
    form = "" if locked else f"""<form method="post" action="/check/{cid}/dash">
<label for="km">Kilométrage total (km)</label><input type="number" name="km" id="km" min="0" max="2000000" value="{'' if c['km'] is None else c['km']}" required inputmode="numeric">
<label for="fuel">Carburant</label><select name="fuel" id="fuel" required><option value="">—</option>{fuel_opts}</select><br><br>
<button class="btn ok">Confirmer le compteur</button></form>
<details><summary>{'Remplacer' if has_photo else 'Ajouter'} la photo du compteur</summary>
<form method="post" action="/check/{cid}/dash-photo" enctype="multipart/form-data">
<input type="file" name="photo" accept="image/*" required><br><br><button>Envoyer et lire</button></form></details>"""
    return f'<div class="card"><b>Compteur</b> · {state}<div style="margin:10px 0">{photo}</div>{form}</div>'


def _billing_card(c):
    s = billing.summary(c)
    body = "<br>".join(e(x) for x in billing.lines(s))
    return f'<div class="card"><b>Kilométrage et carburant</b><br>{body}</div>'


@app.post("/check/{check_id}/dash")
def dash_confirm(check_id: str, km: int = Form(...), fuel: str = Form(...), user=Depends(staff)):
    c = db.get_check(check_id)
    if not c or c["status"] == "reported":
        raise HTTPException(404)
    if not (0 <= km <= 2_000_000) or not fuel.isdigit() or not 0 <= int(fuel) <= 8:
        return page("Refusé", f'<div class="card">Kilométrage ou carburant invalide.</div>'
                              f'<a class="btn" href="/check/{e(check_id)}">Retour</a>')
    db.set_dashboard(check_id, km, int(fuel) / 8, "confirmed", c["dash_confidence"], user["username"])
    return RedirectResponse(f"/check/{check_id}", 303)


@app.post("/check/{check_id}/dash-photo")
async def dash_photo(check_id: str, photo: UploadFile = File(...), user=Depends(staff)):
    c = db.get_check(check_id)
    if not c or c["status"] == "reported":
        raise HTTPException(404)
    try:
        intake.save_dashboard(check_id, await photo.read())
    except intake.Refused as err:
        return page("Refusé", f'<div class="card">{e(str(err))}</div><a class="btn" href="/check/{e(check_id)}">Retour</a>')
    pipeline.read_dashboard(check_id)
    return RedirectResponse(f"/check/{check_id}", 303)


def _m(x):
    return billing.money(x or 0)


def _deposit_card(c):
    """Sortie : encaisser la caution (montant, moyen de paiement, qui)."""
    if c["deposit_status"] in ("returned", "partly_retained", "retained"):
        return (f'<div class="card"><b>Caution</b> {_m(c["deposit_amount"])} ({e(c["deposit_method"] or "")}) · '
                f'retenu {_m(c["deposit_retained"])} · clôturée par {who(c["deposit_settled_by"])}</div>')
    held = (f'<p>Caution reçue : <b>{_m(c["deposit_amount"])}</b> ({e(c["deposit_method"])}) par {who(c["deposit_by"])}</p>'
            if c["deposit_status"] == "held" else '<p class="muted">Aucune caution enregistrée.</p>')
    opts = "".join(f'<option {"selected" if c["deposit_method"] == m else ""}>{m}</option>' for m in money.METHODS)
    return f"""<details class="card" {'open' if c["deposit_status"] != "held" else ''}><summary><b>Caution</b></summary>{held}
<form method="post" action="/check/{e(c['id'])}/deposit"><div class="row2">
<div><label>Montant ({e(billing.CURRENCY)})</label><input type="number" step="1" min="0" name="amount" value="{'' if c['deposit_amount'] is None else f"{c['deposit_amount']:g}"}" required></div>
<div><label>Moyen de paiement</label><select name="method">{opts}</select></div></div><br>
<button>Enregistrer la caution</button></form></details>"""


def _settle_card(c):
    """Retour : retenues proposées (carburant, km), dégâts et autres à saisir, somme restituée, puis facture."""
    out = db.get_check(c["out_check_id"])
    sug = money.suggestion(c)
    dep = out["deposit_amount"] or 0
    new = [m for m in db.marks_for(c["id"]) if m["status"] == "confirmed" and m["is_new"]]
    hint = (f'{len(new)} nouveau(x) dégât(s) confirmé(s) : saisissez le montant retenu (estimation ou devis).'
            if new else "Aucun nouveau dégât confirmé.")
    return f"""<div class="card warn"><b>Clôturer la location : caution et facture</b>
<p>Caution reçue : <b>{_m(dep)}</b>{' (' + e(out['deposit_method']) + ')' if out['deposit_method'] else ' · aucune caution enregistrée'}
· prix de la location : <b>{_m(money.default_price(out))}</b></p>
<form method="post" action="/check/{e(c['id'])}/settle" oninput="var t=(+fuel.value||0)+(+km.value||0)+(+damages.value||0)+(+other.value||0),r=Math.min({dep},t);
res.textContent='Retenu : '+r.toFixed(3)+' · rendu au client : '+({dep}-r).toFixed(3)+(t>{dep}?' · reste à payer : '+(t-{dep}).toFixed(3):'')">
<div class="row2"><div><label>Carburant manquant</label><input id="fuel" value="{sug['fuel']:g}" readonly></div>
<div><label>Dépassement km</label><input id="km" value="{sug['km']:g}" readonly></div></div>
<div class="row2"><div><label>Dégâts</label><input id="damages" type="number" step="0.5" min="0" name="damages" value="0"></div>
<div><label>Autres frais</label><input id="other" type="number" step="0.5" min="0" name="other" value="0"></div></div>
<label>Note (ex. devis carrossier)</label><input name="note" maxlength="200">
<p class="muted">{hint}</p><p id="res" class="muted"></p>
<button>Clôturer et créer la facture</button></form></div>"""


def _invoice_card(c):
    d = money.invoice_data(c["id"])
    if not d:
        return ""
    return (f'<div class="card"><b>Facture {e(d["invoice"]["number"])}</b> · total {_m(d["total"])} · caution retenue '
            f'{_m(d["retained"])}, rendue {_m(d["returned"])}{" · reste à payer " + _m(d["still_due"]) if d["still_due"] else ""}'
            f' · clôturée par {who(d["out"]["deposit_settled_by"])}<br>'
            f'<a class="btn" href="/invoice/{e(c["id"])}.pdf">Télécharger la facture PDF</a></div>')


def _agency():
    from .config import AGENCY_ADDRESS, AGENCY_PHONE, AGENCY_TAX_ID
    return {"name": AGENCY_NAME, "address": AGENCY_ADDRESS, "phone": AGENCY_PHONE, "tax_id": AGENCY_TAX_ID}


@app.post("/check/{check_id}/deposit")
def deposit(check_id: str, amount: float = Form(...), method: str = Form(...), user=Depends(staff)):
    try:
        money.take_deposit(check_id, amount, method, user["username"])
    except money.MoneyError as err:
        return page("Refusé", f'<div class="card">{e(str(err))}</div><a class="btn" href="/check/{e(check_id)}">Retour</a>')
    return RedirectResponse(f"/check/{check_id}", 303)


@app.post("/check/{check_id}/settle")
def settle(check_id: str, damages: float = Form(0), other: float = Form(0), note: str = Form(""), user=Depends(staff)):
    try:
        money.settle(check_id, damages, other, note, user["username"])
    except money.MoneyError as err:
        return page("Refusé", f'<div class="card">{e(str(err))}</div><a class="btn" href="/check/{e(check_id)}">Retour</a>')
    return RedirectResponse(f"/check/{check_id}", 303)


def _pdf_response(check_id):
    from . import pdf
    d = money.invoice_data(check_id)
    if not d:
        raise HTTPException(404)
    return Response(pdf.invoice_pdf(d, _agency()), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="facture-{d["invoice"]["number"]}.pdf"'})


@app.get("/invoice/{check_id}.pdf")
def invoice_staff(check_id: str, user=Depends(staff)):
    return _pdf_response(check_id)


@app.get("/r/{token}/facture.pdf")
def invoice_public(token: str):
    return _pdf_response(_by_token(token)["id"])


def _img(check_id, name, prefix="/s/media"):
    return f'<img loading="lazy" src="{prefix}/{e(check_id)}/frames/{e(name)}" alt="">' if name else '<div class="muted">—</div>'


@app.get("/check/{check_id}", response_class=HTMLResponse)
def check_view(check_id: str, user=Depends(staff)):
    c = db.get_check(check_id)
    if not c:
        raise HTTPException(404)
    if c["status"] in ("uploaded", "analyzing"):
        return HTMLResponse(page("Analyse en cours…", f'<meta http-equiv="refresh" content="4">'
                                 f'<div class="card">{e(c["car"])} · {c["n_frames"] or "?"} photos</div>').body)
    marks = db.marks_for(check_id)
    bad = json.loads(c["bad_photos"] or "[]")
    cards = []
    for m in marks:
        tag = f'<span class="tag new">NOUVEAU</span>' if m["is_new"] else ""
        st = f'<span class="tag {m["status"]}">{m["status"]}</span>'
        if c["kind"] == "in" and m["is_new"]:
            bp = compare.before_photo(c, m["photo"])
            imgs = f'<div class="pair"><div><div class="muted">Sortie</div>{_img(*bp) if bp else ""}</div>' \
                   f'<div><div class="muted">Retour</div>{_img(check_id, m["photo"])}</div></div>'
        else:
            imgs = _img(check_id, m["photo"]).replace("<img", '<img class="shot"')
        btns = "" if c["status"] == "reported" else (
            f'<form method="post" action="/mark/{m["id"]}" style="display:inline">'
            f'<button name="s" value="confirmed" class="btn ok">Confirmer</button> '
            f'<button name="s" value="rejected" class="btn grey">Rejeter</button></form>')
        by = f" · décidé par {who(m['decided_by'])}" if m["decided_by"] else ""
        cards.append(f"""<div class="card">{tag} {st} <b>{e(KIND_LABELS[m['kind']])}</b> · {e(ZONE_LABELS[m['zone']])}
· {e(SIZE_LABELS[m['size']])} <span class="muted">· {e(m['source'])} {m['confidence']:.0%} · {e(m['photo'] or '')}{by}</span>
<div style="margin:10px 0">{imgs}</div>{btns}</div>""")

    opts = lambda xs, lab: "".join(f'<option value="{x}">{e(lab[x])}</option>' for x in xs)
    frames_dir = pathlib.Path(c["dir"]) / "frames"
    photo_opts = "".join(f"<option>{p.name}</option>" for p in sorted(frames_dir.glob("f_*.jpg")))
    pending = sum(1 for m in marks if m["status"] == "ai")
    action = ""
    if c["kind"] == "in" and c["status"] != "reported":
        bill = billing.summary(c)
        if pending:
            action = f'<p class="muted">{pending} marque(s) à décider avant d’envoyer.</p>'
        elif not bill["ready"]:
            action = f'<p class="muted">Avant d’envoyer : {e(bill["why"])}.</p>'
        elif not money.invoice_for(check_id):
            action = _settle_card(c)
        else:
            action = _invoice_card(c) + (f'<form method="post" action="/report/{e(check_id)}"><button>'
                                         'Envoyer le rapport WhatsApp (client + agence)</button></form>')
    elif c["kind"] == "in" and money.invoice_for(check_id):
        action = _invoice_card(c)
    elif (c["kind"] == "out" and pending == 0 and c["status"] == "review" and c["planned_return"]
          and c["dash_status"] == "confirmed"):
        db.update_check(check_id, status="done")
    warn = f'<div class="card">⚠ Photos sombres/floues : {e(", ".join(bad))}. Refaites le tour à la lumière, ou notez « non visible » dans le rapport.</div>' if bad else ""
    err = f'<div class="card"><pre>{e(c["error"] or "")}</pre></div>' if c["status"] == "error" else ""
    integrity = "✓ intact" if intake.verify(check_id) else "✗ MODIFIÉ"
    extra = []
    if c["recorded_at"]:
        same = " · empreinte identique depuis le tournage ✓" if c["phone_sha256"] == c["sha256"] else ""
        extra.append(f"Filmé hors ligne le {_ts_label(c['recorded_at'])} (heure du téléphone), reçu par le serveur le "
                     f"{e(c['server_time'])}{same}")
    if c["plate_source"] == "ai":
        extra.append("Plaque lue par l’IA dans la vidéo : vérifiez-la")
    sigimg = (f'<div><div class="muted">Signature du client</div><img class="shot" style="max-width:320px;background:#fff" '
              f'src="/s/media/{e(check_id)}/signature.png" alt="Signature"></div>') if c["has_signature"] else \
             '<div class="muted">Pas de signature du client.</div>'
    lic = ""
    if c["kind"] == "out":
        st, txt = intake.license_status(c)
        color = {"expired": "#e03131", "soon": "#e8590c"}.get(st, "inherit")
        photo = (f' · <a href="/s/media/{e(check_id)}/license.jpg">photo du permis</a>'
                 if intake.file_path(c, "license.jpg") else (" · photo supprimée (location close)" if c["license_expiry"] else ""))
        lic = f'<div style="color:{color}"><b>Permis :</b> {e(txt)}{photo}</div>'
    people = [f"Filmé par {who(c['filmed_by'])}"] if c["filmed_by"] else []
    if c["dash_by"]:
        people.append(f"compteur confirmé par {who(c['dash_by'])}")
    if c["rental_by"]:
        people.append(f"location saisie par {who(c['rental_by'])}")
    client = " · ".join(x for x in (e(c["client_name"] or ""), e(c["client_phone"] or ""),
                                     "messages en arabe" if c["client_lang"] == "ar" else "messages en français") if x)
    capture = (f'<div class="card"><b>Client :</b> {client}<br>{" · ".join(people)}{"<br>" if people else ""}'
               f'{"<br>".join(e(x) for x in extra)}{"<br>" if extra else ""}{lic}{sigimg}</div>')
    if c["kind"] == "out":
        rental = _rental_card(c) + _deposit_card(c)
    else:
        st = return_status(c)
        rental = (f'<div class="card">{st}</div>' if st else "") + _billing_card(c)
    rental = _dash_card(c) + rental
    return HTMLResponse(page(f"{c['car']} · {'Sortie' if c['kind']=='out' else 'Retour'}", f"""
<div class="card">Heure serveur <b>{e(c['server_time'])}</b> · {c['duration']:.0f}s · {c['n_frames']} photos ·
fichier {integrity}<br><code>{e(c['sha256'])}</code><br>
<video controls preload="none" style="width:100%;margin-top:8px" src="/s/media/{e(check_id)}/walk.mp4"></video></div>
{err}{capture}{rental}{warn}{action}<h2>Marques ({len(marks)})</h2>{''.join(cards) or '<p class="muted">Aucune marque détectée.</p>'}
<details class="card"><summary>Ajouter une marque manquée</summary><form method="post" action="/check/{e(check_id)}/add">
<label>Zone</label><select name="zone">{opts(ZONES, ZONE_LABELS)}</select>
<label>Type</label><select name="kind">{opts(KINDS, KIND_LABELS)}</select>
<label>Taille</label><select name="size">{opts(SIZES, SIZE_LABELS)}</select>
<label>Photo</label><select name="photo">{photo_opts}</select><br><br><button>Ajouter (confirmée)</button></form></details>
""").body)


@app.post("/mark/{mark_id}")
def mark_decide(mark_id: int, s: str = Form(...), user=Depends(staff)):
    if s not in ("confirmed", "rejected"):
        raise HTTPException(400)
    db.set_mark_status(mark_id, s, user["username"])
    with db.connect() as con:
        check_id = con.execute("SELECT check_id FROM marks WHERE id=?", (mark_id,)).fetchone()[0]
    c = db.get_check(check_id)
    if c["kind"] == "in":
        compare.flag_new(c)
    return RedirectResponse(f"/check/{check_id}", 303)


@app.post("/check/{check_id}/add")
def mark_add(check_id: str, zone: str = Form(...), kind: str = Form(...), size: str = Form(...),
             photo: str = Form(""), user=Depends(staff)):
    c = db.get_check(check_id)
    if not c or zone not in ZONES or kind not in KINDS or size not in SIZES:
        raise HTTPException(400)
    db.add_mark(c, {"zone": zone, "kind": kind, "size": size, "photo": photo, "photos": [photo]},
                source="staff", status="confirmed", by=user["username"])
    if c["kind"] == "in":
        compare.flag_new(c)
    return RedirectResponse(f"/check/{check_id}", 303)


@app.post("/report/{check_id}")
def send_report(check_id: str, user=Depends(staff)):
    try:
        res = report.send(check_id)
    except ValueError as err:
        return page("Pas encore", f'<div class="card">{e(str(err))}</div>')
    return page("Rapport envoyé", f'<div class="card"><pre>{e(json.dumps(res, indent=2, ensure_ascii=False))}</pre></div>'
                                 f'<a class="btn" href="/r/{e(db.get_check(check_id)["share_token"])}">Voir la page client</a>')


# ---------- 3. Media ----------
def _file(check_id, rel):
    c = db.get_check(check_id)
    if not c:
        raise HTTPException(404)
    base = pathlib.Path(c["dir"]).resolve()
    p = (base / rel).resolve()
    if base not in p.parents or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/s/media/{check_id}/{rel:path}")
def staff_media(check_id: str, rel: str, user=Depends(staff)):
    return _file(check_id, rel)


@app.get("/r/{token}/media/{check_id}/{rel:path}")
def public_media(token: str, check_id: str, rel: str):
    c = _by_token(token)
    if check_id not in (c["id"], c["out_check_id"]):
        raise HTTPException(404)
    if not (rel in ("walk.mp4", "dashboard.jpg", "signature.png") or rel.startswith("frames/")):
        raise HTTPException(404)                   # jamais le permis ni les autres fichiers
    return _file(check_id, rel)


def _by_token(token):
    with db.connect() as con:
        r = con.execute("SELECT * FROM checks WHERE share_token=? AND kind='in'", (token,)).fetchone()
    if not r:
        raise HTTPException(404)
    return dict(r)


# ---------- 4. Client / owner report page (secret link) ----------
@app.get("/r/{token}", response_class=HTMLResponse)
def client_report(token: str):
    c = _by_token(token)
    out = db.get_check(c["out_check_id"])
    pre = f"/r/{token}/media"
    marks = [m for m in db.marks_for(c["id"]) if m["status"] == "confirmed"]
    new = [m for m in marks if m["is_new"]]
    old = [m for m in marks if not m["is_new"]]
    blocks = []
    for m in new:
        bp = compare.before_photo(c, m["photo"])
        blocks.append(f"""<div class="card"><b>{e(KIND_LABELS[m['kind']])} · {e(ZONE_LABELS[m['zone']])}</b>
· {e(SIZE_LABELS[m['size']])}<p class="muted">Cette marque est apparue au retour du véhicule.</p>
<div class="pair"><div><div class="muted">Sortie · {e(out['server_time'])}</div>{_img(*bp, prefix=pre) if bp else ''}</div>
<div><div class="muted">Retour · {e(c['server_time'])}</div>{_img(c['id'], m['photo'], prefix=pre)}</div></div></div>""")
    old_list = "".join(f"<li>{e(KIND_LABELS[m['kind']])} · {e(ZONE_LABELS[m['zone']])}</li>" for m in old) or "<li>aucune</li>"
    return HTMLResponse(page(f"{c['car']} · rapport de retour", f"""
<div class="card">Sortie : <b>{e(out['server_time'])}</b> · Retour : <b>{e(c['server_time'])}</b><br>{return_status(c)}</div>
{f'<div class="card"><a class="btn" href="/r/{e(token)}/facture.pdf">Facture PDF</a></div>' if money.invoice_for(c["id"]) else ''}
<h2>Nouvelles marques ({len(new)})</h2>{''.join(blocks) or '<p>Aucune nouvelle marque. Merci !</p>'}
<h2>Kilométrage et carburant</h2><div class="card">{'<br>'.join(e(x) for x in billing.lines(billing.summary(c)))}</div>
<div class="pair"><div><div class="muted">Compteur sortie</div><img class="shot" src="{pre}/{e(out['id'])}/dashboard.jpg" alt="" onerror="this.remove()"></div>
<div><div class="muted">Compteur retour</div><img class="shot" src="{pre}/{e(c['id'])}/dashboard.jpg" alt="" onerror="this.remove()"></div></div>
<h2>Déjà présentes à la sortie</h2><ul>{old_list}</ul>
<h2>Signatures du client</h2><div class="pair">
<div><div class="muted">Au départ</div>{'<img class="shot" style="background:#fff" src="' + pre + '/' + e(out['id']) + '/signature.png" alt="">' if out['has_signature'] else '<p class="muted">—</p>'}</div>
<div><div class="muted">Au retour</div>{'<img class="shot" style="background:#fff" src="' + pre + '/' + e(c['id']) + '/signature.png" alt="">' if c['has_signature'] else '<p class="muted">—</p>'}</div></div>
<h2>Vidéos complètes</h2><div class="pair">
<div><div class="muted">Sortie</div><video controls preload="none" style="width:100%" src="{pre}/{e(out['id'])}/walk.mp4"></video>
<code>{e(out['sha256'])}</code></div>
<div><div class="muted">Retour</div><video controls preload="none" style="width:100%" src="{pre}/{e(c['id'])}/walk.mp4"></video>
<code>{e(c['sha256'])}</code></div></div>
<p class="muted">Les empreintes SHA-256 prouvent que les vidéos n’ont pas été modifiées depuis l’enregistrement.
Le client et l’agence voient exactement les mêmes images.</p>""", nav=False).body)


# ---------- 5. Monthly ----------
@app.get("/monthly", response_class=HTMLResponse)
def monthly_page(user=Depends(staff)):
    import time as _t
    from . import fleet, monthly
    end = _t.time()
    return HTMLResponse(monthly.render(monthly.rows(), fleet.month_figures(end - 30 * 86400, end, users.scope(user))))


# ---------- 6. WhatsApp webhook (button replies "OK" / "I want to talk") ----------
@app.get("/webhook")
def wa_verify(request: Request):
    q = request.query_params
    if WA_VERIFY_TOKEN and q.get("hub.verify_token") == WA_VERIFY_TOKEN:
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403)


@app.post("/webhook")
async def wa_incoming(request: Request):
    import time
    body = await request.json()
    for entry in body.get("entry", []):
        for ch in entry.get("changes", []):
            for msg in ch.get("value", {}).get("messages", []) or []:
                text = (msg.get("button", {}) or {}).get("text") or (msg.get("text", {}) or {}).get("body", "")
                with db.connect() as con:
                    con.execute("INSERT INTO replies(phone, text, raw, created) VALUES(?,?,?,?)",
                                (msg.get("from"), text, json.dumps(msg), time.time()))
                try:
                    extensions.handle_incoming(msg.get("from", ""), text)   # « prolonger 2 jours » / « تمديد 2 »
                except Exception:                                        # le webhook doit toujours répondre 200
                    pass
    return {"ok": True}


# ---------- Planning, voitures, réservation client, flotte, équipe ----------
from . import agence, web_fleet, web_planning  # noqa: E402  (importés en dernier : ils réutilisent page() et staff())

app.include_router(agence.router)        # en premier : « / », « /reserver » et l'API de la nouvelle application
app.include_router(web_planning.router)
app.include_router(web_fleet.router)
