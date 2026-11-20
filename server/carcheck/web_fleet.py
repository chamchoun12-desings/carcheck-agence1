"""Fiche voiture (historique, dégâts, réparations, coûts, entretien) et page Équipe (employés, agences)."""
import datetime
import time
import urllib.parse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import billing, fleet, maintenance, planning, users
from .app import e, owner, page, staff, who
from .web_planning import PLAN_CSS
from .zones import KIND_LABELS, ZONE_LABELS

router = APIRouter()


def _m(x):
    return billing.money(x or 0)


def _d(ts):
    return time.strftime("%d/%m/%Y", time.localtime(ts)) if ts else "—"


def _back(plate, msg):
    return RedirectResponse(f"/cars/{plate}?" + urllib.parse.urlencode({"msg": msg}), 303)


# ---------- fiche voiture ----------
@router.get("/cars/{plate}", response_class=HTMLResponse)
def car_file(plate: str, request: Request, user=Depends(staff)):
    c = planning.get_car(plate)
    if not c:
        raise HTTPException(404)
    msg = request.query_params.get("msg")
    km = maintenance.current_km(plate)
    al = maintenance.alerts(c)
    t = fleet.totals(plate)
    block = maintenance.blocking(plate)

    alerts = "".join(f'<li style="color:{"#e03131" if a["level"] == "due" else "#e8590c"}">{e(a["text"])}</li>' for a in al) \
        or "<li>Tout est à jour ✓</li>"
    docs = f"""<div class="card {'bad' if block else ''}"><b>Entretien</b>{' · <b>sortie bloquée</b> : ' + e(block) if block else ''}<ul>{alerts}</ul>
<form method="post" action="/cars/{e(plate)}/docs"><div class="row2">
<div><label>Assurance valable jusqu’au</label><input type="date" name="insurance" value="{e(c['insurance_until'] or '')}"></div>
<div><label>Visite technique jusqu’au</label><input type="date" name="inspection" value="{e(c['inspection_until'] or '')}"></div></div>
<div class="row2"><div><label>Vignette jusqu’au</label><input type="date" name="vignette" value="{e(c['vignette_until'] or '')}"></div>
<div><label>Vidange tous les (km)</label><input type="number" name="oil_every" min="1000" step="500" value="{c['oil_every_km'] or maintenance.OIL_EVERY_KM}"></div></div><br>
<button>Enregistrer les dates</button></form>
<form method="post" action="/cars/{e(plate)}/oil"><div class="row2">
<div><label>Vidange faite à (km)</label><input type="number" name="km" min="0" value="{km or ''}" required></div>
<div><label>Coût</label><input type="number" name="cost" min="0" step="0.5" value="0"></div></div><br>
<button>Vidange faite</button></form>
<p class="muted">Dernière vidange : {f"{c['last_oil_km']} km" if c['last_oil_km'] is not None else "non saisie"} · compteur actuel : {f"{km} km" if km is not None else "inconnu"}</p></div>"""

    kpis = f"""<div class="kpis">
<div class="kpi"><b>{t['rentals']}</b><span>locations terminées · {t['days']} jours</span></div>
<div class="kpi"><b>{_m(t['revenue'])}</b><span>chiffre d’affaires (factures)</span></div>
<div class="kpi"><b>{_m(t['repairs'])}</b><span>réparations</span></div>
<div class="kpi"><b>{_m(t['upkeep'])}</b><span>entretien</span></div>
<div class="kpi"><b>{_m(t['retained_damages'])}</b><span>retenu aux clients pour dégâts</span></div>
<div class="kpi"><b>{_m(t['margin'])}</b><span>CA − réparations − entretien</span></div></div>"""

    rows = ""
    for r in fleet.rentals(plate):
        dist = (r["km_in"] - r["km"]) if r["km_in"] is not None and r["km"] is not None else None
        inv = r["invoice"]
        rows += (f"<tr><td><a href='/check/{e(r['id'])}'>{_d(r['created'])}</a></td>"
                 f"<td>{('<a href=/check/' + e(r['in_id']) + '>' + _d(r['in_created']) + '</a>') if r['in_id'] else 'en cours'}</td>"
                 f"<td>{e(r['client_name'] or r['client_phone'] or '—')}</td><td>{r['rental_days'] or '—'}</td>"
                 f"<td>{dist if dist is not None else '—'}</td><td>{r['new_marks']}</td>"
                 f"<td>{_m(r['deposit_retained']) if r['deposit_retained'] else '—'}</td>"
                 f"<td>{('<a href=/invoice/' + e(r['in_id']) + '.pdf>' + e(inv['number']) + '</a> ' + _m(inv['total'])) if inv else '—'}</td>"
                 f"<td>{who(r['filmed_by'])}</td></tr>")
    hist = (f"<h2>Locations</h2><div style='overflow-x:auto'><table><tr><th>Sortie</th><th>Retour</th><th>Client</th><th>Jours</th>"
            f"<th>Km</th><th>Nouveaux dégâts</th><th>Retenu</th><th>Facture</th><th>Filmé par</th></tr>"
            f"{rows or '<tr><td colspan=9>Aucune location.</td></tr>'}</table></div>")

    dmg = fleet.damages(plate)
    opts = "".join(f'<option value="{d["id"]}">{e(KIND_LABELS[d["kind"]])} · {e(ZONE_LABELS[d["zone"]])} ({e(d["server_time"][:10])})</option>'
                   for d in dmg if not d["repair"])
    dmg_html = "".join(
        f"<li>{e(KIND_LABELS[d['kind']])} · {e(ZONE_LABELS[d['zone']])} · constaté le {e(d['server_time'][:10])} · "
        f"{('réparé le ' + e(d['repair']['day']) + ' (' + _m(d['repair']['cost']) + ')') if d['repair'] else '<b>pas encore réparé</b>'}</li>"
        for d in dmg) or "<li>Aucun dégât constaté au retour.</li>"
    reps = maintenance.repairs(plate)
    rep_rows = "".join(f"<tr><td>{e(r['day'])}</td><td>{e(r['kind'])}</td><td>{e(r['description'] or '')}</td>"
                       f"<td>{_m(r['cost'])}</td><td>{who(r['created_by'])}</td></tr>" for r in reps)
    repairs = f"""<h2>Dégâts constatés</h2><ul>{dmg_html}</ul>
<h2>Réparations et entretien</h2><div style="overflow-x:auto"><table><tr><th>Date</th><th>Type</th><th>Description</th><th>Coût</th><th>Saisi par</th></tr>
{rep_rows or '<tr><td colspan=5>Rien pour l’instant.</td></tr>'}</table></div>
<form method="post" action="/cars/{e(plate)}/repair" class="card"><b>Ajouter une réparation ou une dépense</b>
<div class="row2"><div><label>Date</label><input type="date" name="day" value="{datetime.date.today().isoformat()}" required></div>
<div><label>Coût</label><input type="number" name="cost" min="0" step="0.5" required></div></div>
<div class="row2"><div><label>Type</label><select name="kind"><option>réparation</option><option>entretien</option><option>autre</option></select></div>
<div><label>Dégât réparé (facultatif)</label><select name="mark_id"><option value="">—</option>{opts}</select></div></div>
<label>Description</label><input name="description" required placeholder="Carrosserie porte avant droite, pneus…"><br><br>
<button>Ajouter</button></form>"""

    head = (f"<div class='card'><b>{e(c['name'])}</b> · {e(plate)} · {e(c['category'] or '')} · "
            f"{_m(c['price_day']) + ' / jour' if c['price_day'] else 'prix non saisi'}"
            f"{' · agence ' + e(users.agency_name(c['agency_id'])) if c['agency_id'] else ''} · <a href='/cars'>modifier</a></div>")
    note = f'<div class="card warn">{e(msg)}</div>' if msg else ""
    return page(f"Fiche · {c['name']}", PLAN_CSS + note + head + kpis + docs + hist + repairs)


@router.post("/cars/{plate}/docs")
def car_docs(plate: str, insurance: str = Form(""), inspection: str = Form(""), vignette: str = Form(""),
             oil_every: str = Form(""), user=Depends(staff)):
    try:
        maintenance.set_docs(plate, insurance, inspection, vignette, int(oil_every) if oil_every.strip() else None)
    except ValueError:
        return _back(plate, "Date ou intervalle invalide.")
    return _back(plate, "Dates d’entretien enregistrées.")


@router.post("/cars/{plate}/oil")
def car_oil(plate: str, km: int = Form(...), cost: float = Form(0), user=Depends(staff)):
    if km < 0:
        return _back(plate, "Kilométrage invalide.")
    maintenance.oil_done(plate, km, cost, user["username"])
    return _back(plate, f"Vidange enregistrée à {km} km.")


@router.post("/cars/{plate}/repair")
def car_repair(plate: str, day: str = Form(...), cost: float = Form(...), kind: str = Form("réparation"),
               mark_id: str = Form(""), description: str = Form(...), user=Depends(staff)):
    if kind not in ("réparation", "entretien", "autre") or cost < 0:
        return _back(plate, "Type ou coût invalide.")
    try:
        maintenance.add_repair(plate, description, cost, kind, int(mark_id) if mark_id.isdigit() else None,
                               user["username"], day)
    except ValueError:
        return _back(plate, "Date invalide.")
    return _back(plate, "Dépense ajoutée.")


# ---------- équipe et agences (propriétaire) ----------
@router.get("/users", response_class=HTMLResponse)
def team(request: Request, user=Depends(owner)):
    msg = request.query_params.get("msg")
    ags = users.agencies()
    ag_opts = '<option value="">Toutes les agences</option>' + "".join(f'<option value="{a["id"]}">{e(a["name"])}</option>' for a in ags)
    rows = "".join(
        f"<tr><td>{e(u['name'] or '')}</td><td><code>{e(u['username'])}</code></td><td>{e(users.ROLES.get(u['role'], u['role']))}</td>"
        f"<td>{e(u['agency'] or 'toutes')}</td><td>{'actif' if u['active'] else 'désactivé'}</td>"
        f"<td><form method='post' action='/users/{e(u['username'])}/active'><button name='active' value='{0 if u['active'] else 1}' class='btn grey'>"
        f"{'Désactiver' if u['active'] else 'Réactiver'}</button></form></td></tr>" for u in users.list_users())
    return page("Équipe", PLAN_CSS + (f'<div class="card warn">{e(msg)}</div>' if msg else "") + f"""
<p class="muted">Chaque employé a son identifiant : les contrôles, validations, cautions et réservations indiquent qui les a faits.
Un employé voit les voitures de son agence ; le propriétaire voit tout.</p>
<div style="overflow-x:auto"><table><tr><th>Nom</th><th>Identifiant</th><th>Rôle</th><th>Agence</th><th>État</th><th></th></tr>
{rows or '<tr><td colspan=6>Aucun employé : seul le compte du fichier .env existe.</td></tr>'}</table></div>
<form method="post" action="/users" class="card"><b>Ajouter un employé</b> (ou changer son mot de passe)
<div class="row2"><div><label>Nom</label><input name="name" required></div><div><label>Identifiant</label><input name="username" required placeholder="ahmed"></div></div>
<div class="row2"><div><label>Mot de passe (8 caractères minimum)</label><input name="password" type="password" minlength="8" required autocomplete="new-password"></div>
<div><label>Rôle</label><select name="role"><option value="staff">Employé</option><option value="owner">Propriétaire</option></select></div></div>
<label>Agence</label><select name="agency_id">{ag_opts}</select><br><br><button>Enregistrer</button></form>
<h2>Agences</h2><ul>{''.join(f"<li>{e(a['name'])} · {e(a['address'] or '')} {e(a['phone'] or '')}</li>" for a in ags) or '<li>Une seule agence pour l’instant.</li>'}</ul>
<form method="post" action="/agencies" class="card"><b>Ajouter une agence</b>
<div class="row2"><div><label>Nom</label><input name="name" required placeholder="Agence Sfax"></div><div><label>Téléphone</label><input name="phone"></div></div>
<label>Adresse</label><input name="address"><br><br><button>Ajouter l’agence</button></form>""")


@router.post("/users")
def team_add(name: str = Form(...), username: str = Form(...), password: str = Form(...), role: str = Form("staff"),
             agency_id: str = Form(""), user=Depends(owner)):
    try:
        users.add_user(username, name, password, role, int(agency_id) if agency_id.isdigit() else None)
        msg = f"{name} enregistré."
    except ValueError as err:
        msg = f"Refusé : {err}."
    return RedirectResponse("/users?" + urllib.parse.urlencode({"msg": msg}), 303)


@router.post("/users/{username}/active")
def team_active(username: str, active: int = Form(...), user=Depends(owner)):
    users.set_active(username, bool(active))
    return RedirectResponse("/users", 303)


@router.post("/agencies")
def agency_add(name: str = Form(...), address: str = Form(""), phone: str = Form(""), user=Depends(owner)):
    users.add_agency(name, address, phone)
    return RedirectResponse("/users?msg=" + urllib.parse.quote("Agence ajoutée."), 303)
