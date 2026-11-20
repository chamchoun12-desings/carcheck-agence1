"""Part 06 · The monthly: one page for the owner.
Chiffre d'affaires, occupation par voiture, coût des dégâts et cautions, puis quelle voiture se fait toucher, où.
Cron le 1er du mois :  0 8 1 * * cd /opt/carcheck/app && python3 -m carcheck.monthly"""
import html
import time

from . import db, fleet
from .config import AGENCY_NAME, CURRENCY, VAULT
from .zones import KIND_LABELS, ZONE_LABELS

QUERY = """
SELECT car, kind, zone, COUNT(*) AS n
FROM marks
WHERE status = 'confirmed'
  AND kind_of_check = 'in'
  AND is_new = 1
  AND created >= CAST(strftime('%s','now','-30 days') AS REAL)
GROUP BY car, kind, zone
ORDER BY n DESC;
"""


def rows():
    with db.connect() as con:
        return [dict(r) for r in con.execute(QUERY)]


def _m(x):
    return f"{x:,.3f}".replace(",", " ").replace(".", ",") + f" {CURRENCY}"


def render(data, figures=None):
    if figures is None:
        end = time.time()
        figures = fleet.month_figures(end - 30 * 86400, end)
    by_car, by_zone = {}, {}
    for r in data:
        by_car[r["car"]] = by_car.get(r["car"], 0) + r["n"]
        by_zone[r["zone"]] = by_zone.get(r["zone"], 0) + r["n"]
    total = sum(by_car.values())
    e = html.escape
    f = figures

    def bars(d, label=lambda k: k, fmt=str):
        top = max(d.values(), default=1) or 1
        return "".join(
            f'<div class="bar"><span>{e(label(k))}</span><i style="width:{v / top * 100:.0f}%"></i><b>{e(fmt(v))}</b></div>'
            for k, v in sorted(d.items(), key=lambda x: -x[1])) or "<p>Rien ce mois-ci.</p>"

    occ = "".join(
        f"<tr><td>{e(x['car']['name'])} <small>{e(x['car']['plate'])}</small></td>"
        f"<td><div class='occ'><i style='width:{x['occupancy'] * 100:.0f}%'></i></div></td><td>{x['occupancy']:.0%}</td>"
        f"<td>{_m(x['revenue'])}</td><td>{_m(x['costs'])}</td></tr>" for x in f["per_car"])
    table = "".join(
        f"<tr><td>{e(r['car'])}</td><td>{e(KIND_LABELS[r['kind']])}</td>"
        f"<td>{e(ZONE_LABELS[r['zone']])}</td><td>{r['n']}</td></tr>" for r in data)
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Bilan du mois</title>
<style>body{{font-family:system-ui;max-width:860px;margin:24px auto;padding:0 16px;color:#111;background:#fff}}
h1{{margin-bottom:0}}.sub{{color:#666}}.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:16px 0}}
.kpi{{border:1px solid #e5e7eb;border-radius:10px;padding:10px 12px}}.kpi b{{display:block;font-size:1.35rem}}.kpi span{{color:#666;font-size:.85rem}}
.bar{{display:grid;grid-template-columns:170px 1fr 70px;gap:8px;align-items:center;margin:6px 0}}
.bar i{{display:block;height:14px;background:#d9480f;border-radius:3px}}.occ{{background:#eef1f4;border-radius:3px;height:12px;min-width:80px}}
.occ i{{display:block;height:12px;background:#1c4e80;border-radius:3px}}table{{width:100%;border-collapse:collapse}}
td,th{{border-bottom:1px solid #eee;padding:6px;text-align:left}}small{{color:#666}}.wrap{{overflow-x:auto}}</style></head><body>
<h1>{e(AGENCY_NAME)} — bilan 30 jours</h1>
<p class="sub">Généré le {time.strftime('%d/%m/%Y')}</p>
<div class="kpis">
<div class="kpi"><b>{_m(f['revenue'])}</b><span>chiffre d’affaires ({f['invoices']} facture(s))</span></div>
<div class="kpi"><b>{f['rentals']}</b><span>locations terminées · {f['days']} jours</span></div>
<div class="kpi"><b>{f['occupancy']:.0%}</b><span>taux d’occupation moyen</span></div>
<div class="kpi"><b>{_m(f['repairs'])}</b><span>coût des réparations</span></div>
<div class="kpi"><b>{_m(f['upkeep'])}</b><span>entretien (vidanges…)</span></div>
<div class="kpi"><b>{_m(f['retained'])}</b><span>retenu sur cautions (dont dégâts {_m(f['retained_damages'])})</span></div>
</div>
<h2>Occupation et chiffre d’affaires par voiture</h2>
<div class="wrap"><table><tr><th>Voiture</th><th>Occupation</th><th></th><th>CA</th><th>Coûts</th></tr>{occ}</table></div>
<h2>Nouveaux dégâts : voitures les plus touchées ({total})</h2>{bars(by_car)}
<h2>Zones qui reviennent</h2>{bars(by_zone, lambda z: ZONE_LABELS[z])}
<h2>Détail des dégâts</h2><div class="wrap"><table><tr><th>Voiture</th><th>Type</th><th>Zone</th><th>N</th></tr>{table}</table></div>
<p class="sub">Uniquement les marques confirmées par le personnel. Chiffre d’affaires = factures émises sur la période.</p>
</body></html>"""


def main():
    db.init()
    out = VAULT / "monthly"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%Y-%m')}.html"
    path.write_text(render(rows()))
    print(path)


if __name__ == "__main__":
    main()
