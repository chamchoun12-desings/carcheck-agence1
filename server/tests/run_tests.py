"""Runs the guide's TEST steps without a real car, AI key or WhatsApp.
python3 tests/run_tests.py"""
import os
import pathlib
import subprocess
import sys
import tempfile

tmp = pathlib.Path(tempfile.mkdtemp())
os.environ["CARCHECK_VAULT"] = str(tmp / "vault")
os.environ["CARCHECK_DB"] = str(tmp / "vault" / "t.db")
os.environ["AI_MODE"] = "mock"
os.environ["STAFF_PASSWORD"] = "test"
os.environ["KM_BILLING"] = "1"      # the tests also cover agencies that charge extra km
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from carcheck import (ai, billing, bookdocs, compare, db, extensions, fleet, intake, maintenance, messages, money,  # noqa: E402
                      monthly, pdf, pipeline, planning, reminders, report, users)
import time  # noqa: E402


def make_video(seconds, color):
    p = tmp / f"{color}{seconds}.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc=duration={seconds}:size=640x360:rate=10", "-vf",
                    f"drawbox=c={color}:t=20", "-pix_fmt", "yuv420p", str(p)], check=True)
    return p.read_bytes()


def ok(cond, msg):
    print(("✓ " if cond else "✗ ") + msg)
    assert cond, msg


db.init()

# 02 · exit video: saved with server time + hash; one changed byte -> different hash
v = make_video(50, "red")
import base64  # noqa: E402
PNG = b"\x89PNG\r\n\x1a\n" + b"sig" * 10
SIG = "data:image/png;base64," + base64.b64encode(PNG).decode()
out = intake.save("123 TU 4567", "out", v, {"lat": 36.8, "lon": 10.18}, "21698000000",
                  signature=SIG, license_bytes=b"\xff\xd8licence", license_expiry="2030-06-30")
ok(out["id"].startswith("out-") and len(out["sha256"]) == 64, f"saved {out['server_time']} {out['sha256'][:12]}")
tampered = bytearray(v); tampered[-1] ^= 1
import hashlib  # noqa: E402
ok(hashlib.sha256(tampered).hexdigest() != out["sha256"], "one byte changed -> hash changes")
ok(intake.verify(out["id"]), "stored file verifies intact")
ok(out["has_signature"] == 1 and intake.file_path(out, "signature.png").read_bytes() == PNG, "client signature saved (web pad data URL)")
ok(intake.file_path(out, "license.jpg") and out["license_expiry"] == "2030-06-30", "licence photo + expiry saved")
ok(intake.license_status(out)[0] == "ok", f"licence status: {intake.license_status(out)[1]}")

# NEW · plate, licence, offline capture
ok(intake.normalize_plate("123 تونس 4567") == "123TU4567", "Arabic تونس plate normalised to TU")
ok(ai.parse_plate('{"plate": "245 تونس 8812", "confidence": 0.9}') == {"plate": "245 TU 8812", "confidence": 0.9}, "AI plate JSON parsed")
ok(ai.parse_plate('{"plate": null}') is None and ai.parse_plate('{"plate": "??"}') is None, "unreadable plate -> staff types it")
ok(intake.read_plate_from_video(v) is None, "mock mode: no plate guessed")
for bad, why in ((dict(license_expiry="2020-01-01"), "expiré"), (dict(phone_sha256="0" * 64), "empreinte"),
                 (dict(signature="data:image/png;base64,AAAA"), "signature")):
    try:
        intake.save("777 TU 7777", "out", make_video(50, "pink"), **bad)
        ok(False, why)
    except intake.Refused as e:
        ok(why in str(e), f"refused: {e}")
import hashlib  # noqa: E402
vo = make_video(50, "navy")
off = intake.save("777 TU 7777", "out", vo, recorded_at=str(time.time() - 3 * 3600),
                  phone_sha256=hashlib.sha256(vo).hexdigest())
ok(off["recorded_at"] and off["phone_sha256"] == off["sha256"], "offline video: phone time kept, phone hash matches")
db.update_check(off["id"], status="error")              # keep the rest of the tests independent

# Known problem: rushed walk-around
try:
    intake.save("123 TU 4567", "out", make_video(20, "blue"))
    ok(False, "short video refused")
except intake.Refused as e:
    ok("trop courte" in str(e), f"short video refused: {e}")

# 03 · frames 1/s
pipeline.process(out["id"])
out = db.get_check(out["id"])
ok(out["status"] == "review" and out["n_frames"] == 50, f"{out['n_frames']} frames extracted")

# 03 · AI JSON parsing + merging (same zone+kind across photos = one mark)
parsed = ai.parse('blah {"marks":[{"zone":"rear_left_door","kind":"scratch","size":"small","photo":2,"confidence":0.8},'
                  '{"zone":"moon","kind":"scratch","size":"small","photo":1,"confidence":0.9}],"bad_photos":[5]} end')
ok(len(parsed["marks"]) == 1 and parsed["bad_photos"] == [5], "invalid zone dropped, bad photo kept")
merged = ai.merge([
    {"zone": "bonnet", "kind": "dent", "size": "small", "photo": "f_003.jpg", "confidence": 0.6},
    {"zone": "bonnet", "kind": "dent", "size": "medium", "photo": "f_004.jpg", "confidence": 0.9},
    {"zone": "boot", "kind": "scratch", "size": "small", "photo": "f_030.jpg", "confidence": 0.7}])
ok(len(merged) == 2 and merged[0]["size"] == "medium" and merged[0]["photo"] == "f_004.jpg", "merge works")

# Car leaves with 3 known marks (staff-confirmed)
for z, k in [("bonnet", "dent"), ("rear_bumper", "scratch"), ("wheels", "wheel")]:
    db.add_mark(out, {"zone": z, "kind": k, "size": "small", "photo": "f_010.jpg", "photos": []}, "staff", "confirmed")

# NEW · rental duration is required before the return
try:
    intake.save("123TU4567", "in", make_video(55, "yellow"))
    ok(False, "return refused without rental")
except intake.Refused as e:
    ok("durée de location" in str(e), f"return refused without rental: {e}")
ret_ts = out["created"] + 3 * 86400
db.set_rental(out["id"], 3, ret_ts)
out = db.get_check(out["id"])
ok(out["planned_return"] and out["reminder_sent"] == 0, f"rental saved: 3 days, return {out['planned_return']}")

# NEW · WhatsApp reminder 12 h before the planned return, sent once
ok(reminders.due(now=ret_ts - 13 * 3600) == [], "no reminder 13 h before")
ok(len(reminders.due(now=ret_ts - 11 * 3600)) == 1, "reminder due 11 h before")
sent = reminders.run(now=ret_ts - 11 * 3600)
ok(sent and sent[0]["results"]["client"].get("skipped"), "reminder sent (skipped cleanly without token)")
ok(reminders.due(now=ret_ts - 10 * 3600) == [], "reminder not sent twice")
db.set_rental(out["id"], 4, ret_ts + 86400)          # extension re-arms the reminder
ok(len(reminders.due(now=ret_ts + 86400 - 6 * 3600)) == 1, "extension re-arms the reminder")
ok(reminders.due(now=ret_ts + 86400 + 60) == [], "no reminder after the return time")
db.update_check(out["id"], reminder_sent=1)

# 04 · compare: same car back with no new damage -> 0 NEW
back = intake.save("123TU4567", "in", make_video(55, "green"))
ok(back["out_check_id"] == out["id"] and back["client_phone"] == "21698000000", "in linked to out")
pipeline.process(back["id"])
back = db.get_check(back["id"])
for z, k in [("bonnet", "dent"), ("rear_bumper", "scratch"), ("wheels", "wheel")]:
    db.add_mark(back, {"zone": z, "kind": k, "size": "small", "photo": "f_010.jpg", "photos": []}, "staff", "confirmed")
new, before = compare.flag_new(back)
ok(len(new) == 0 and len(before) == 3, "no new damage -> 0 NEW")

# red sticker on a door -> 1 NEW in the right zone
db.add_mark(back, {"zone": "front_right_door", "kind": "scratch", "size": "medium", "photo": "f_020.jpg", "photos": []})
new, _ = compare.flag_new(back)
ok(len(new) == 1 and new[0]["zone"] == "front_right_door", "sticker -> 1 NEW, front_right_door")
ok(compare.before_photo(back, "f_020.jpg") == (out["id"], "f_018.jpg"), "before photo picked at same position")

# 05 · report blocked while a mark is undecided, then built from confirmed marks only
try:
    report.send(back["id"]); ok(False, "blocked")
except ValueError as e:
    ok(True, f"report blocked: {e}")
db.set_mark_status(new[0]["id"], "confirmed")

# NEW · compteur : lecture IA (JSON), photo enregistrée avec empreinte, calcul km + carburant
d = ai.parse_dashboard('ok {"km": 46210, "fuel_eighths": 3, "confidence": 0.92}')
ok((d["km"], d["fuel"], d["confidence"], d["unit"]) == (46210, 0.375, 0.92, "km"), f"dashboard JSON parsed: {d}")
d = ai.parse_dashboard('{"km": 10000, "unit": "mi", "fuel_eighths": 8, "dash_type": "screen", "confidence": 0.9}')
ok(d["km"] == 16093 and d["unit"] == "mi" and d["dash_type"] == "screen", f"miles converted to km: {d}")
d = ai.parse_dashboard('{"km": null, "fuel_eighths": 4, "dash_type": "analog", "problem": "odo_hidden"}')
ok(d["km"] is None and d["fuel"] == 0.5 and d["problem"] == "odo_hidden", f"hidden odometer flagged: {d}")
ok(ai.parse_dashboard('{"km": "illisible", "fuel_eighths": 12}')["km"] is None, "bad dashboard values ignored")
intake.save_dashboard(back["id"], b"\xff\xd8fake-jpeg")
pipeline.read_dashboard(back["id"])                       # mock: nothing proposed, staff types it
back = db.get_check(back["id"])
ok(intake.dashboard_path(back) and len(back["dash_sha256"]) == 64 and back["km"] is None,
   "dashboard photo saved with hash, mock leaves values to staff")
try:
    report.send(back["id"]); ok(False, "blocked without dashboard")
except ValueError as e:
    ok("compteur" in str(e), f"report blocked until dashboard confirmed: {e}")
db.set_dashboard(out["id"], 45000, 6 / 8)                 # sortie : 45 000 km, 6/8
db.set_dashboard(back["id"], 44000, 3 / 8)                # erreur de saisie
ok(not billing.summary(db.get_check(back["id"]))["ready"], "km lower at return is refused")
db.set_dashboard(back["id"], 46100, 4 / 8)                # retour : 1 100 km, 4/8
s = billing.summary(db.get_check(back["id"]))
# 4 jours x 250 km = 1 000 inclus -> 100 km x 0,2 = 20 ; 2/8 x 45 L = 11,25 L x 2,5 + 10 = 38,125
ok(s["distance"] == 1100 and s["extra_km"] == 100 and s["km_cost"] == 20.0, f"km: {s['distance']} km, +{s['extra_km']} km = {s['km_cost']}")
ok(s["fuel_missing_liters"] == 11.25 and s["fuel_cost"] == 38.125 and s["total"] == 58.125, f"fuel: {s['fuel_missing_liters']} L = {s['fuel_cost']}, total {s['total']}")
print("  " + " | ".join(billing.lines(s)))
db.set_rental(out["id"], 4, ret_ts + 86400, 0)            # km illimités
ok(billing.summary(db.get_check(back["id"]))["extra_km"] == 0, "unlimited km -> no extra")
billing.KM_BILLING = False                                # agence sans frais de km : km notés seulement
db.set_rental(out["id"], 4, ret_ts + 86400)
s2 = billing.summary(db.get_check(back["id"]))
ok(s2["km_cost"] == 0 and s2["total"] == 38.125 and billing.lines(s2)[0].startswith("Kilométrage : 1 100 km"),
   "km billing off: km kept as data, only fuel charged -> " + " | ".join(billing.lines(s2)))
billing.KM_BILLING = True
db.update_check(out["id"], reminder_sent=1)

# NEW · argent : caution, clôture, facture
try:
    report.send(back["id"]); ok(False, "report needs closing")
except ValueError as e:
    ok("clôturez" in str(e), f"report waits for closing: {e}")
money.take_deposit(out["id"], 500, "espèces", by="ahmed")
db.update_check(out["id"], client_name="Sami Ben Ali", rental_price=360)
inv = money.settle(back["id"], damages=120, other=0, note="rayure porte avant droite", by="ahmed")
o = db.get_check(out["id"])
ok(inv["number"].startswith("F") and inv["number"].endswith("-0001"), f"invoice number {inv['number']}")
# carburant 38,125 + km 20 + dégâts 120 = 178,125 retenus sur 500 -> 321,875 rendus ; total = 360 + 178,125
ok(o["deposit_retained"] == 178.125 and o["deposit_status"] == "partly_retained", f"deposit: retained {o['deposit_retained']}")
d = money.invoice_data(back["id"])
ok(d["total"] == 538.125 and d["returned"] == 321.875 and d["still_due"] == 0, f"invoice total {d['total']}, returned {d['returned']}")
pdfb = pdf.invoice_pdf(d, {"name": "Mon Agence", "address": "Tunis", "phone": "71000000", "tax_id": "1234567/A"})
ok(pdfb.startswith(b"%PDF-1.4") and pdfb.rstrip().endswith(b"%%EOF") and b"Sami Ben Ali" in pdfb and b"F20" in pdfb,
   f"PDF invoice generated ({len(pdfb)} bytes)")
(tmp / "facture.pdf").write_bytes(pdfb)
try:
    money.settle(back["id"]); ok(False, "double close")
except money.MoneyError as e:
    ok(True, f"cannot close twice: {e}")
res = report.send(back["id"])
ok("Rayure porte avant droite" in res["params"][3], f"report params: {res['params'][3]} | {res['params'][4]}")
ok(res["results"]["client"].get("skipped"), "WhatsApp skipped cleanly without token")
ok(intake.file_path(db.get_check(out["id"]), "license.jpg") is None and db.get_check(out["id"])["license_expiry"],
   "INPDP: licence photo deleted when the rental closes, expiry date kept")

# 06 · monthly counts only confirmed NEW marks at return
rows = monthly.rows()
ok(len(rows) == 1 and rows[0]["zone"] == "front_right_door", f"monthly: {rows}")
html = monthly.render(rows)
ok("Porte avant droite" in html, "monthly page renders")

# NEW · planning : flotte, réservations client, anti double location
ok(planning.get_car("123TU4567") and not planning.get_car("123TU4567")["public"], "car registered automatically (hidden from clients)")
planning.upsert_car("200TU1111", "Peugeot 208", "citadine", 90, "manuelle", 5)
planning.upsert_car("201TU2222", "Kia Picanto", "citadine", 80, "manuelle", 5)
t0 = time.time() + 2 * 86400
t1 = t0 + 3 * 86400
ok(len(planning.available(t0, t1, public_only=True)) == 2, "2 cars free for the client")
r1 = planning.create_reservation("200TU1111", "Sami", "+216 98 111 222", t0, t1)
ok(r1["status"] == "pending" and r1["client_phone"] == "21698111222", "client booking arrives as pending")
ok([c["plate"] for c in planning.available(t0, t1, public_only=True)] == ["201TU2222"], "pending booking blocks the car")
try:
    planning.create_reservation("200TU1111", "Ali", "21655000000", t0 + 86400, t1 + 86400)
    ok(False, "overlap refused")
except planning.Conflict as e:
    ok("déjà prise" in str(e), f"overlapping booking refused: {e}")
r2 = planning.create_reservation("200TU1111", "Ali", "21655000000", t1 + 3 * 3600, t1 + 2 * 86400)
ok(r2["status"] == "pending", "booking right after (with 2 h preparation) accepted")
try:
    planning.create_reservation("123TU4567", "Ali", "21655000000", t0, t1)
    ok(False, "hidden car")
except planning.Conflict as e:
    ok(True, f"hidden car not bookable online: {e}")
ok(planning.set_status(r1["id"], "confirmed")["status"] == "confirmed", "agency confirms")

o2 = intake.save("200 TU 1111", "out", make_video(50, "purple"), None, "21677000000")
try:
    planning.convert_for_rental(o2, o2["created"] + 5 * 86400)
    ok(False, "double rental")
except planning.Conflict as e:
    ok("double location" in str(e), f"5-day rental over Sami's booking refused: {e}")
planning.convert_for_rental(o2, o2["created"] + 86400)
db.set_rental(o2["id"], 1, o2["created"] + 86400)
ok(True, "1-day rental before Sami's booking accepted")
try:
    intake.save("200TU1111", "out", make_video(50, "orange"))
    ok(False, "second exit")
except intake.Refused as e:
    ok("déjà sortie" in str(e), f"second exit of the same car refused: {e}")
rows = {r["car"]["plate"]: [c["state"] for c in r["cells"]] for r in planning.grid(time.time() - 3600, 7)}
ok(rows["200TU1111"][0] == "rented" and "reserved" in rows["200TU1111"] and "pending" in rows["200TU1111"], f"grid 200TU1111: {rows['200TU1111']}")
ok(set(rows["201TU2222"]) == {"free"}, "grid: Picanto free all week")
tdy = planning.today()
ok([c["plate"] for c in tdy["rented"]] == ["200TU1111"], "today: 1 car out")
# the client who booked comes to take the car: his booking becomes the rental
r3 = planning.create_reservation("201TU2222", "Mouna", "21622333444", time.time() + 600, time.time() + 2 * 86400, source="staff")
ok(r3["status"] == "confirmed", "phone booking by staff is confirmed directly")
o3 = intake.save("201TU2222", "out", make_video(50, "cyan"), None, "+216 22 333 444")
planning.convert_for_rental(o3, time.time() + 2 * 86400)
ok(planning.get_reservation(r3["id"])["status"] == "converted", "client's own booking becomes the rental")


# NEW · documents envoyés en réservant : CIN/passeport + permis, contrôles, suppression
import datetime as _dt  # noqa: E402
JPG = b"\xff\xd8\xff\xe0" + b"photo" * 50
far0 = time.time() + 40 * 86400
far1 = far0 + 3 * 86400
in_ = lambda days: (_dt.date.today() + _dt.timedelta(days=days)).isoformat()
docs = {"id_front": JPG, "id_back": JPG, "license_front": JPG, "license_back": b""}
for bad, args, why in (
        ({**docs, "id_back": b""}, ("cin", "", in_(800)), "verso"),
        (docs, ("cin", "", in_(41)), "permis n’est plus valable"),
        (docs, ("passport", "", in_(800)), "passeport"),
        (docs, ("passport", in_(42), in_(800)), "pièce d’identité n’est plus valable"),
        ({**docs, "id_front": b"MZ\x90\x00exe"}, ("cin", "", in_(800)), "photo"),
        ({**docs, "license_front": JPG * 50000}, ("cin", "", in_(800)), "trop lourd")):
    try:
        bookdocs.validate(bad, *args, far1)
        ok(False, why)
    except bookdocs.DocError as e:
        ok(why in str(e), f"documents refused: {e}")
dates = bookdocs.validate(docs, "cin", "", in_(800), far1)
planning.upsert_car("202TU2020", "Seat Ibiza", "citadine", 85)
rb = planning.create_reservation("202TU2020", "Nour", "21622000111", far0, far1)
bookdocs.save(rb["id"], docs, "cin", dates)
rb = planning.get_reservation(rb["id"])
ok(rb["docs_status"] == "received" and set(bookdocs.files_of(rb["id"])) == {"id_front", "id_back", "license_front"},
   "CIN recto/verso + permis saved privately")
ok(all(p.suffix == ".jpg" for p in bookdocs.files_of(rb["id"]).values()), "file type decided from content, not from the name")
planning.set_status(rb["id"], "refused", by="ahmed")
ok(bookdocs.files_of(rb["id"]) == {} and planning.get_reservation(rb["id"])["docs_purged_at"], "refused booking: documents deleted at once")
rc = planning.create_reservation("202TU2020", "Nour", "21622000111", far0, far1)
bookdocs.save(rc["id"], docs, "cin", dates)
bookdocs.check(rc["id"], False, "permis flou", by="ahmed")
ok(planning.get_reservation(rc["id"])["docs_status"] == "rejected", "staff can ask to send them again")
bookdocs.save(rc["id"], docs, "cin", dates)
planning.set_status(rc["id"], "confirmed", by="ahmed")
rc = planning.get_reservation(rc["id"])
ok(rc["docs_status"] == "verified" and rc["docs_checked_by"] == "ahmed", "confirming the booking = documents checked, by whom")
ok(bookdocs.purge_expired(now=far1 + 31 * 86400) == [rc["id"]] and not bookdocs.files_of(rc["id"]),
   "kept at most 30 days after the end, then deleted")
planning.upsert_car("203TU3030", "Fiat Tipo", "berline", 95)
rd = planning.create_reservation("203TU3030", "Yassine", "21633000222", time.time() + 600, time.time() + 2 * 86400)
bookdocs.save(rd["id"], docs, "cin", bookdocs.validate(docs, "cin", "", in_(800), rd["end_ts"]))
o7 = intake.save("203TU3030", "out", make_video(50, "gold"), None, "+216 33 000 222")
planning.convert_for_rental(o7, time.time() + 2 * 86400)
ok(db.get_check(o7["id"])["license_expiry"] == in_(800), "licence date sent with the booking goes to the exit check")
ok(bookdocs.purge_for_out(o7["id"]) == [rd["id"]] and not bookdocs.files_of(rd["id"]), "closing the rental deletes the booking documents")

# NEW · comptes : employés, agences, traçabilité
ag = users.add_agency("Agence Tunis Centre", "Av. Habib Bourguiba", "71000000")
users.add_user("Ahmed", "Ahmed K.", "motdepasse1", "staff", ag)
ok(users.authenticate("ahmed", "motdepasse1")["agency_id"] == ag, "employee logs in with his own account")
ok(users.authenticate("ahmed", "mauvais") is None, "wrong password refused")
ok(users.authenticate("staff", "test")["role"] == "owner", ".env account is the owner")
try:
    users.add_user("x y", "X", "motdepasse1"); ok(False, "bad username")
except ValueError as e:
    ok(True, f"bad username refused: {e}")
users.set_active("ahmed", False)
ok(users.authenticate("ahmed", "motdepasse1") is None, "deactivated employee cannot log in")
users.set_active("ahmed", True)
ok(db.get_check(out["id"])["deposit_by"] == "ahmed" and users.display("ahmed") == "Ahmed K.", "who took the deposit is recorded")

# NEW · pendant la location : prolongation WhatsApp, retard, langues
ok(extensions.parse("prolonger 2 jours") == 2 and extensions.parse("Bonjour, je voudrais prolonger de trois jours") == 3,
   "French extension parsed")
ok(extensions.parse("تمديد يومين") == 2 and extensions.parse("نحب نمدد ٣ أيام") == 3, "Arabic extension parsed (words and Arabic digits)")
ok(extensions.parse("prolonger") == 0 and extensions.parse("merci, à demain") is None, "no number -> help, other text ignored")
planning.upsert_car("600TU6666", "Renault Clio", "citadine", 85)
o6 = intake.save("600 TU 6666", "out", make_video(50, "brown"), None, "+216 97 123 456",
                 client_name="Leila M.", client_lang="ar", by="ahmed", agency_id=ag)
ok(o6["client_lang"] == "ar" and o6["filmed_by"] == "ahmed" and o6["agency_id"] == ag, "client language, who filmed, agency saved")
db.set_rental(o6["id"], 2, o6["created"] + 2 * 86400, by="ahmed")
r = extensions.handle_incoming("21697123456", "تمديد يومين")
ok(r["action"] == "pending" and r["days"] == 2, "WhatsApp reply creates an extension request")
ok(extensions.handle_incoming("21600000000", "prolonger 2 jours")["action"] == "no_rental", "unknown number ignored")
pend = extensions.pending()
ok(len(pend) == 1 and pend[0]["client_lang"] == "ar", "request waits for the staff (Arabic client)")
res_x = extensions.decide(pend[0]["id"], True, by="ahmed")
o6 = db.get_check(o6["id"])
ok(res_x["status"] == "approved" and o6["rental_days"] == 4 and abs(o6["planned_return_ts"] - (o6["created"] + 4 * 86400)) < 1,
   "one click: rental extended by 2 days")
ok(o6["rental_price"] == 340 and "تمديد" in res_x["message"], f"price updated (4 × 85), Arabic confirmation: {res_x['message'][:40]}…")
planning.create_reservation("600TU6666", "Hedi", "21611111111", o6["planned_return_ts"] + 3 * 3600, o6["planned_return_ts"] + 3 * 86400)
extensions.handle_incoming("+216 97 123 456", "prolonger 2 jours")
res_y = extensions.decide(extensions.pending()[0]["id"], True, by="ahmed")
ok(res_y["status"] == "refused" and res_y["reason"] == "reason_booked", "extension refused automatically: car booked afterwards")
ok([c for c in extensions.late_due(now=o6["planned_return_ts"] + 1800) if c["car"] == "600TU6666"] == [], "not late yet within the grace period")
late = [x for x in extensions.send_late_alerts(now=o6["planned_return_ts"] + 2 * 3600) if x["car"] == "600TU6666"]
ok(len(late) == 1 and late[0]["results"]["client"].get("skipped"), "late: agency + client alerted (skipped cleanly without token)")
ok([x for x in extensions.send_late_alerts(now=o6["planned_return_ts"] + 5 * 3600) if x["car"] == "600TU6666"] == [], "late alert sent once")
ok(messages.t("ar", "ext_help").startswith("لتمديد") and messages.t("xx", "ext_help").startswith("Pour"), "Arabic and French texts")
pa = report.build(back["id"], "ar")
ok("خدش الباب الأمامي الأيمن" in pa[3] and "انبعاج غطاء المحرّك" in pa[4], f"Arabic report message: {pa[3]}")

# NEW · flotte : entretien, réparations, fiche voiture
import datetime  # noqa: E402
today = datetime.date.today()
maintenance.set_docs("600TU6666", insurance=(today + datetime.timedelta(days=200)).isoformat(),
                     inspection=(today + datetime.timedelta(days=10)).isoformat(),
                     vignette=(today + datetime.timedelta(days=90)).isoformat(), oil_every=10000)
maintenance.oil_done("600TU6666", 30000, 120, by="ahmed")
db.set_dashboard(o6["id"], 39700, 0.5)
al = {a["kind"]: a for a in maintenance.alerts(planning.get_car("600TU6666"))}
ok(al["oil"]["level"] == "soon" and "300 km" in al["oil"]["text"], f"oil change warning: {al['oil']['text']}")
ok(al["inspection_until"]["level"] == "soon" and "insurance_until" not in al, "inspection expiring soon, insurance fine")
maintenance.set_docs("201TU2222", insurance=(today - datetime.timedelta(days=1)).isoformat())
ok("Assurance expirée" in (maintenance.blocking("201TU2222") or ""), "expired insurance blocks the car")
maintenance.add_repair("123TU4567", "Peinture porte avant droite", 180, mark_id=new[0]["id"], by="ahmed")
dm = fleet.damages("123TU4567")
ok(dm and dm[0]["repair"]["cost"] == 180, "damage linked to its repair")
tt = fleet.totals("123TU4567")
ok(tt["revenue"] == 538.125 and tt["repairs"] == 180 and tt["margin"] == 358.125, f"car totals: {tt}")
d0 = maintenance.send_daily_digest(now=time.mktime(time.localtime()[:3] + (9, 0, 0, 0, 0, -1)))
ok(d0 and d0["sent"] and any("600TU6666" in i for i in d0["items"]), "daily maintenance message to the owner")
ok(maintenance.send_daily_digest(now=time.mktime(time.localtime()[:3] + (10, 0, 0, 0, 0, -1))) is None, "sent once a day")

# NEW · bilan enrichi
fig = fleet.month_figures(time.time() - 30 * 86400, time.time() + 60)
ok(fig["revenue"] == 538.125 and fig["repairs"] == 180 and fig["retained_damages"] == 120, f"monthly: CA {fig['revenue']}, réparations {fig['repairs']}")
occ = {x["car"]["plate"]: x["occupancy"] for x in fig["per_car"]}
ok(occ["600TU6666"] > 0 and all(0 <= v <= 1 for v in occ.values()), "occupancy per car between 0 and 100 %")
ok("chiffre d’affaires" in monthly.render(monthly.rows(), fig) and "Occupation" in monthly.render(monthly.rows(), fig), "monthly page renders")

# WEB · the real pages, with FastAPI's test client (installed automatically on GitHub)
import importlib.util  # noqa: E402
if not importlib.util.find_spec("fastapi") and os.environ.get("CI"):
    base = [sys.executable, "-m", "pip", "install", "-q", "fastapi", "httpx", "python-multipart"]
    if subprocess.run(base + ["--break-system-packages"]).returncode != 0:
        subprocess.run(base, check=True)
if importlib.util.find_spec("fastapi") and importlib.util.find_spec("httpx"):
    from fastapi.testclient import TestClient
    from carcheck.app import app
    cl = TestClient(app)
    auth = ("staff", "test")
    ok(cl.get("/planning").status_code == 401, "web: staff pages need the login")
    for path in ("/", "/planning", "/cars", "/checks", "/monthly"):
        r = cl.get(path, auth=auth)
        ok(r.status_code == 200, f"web: {path} -> {r.status_code}")
    far = time.time() + 30 * 86400
    fmt = lambda ts: time.strftime("%Y-%m-%dT%H:%M", time.localtime(ts))
    day = lambda d: (_dt.date.today() + _dt.timedelta(days=d)).isoformat()  # noqa: E731
    ok("<title>" in cl.get("/reserver").text, "web: client booking page (separate from the agency app)")
    r = cl.get("/api/public/cars", params={"start": day(30), "end": day(32)})
    ok(r.status_code == 200 and any(c["name"] == "Peugeot 208" for c in r.json()["cars"])
       and "price" not in str(r.json()["cars"]), "web: client sees free cars, without prices")
    r = cl.post("/reserver/200TU1111", data={"start": fmt(far), "end": fmt(far + 2 * 86400), "name": "Web Test",
                                             "phone": "+216 50 123 456"}, follow_redirects=False)
    ok(r.status_code == 200 and "document" in r.text, "web: booking without documents refused with a clear message")
    bd = {"start": fmt(far), "end": fmt(far + 2 * 86400), "name": "Web Test", "phone": "+216 50 123 456",
          "id_type": "cin", "license_expiry": in_(900), "consent": "1"}
    bf = {"id_front": ("cin1.jpg", JPG, "image/jpeg"), "id_back": ("cin2.jpg", JPG, "image/jpeg"),
          "license_front": ("permis.jpg", JPG, "image/jpeg")}
    r = cl.post("/reserver/200TU1111", data=bd, files=bf, follow_redirects=False)
    ok(r.status_code == 303 and r.headers["location"].startswith("/reservation/"), "web: client books online with CIN + permis")
    rid_web = planning.get_reservation(token=r.headers["location"].rsplit("/", 1)[1])["id"]
    ok(cl.get(f"/bookdocs/{rid_web}/id_front").status_code == 401, "web: documents never reachable without staff login")
    ok(cl.get(f"/bookdocs/{rid_web}/id_front", auth=auth).content == JPG, "web: staff can open the documents")
    ok("CIN" in cl.get(f"/reservations/{rid_web}/docs", auth=auth).text, "web: staff documents page")
    tok_web = r.headers["location"].rsplit("/", 1)[1]
    ok(cl.get(f"/api/public/res/{tok_web}").json()["status"] == "pending", "web: client follows the request")
    ok("suivi=" in cl.get(f"/reservation/{tok_web}", follow_redirects=False).headers["location"],
       "web: old status links lead to the new client page")
    r = cl.post("/upload", auth=auth, data={"car": "400 TU 4", "kind": "out", "client_phone": "21698000000"},
                files={"video": ("walk.mp4", make_video(50, "white"), "video/mp4"),
                       "dash": ("compteur.jpg", b"\xff\xd8web", "image/jpeg")})
    ok(r.status_code == 200 and "Enregistré" in r.text, "web: upload video + dashboard photo")
    cid = r.text.split("/check/")[1].split('"')[0]
    r = cl.get(f"/check/{cid}", auth=auth)
    ok(r.status_code == 200 and "Compteur" in r.text and "Obligatoire" in r.text, "web: exit check page")
    r = cl.post(f"/check/{cid}/dash", auth=auth, data={"km": "12000", "fuel": "8"}, follow_redirects=False)
    ok(r.status_code == 303, "web: confirm dashboard")
    vid2 = make_video(50, "olive")
    r = cl.post("/api/upload", auth=auth, data={"car": "", "kind": "out"}, files={"video": ("w.mp4", vid2, "video/mp4")})
    ok(r.status_code == 422 and "plaque" in r.json()["error"], "web API: unreadable plate -> clear error for the app")
    r = cl.post("/api/upload", auth=auth,
                data={"car": "500 TU 5", "kind": "out", "client_phone": "21698000000", "license_expiry": "2031-01-01",
                      "recorded_at": str(time.time() - 600), "phone_sha256": hashlib.sha256(vid2).hexdigest()},
                files={"video": ("w.mp4", vid2, "video/mp4"), "signature": ("s.png", PNG, "image/png"),
                       "license": ("l.jpg", b"\xff\xd8lic", "image/jpeg"), "dash": ("d.jpg", b"\xff\xd8d", "image/jpeg")})
    ok(r.status_code == 200 and r.json()["ok"], f"web API: offline upload accepted {r.json()}")
    api_id = r.json()["check_id"]
    r = cl.get(f"/check/{api_id}", auth=auth)
    ok("Filmé hors ligne" in r.text and "Signature du client" in r.text and "2031" in r.text, "web: offline info, signature, licence shown to staff")
    tok = db.get_check(back["id"])["share_token"]
    ok(cl.get(f"/r/{tok}/media/{out['id']}/license.jpg").status_code == 404, "web: licence never reachable from the client link")
    for path in ("/users", "/cars/123TU4567", "/cars/600TU6666"):
        r = cl.get(path, auth=auth)
        ok(r.status_code == 200, f"web: {path} -> {r.status_code}")
    r = cl.get(f"/invoice/{back['id']}.pdf", auth=auth)
    ok(r.status_code == 200 and r.content.startswith(b"%PDF"), "web: invoice PDF for staff")
    ok(cl.get(f"/r/{tok}/facture.pdf").content.startswith(b"%PDF"), "web: invoice PDF on the client link")
    ahmed = ("ahmed", "motdepasse1")
    ok(cl.get("/planning", auth=ahmed).status_code == 200 and cl.get("/users", auth=ahmed).status_code == 403,
       "web: employee sees the planning, not the team page")
    r = cl.post("/webhook", json={"entry": [{"changes": [{"value": {"messages": [
        {"from": "21697123456", "type": "text", "text": {"body": "prolonger 1 jour"}}]}}]}]})
    ok(r.status_code == 200 and extensions.pending(), "web: WhatsApp webhook turns « prolonger 1 jour » into a request")

    # NOUVELLE APPLICATION AGENCE · API JSON utilisée par l'application (navigateur et Android)
    st = cl.get("/api/a/state", auth=auth).json()
    ok(st["ok"] and st["me"]["role"] == "owner" and st["cars"] and len(st["cars"][0]["days"]) == 7,
       "app: state for home, planning and cars")
    r = cl.post("/api/a/cars", auth=auth, data={"plate": "888 TU 8888", "name": "Kia Rio", "km": "12000", "dt": "1",
                                                "category": "citadine", "oil_next": "20000", "ins": day(300),
                                                "vis": day(200), "vig": day(100)})
    ok(r.json()["ok"] and r.json()["car"]["km"] == 12000 and r.json()["car"]["oil"]["left"] == 8000
       and r.json()["car"]["lvl"] == 0, f"app: owner adds a car {r.json()}")
    ok(cl.post("/api/a/cars", auth=ahmed, data={"plate": "778 TU 1", "name": "X"}).status_code == 403,
       "app: employees cannot add cars")
    ok(cl.post("/api/a/cars", auth=auth, data={"plate": "888 TU 8888", "name": "Kia Rio"}).status_code == 422,
       "app: same plate refused")
    r = cl.post("/api/public/book", data={"car": "888TU8888", "start": day(40), "end": day(43), "name": "Salma R.",
                                          "phone": "+216 55 444 333", "lang": "ar", "id_type": "cin",
                                          "license_expiry": day(900), "consent": "1"}, files=bf)
    ok(r.json()["ok"], f"app: client sends a request with documents {r.json()}")
    tok2 = r.json()["token"]
    pub = cl.get(f"/api/public/res/{tok2}").json()
    ok(pub["status"] == "pending" and pub["price_day"] is None, "app: request waits, no price yet")
    rq = cl.get("/api/a/requests", auth=ahmed).json()
    one = [x for x in rq["res"] if x["name"] == "Salma R."][0]
    ok(set(one["docs"]) == {"id_front", "id_back", "license_front"}, "app: staff sees the client's documents")
    ok(cl.post(f"/api/a/requests/res/{one['id']}", auth=ahmed, data={"ok": "1"}).status_code == 422,
       "app: accepting needs the price per day")
    ok(cl.post(f"/api/a/requests/res/{one['id']}", auth=ahmed, data={"ok": "1", "price_day": "150"}).json()["total"] == 450,
       "app: accepted at 3 x 150")
    pub = cl.get(f"/api/public/res/{tok2}").json()
    ok(pub["status"] == "confirmed" and pub["total"] == 450, "app: client sees the price once accepted")
    ok(cl.post("/api/a/dash-read", auth=ahmed, files={"photo": ("d.jpg", JPG, "image/jpeg")}).json()["read"] is None,
       "app: dashboard reading (mock: nothing, staff types it)")
    vid3 = make_video(50, "teal")
    out_form = {"kind": "out", "car": "888 TU 8888", "client_name": "Salma R.", "client_phone": "21655444333",
                "client_lang": "ar", "license_expiry": day(900), "km": "12050", "fuel8": "8", "days": "3",
                "price_day": "150", "deposit": "400", "pay": "cash", "phone_sha256": hashlib.sha256(vid3).hexdigest()}
    r = cl.post("/api/a/checks", auth=ahmed, data={**out_form, "price_day": ""}, files={"video": ("w.mp4", vid3, "video/mp4")})
    ok(r.status_code == 422 and "prix" in r.json()["error"], "app: exit refused without the price")
    r = cl.post("/api/a/checks", auth=ahmed, data={**out_form, "license_expiry": day(1)},
                files={"video": ("w.mp4", vid3, "video/mp4")})
    ok(r.status_code == 422 and "permis" in r.json()["error"], "app: licence expiring before the return refused")
    r = cl.post("/api/a/checks", auth=ahmed, data=out_form, files={
        "video": ("w.mp4", vid3, "video/mp4"), "dash": ("d.jpg", JPG, "image/jpeg"), "license": ("l.jpg", JPG, "image/jpeg")})
    ok(r.json()["ok"], f"app: exit sent {r.json()}")
    oid = r.json()["check_id"]
    o = db.get_check(oid)
    ok(o["rental_price"] == 450 and o["deposit_amount"] == 400 and o["km"] == 12050 and o["dash_status"] == "confirmed"
       and o["filmed_by"] == "ahmed" and o["client_lang"] == "ar", "app: price, deposit, km and language saved")
    st = cl.get("/api/a/state", auth=ahmed).json()
    car7 = [c for c in st["cars"] if c["plate"] == "888TU8888"][0]
    ok(car7["st"] == "rented" and car7["days"][0] == "rented" and car7["client"] == "Salma R.",
       "app: the car is rented in the planning")
    det = cl.get(f"/api/a/checks/{oid}", auth=ahmed).json()
    for m in det["marks"]:
        if m["status"] == "ai":
            ok(m["photo"] and m["fr"] and m["ar"], "app: damage with photo and FR/AR label")
            cl.post(f"/api/a/marks/{m['id']}", auth=ahmed, data={"s": "confirmed"})
    ok(cl.post(f"/api/a/checks/{oid}/finish", auth=ahmed).json()["ok"], "app: exit damages checked")
    ok(not [t for t in cl.get("/api/a/state", auth=ahmed).json()["todo"] if t["id"] == oid], "app: nothing left for the exit")
    ok(cl.post("/api/a/cars/888TU8888/remove", auth=auth).status_code == 422, "app: a rented car cannot be removed")
    vid4 = make_video(50, "coral")
    r = cl.post("/api/a/checks", auth=ahmed, data={"kind": "in", "car": "888TU8888", "km": "12900", "fuel8": "6"},
                files={"video": ("w.mp4", vid4, "video/mp4"), "dash": ("d.jpg", JPG, "image/jpeg")})
    ok(r.json()["ok"], f"app: return sent {r.json()}")
    iid = r.json()["check_id"]
    ok([t["what"] for t in cl.get("/api/a/state", auth=ahmed).json()["todo"] if t["id"] == iid] == ["finish"],
       "app: the return waits to be finished")
    det = cl.get(f"/api/a/checks/{iid}", auth=ahmed).json()
    mo = det["money"]
    ok(mo["deposit"] == 400 and mo["fuel"] > 0 and mo["price"] == 450 and mo["fuel_out8"] == 8 and mo["fuel_in8"] == 6,
       f"app: return shows deposit, price and fuel {mo}")
    for m in det["marks"]:
        if m["status"] == "ai" and m["is_new"]:
            cl.post(f"/api/a/marks/{m['id']}", auth=ahmed, data={"s": "rejected"})
    r = cl.post(f"/api/a/checks/{iid}/marks", auth=ahmed, data={"zone": "front_left_door", "kind": "scratch"}).json()
    ok(any(m["source"] == "staff" and m["is_new"] and m["status"] == "confirmed" for m in r["marks"]) and len(r["zones"]) == 14,
       "app: staff adds a damage the AI missed (new at return)")
    r = cl.post(f"/api/a/checks/{iid}/finish", auth=ahmed, data={"damages": "0"}).json()
    ok(r["ok"] and r["invoice"] and r["returned"] == round(400 - mo["fuel"] - mo["km_cost"], 3), f"app: return closed with invoice {r}")
    ok(db.get_check(iid)["status"] == "reported", "app: report sent, location closed")
    car7 = cl.get("/api/a/cars/888TU8888", auth=auth).json()
    ok(car7["st"] == "free" and car7["km"] == 12900 and [h["kind"] for h in car7["history"]][:2] == ["close", "in"],
       f"app: car free again, km updated, history {[h['kind'] for h in car7['history']]}")
    ok(cl.post("/api/a/cars/888TU8888/oil", auth=ahmed).json()["car"]["oil"]["left"] == 10000, "app: oil change noted")
    ok(cl.post("/api/a/cars/888TU8888/remove", auth=auth).status_code == 422, "app: a car with a future booking stays")
    ex = cl.get("/api/a/requests", auth=ahmed).json()["ext"]
    if ex:
        ok(cl.post(f"/api/a/requests/ext/{ex[0]['id']}", auth=ahmed, data={"ok": "1"}).json()["ok"], "app: extension decided")
    ok(cl.get("/api/a/team", auth=ahmed).status_code == 403, "app: the team page is for the owner")
    tm = cl.get("/api/a/team", auth=auth).json()
    ok(any(e["kind"] == "out" and e["who"] == "ahmed" for e in tm["log"]), "app: journal shows who did what")
    r = cl.post("/api/a/team", auth=auth, data={"username": "rim", "name": "Rim B.", "password": "motdepasse2",
                                                "jobs": "book,cash,xx", "phone": "+216 20 111 222", "is_new": "1"})
    ok(r.json()["ok"] and cl.get("/api/a/state", auth=("rim", "motdepasse2")).json()["me"]["jobs"] == ["book", "cash"],
       "app: owner adds an employee with tasks")
    ok(cl.post("/api/a/team", auth=auth, data={"username": "staff", "name": "Moi", "role": "staff"}).status_code == 422,
       "app: the owner cannot demote himself")
    ok(cl.get("/api/a/boss", auth=auth).json()["revenue"] > 0, "app: owner figures of the month")
    ok("<title>" in cl.get("/", auth=ahmed).text, "app: the new agency app is the home page")
else:
    print("  (web pages not tested here: FastAPI not installed, they are tested on GitHub)")

print("\nAll tests passed.")
