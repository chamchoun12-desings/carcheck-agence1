"""Part 04 · The compare: a mark at 'in' that was not at 'out' (same zone, same kind) = NEW."""
from . import db


def compare(out_marks, in_marks):
    seen = {(m["zone"], m["kind"]) for m in out_marks}
    new, before = [], []
    for m in in_marks:
        key = (m["zone"], m["kind"])
        (before if key in seen else new).append(m)
    return new, before


def flag_new(in_check):
    """Run after the AI on an 'in' check. Rejected marks never count on either side."""
    out_marks = db.marks_for(in_check["out_check_id"], include_rejected=False)
    in_marks = db.marks_for(in_check["id"], include_rejected=False)
    new, before = compare(out_marks, in_marks)
    new_ids = {m["id"] for m in new}
    with db.connect() as con:
        for m in in_marks:
            con.execute("UPDATE marks SET is_new=? WHERE id=?", (int(m["id"] in new_ids), m["id"]))
    return new, before


def before_photo(in_check, in_photo: str):
    """Pick the 'out' photo showing the same part of the car.
    Both walk-arounds follow the same route (front -> right -> rear -> left),
    so the same relative position in the video shows the same zone."""
    out = db.get_check(in_check["out_check_id"])
    if not out or not out["n_frames"] or not in_check["n_frames"] or not in_photo:
        return None
    try:
        idx = int(in_photo.split("_")[1].split(".")[0])
    except (IndexError, ValueError):
        return None
    ratio = (idx - 1) / max(in_check["n_frames"] - 1, 1)
    out_idx = round(ratio * (out["n_frames"] - 1)) + 1
    return out["id"], f"f_{out_idx:03d}.jpg"
