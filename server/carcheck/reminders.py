"""Rappel WhatsApp avant le retour prévu (par défaut 12 h avant), au client ET à l'agence.
Cron toutes les 15 minutes:
*/15 * * * * cd /opt/carcheck/app && /opt/carcheck/venv/bin/python -m carcheck.reminders"""
import time

from . import db, report
from .config import AGENCY_NAME, OWNER_PHONE, REMINDER_HOURS, WA_REMINDER_TEMPLATE

QUERY = """
SELECT * FROM checks c
WHERE kind = 'out'
  AND planned_return_ts IS NOT NULL
  AND COALESCE(reminder_sent, 0) = 0
  AND status NOT IN ('error', 'purged')
  AND ? >= planned_return_ts - ? * 3600     -- on est dans les 12 dernières heures
  AND ? <  planned_return_ts                -- et le retour n'est pas déjà passé
  AND NOT EXISTS (SELECT 1 FROM checks i WHERE i.out_check_id = c.id)
"""


def due(now=None):
    now = time.time() if now is None else now
    with db.connect() as con:
        return [dict(r) for r in con.execute(QUERY, (now, REMINDER_HOURS, now))]


def run(now=None):
    sent = []
    for c in due(now):
        # Modèle WhatsApp "rappel_retour" : {{1}} voiture, {{2}} date de retour, {{3}} agence
        params = [c["car"], c["planned_return"], AGENCY_NAME]
        results = {}
        for who, phone, lang in (("client", c["client_phone"], c["client_lang"] or "fr"), ("owner", OWNER_PHONE, "fr")):
            results[who] = (report.send_template(phone, params, WA_REMINDER_TEMPLATE, lang)
                            if phone else {"skipped": "no phone"})
        db.update_check(c["id"], reminder_sent=1)
        sent.append({"check": c["id"], "car": c["car"], "results": results})
    return sent


def main():
    """Toutes les 15 min : rappels 12 h avant, alertes de retard, résumé d'entretien une fois par jour."""
    from . import extensions, maintenance
    db.init()
    for s in run():
        print("rappel", s)
    for s in extensions.send_late_alerts():
        print("retard", s)
    d = maintenance.send_daily_digest()
    if d:
        print("entretien", d)


if __name__ == "__main__":
    main()
