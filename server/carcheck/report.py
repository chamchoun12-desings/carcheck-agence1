"""Part 05 · The report: same WhatsApp message to the client AND the agency owner.
Uses a Meta-approved UTILITY template (the agency starts the conversation)."""
import json
import urllib.request

from . import billing, db
from .config import (BASE_URL, OWNER_PHONE, WA_LANG, WA_PHONE_ID, WA_TEMPLATE, WA_TOKEN)
from .zones import KIND_LABELS, KIND_LABELS_AR, ZONE_LABELS, ZONE_LABELS_AR


def _describe(marks, lang="fr"):
    if lang == "ar":
        return "، ".join(f"{KIND_LABELS_AR[m['kind']]} {ZONE_LABELS_AR[m['zone']]}" for m in marks) if marks else "لا شيء"
    if not marks:
        return "aucune"
    return ", ".join(f"{KIND_LABELS[m['kind']]} {ZONE_LABELS[m['zone']].lower()}" for m in marks)


def build(in_check_id, lang="fr"):
    """Only CONFIRMED marks go in the report. The AI never decides alone."""
    c = db.get_check(in_check_id)
    out = db.get_check(c["out_check_id"])
    marks = [m for m in db.marks_for(in_check_id) if m["status"] == "confirmed"]
    new = [m for m in marks if m["is_new"]]
    before = [m for m in marks if not m["is_new"]]
    params = [c["car"], out["server_time"], c["server_time"],
              _describe(new, lang), _describe(before, lang), f"{BASE_URL}/r/{c['share_token']}"]
    return params


def send_template(to_phone, params, template=None, lang=None):
    if not (WA_TOKEN and WA_PHONE_ID):
        return {"skipped": "WA_TOKEN / WA_PHONE_ID not set"}
    body = {
        "messaging_product": "whatsapp", "to": to_phone.lstrip("+"), "type": "template",
        "template": {"name": template or WA_TEMPLATE, "language": {"code": lang or WA_LANG}, "components": [
            {"type": "body", "parameters": [{"type": "text", "text": str(p)[:1000]} for p in params]}]},
    }
    req = urllib.request.Request(
        f"https://graph.facebook.com/v21.0/{WA_PHONE_ID}/messages",
        data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()[:500]}


def send_text(to_phone, body):
    """Message libre : seulement dans les 24 h qui suivent un message du client (règle WhatsApp)."""
    if not (WA_TOKEN and WA_PHONE_ID):
        return {"skipped": "WA_TOKEN / WA_PHONE_ID not set", "text": body}
    payload = {"messaging_product": "whatsapp", "to": to_phone.lstrip("+"), "type": "text",
               "text": {"body": body[:4000]}}
    req = urllib.request.Request(
        f"https://graph.facebook.com/v21.0/{WA_PHONE_ID}/messages",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()[:500]}


def send(in_check_id):
    c = db.get_check(in_check_id)
    pending = [m for m in db.marks_for(in_check_id) if m["status"] == "ai"]
    if pending:
        raise ValueError(f"{len(pending)} mark(s) still waiting for staff confirm/reject")
    s = billing.summary(c)
    if not s["ready"]:
        raise ValueError(s["why"])
    from . import money
    if not money.invoice_for(in_check_id):
        raise ValueError("clôturez d'abord la location (caution et facture)")
    params = build(in_check_id)
    results = {}
    out = db.get_check(c["out_check_id"])
    lang = (out or {}).get("client_lang") or "fr"
    for who, phone, lg in (("client", c["client_phone"], lang), ("owner", OWNER_PHONE, None)):
        p = build(in_check_id, lg or "fr")
        results[who] = send_template(phone, p, None, lg) if phone else {"skipped": "no phone"}
    db.update_check(in_check_id, status="reported")
    from . import intake
    intake.purge_license(c["out_check_id"])           # INPDP : photo du permis supprimée à la clôture
    from . import bookdocs
    bookdocs.purge_for_out(c["out_check_id"])         # et les documents envoyés en réservant
    return {"params": params, "results": results}
