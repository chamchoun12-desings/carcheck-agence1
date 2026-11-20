"""Runs after an upload: frames -> AI -> marks table -> compare (for 'in')."""
import json
import traceback

from . import ai, compare, db, frames, intake


def process(check_id):
    c = db.get_check(check_id)
    db.update_check(check_id, status="analyzing")
    try:
        paths = frames.extract(c["dir"])
        db.update_check(check_id, n_frames=len(paths))
        result = ai.analyze(paths)
        c = db.get_check(check_id)
        for m in result["marks"]:
            db.add_mark(c, m)
        db.update_check(check_id, bad_photos=json.dumps(result["bad_photos"]), status="review")
        if c["kind"] == "in":
            compare.flag_new(c)
        read_dashboard(check_id)
    except Exception as e:
        db.update_check(check_id, status="error", error=f"{e}\n{traceback.format_exc()[-800:]}")


def read_dashboard(check_id):
    """L'IA propose km + carburant ; une erreur ici ne bloque jamais le contrôle."""
    c = db.get_check(check_id)
    p = intake.dashboard_path(c)
    if not p:
        return
    try:
        r = ai.read_dashboard(p.read_bytes())
    except Exception as e:
        db.update_check(check_id, error=f"lecture compteur : {e}")
        return
    if db.get_check(check_id)["dash_status"] == "confirmed":
        return                       # déjà vérifié par l'employé dans l'application : on n'écrase pas
    if r and (r["km"] is not None or r["fuel"] is not None):
        db.set_dashboard(check_id, r["km"], r["fuel"], "ai", r["confidence"])
