# AI Car Check

The phone films a walk-around, the server stamps it (time + SHA-256), the AI proposes damage marks, staff confirm, and the same WhatsApp report goes to the client and the agency.

**Rule #1: the AI proposes, a human decides.** No mark reaches a report until staff press *Confirmer*.

```
PHONE (walk-around) → SERVER (time + hash) → FFMPEG (1 photo/s) → AI (marks)
→ STAFF (confirm/reject) → WHATSAPP (client + owner)
```

## What's in the box

| File | Guide part | What it does |
|---|---|---|
| `carcheck/zones.py` | 01 | 14 zones, 4 kinds, 3 sizes + French labels |
| `carcheck/intake.py` | 02 | Saves video, server time, SHA-256, GPS; refuses < 45 s |
| `carcheck/frames.py` + `ai.py` | 03 | ffmpeg 1 photo/s, AI reads 8 by 8, JSON marks, merge |
| `carcheck/compare.py` | 04 | `in` mark not in `out` (same zone + kind) = NEW; picks the "before" photo |
| `carcheck/report.py` | 05 | WhatsApp template to client + owner (confirmed marks only) |
| `carcheck/monthly.py` | 06 | 30-day page: which car, which damage, which zone |
| `carcheck/billing.py` | km/fuel | Km driven, extra km, missing fuel and amounts (prices in `.env`) |
| `carcheck/planning.py` + `web_planning.py` | planning | Fleet, bookings, availability, no double rental; pages /planning, /cars and the public /reserver |
| `carcheck/reminders.py` | location | WhatsApp reminder 12 h before the planned return (cron every 15 min) |
| `carcheck/cleanup.py` | rules | Deletes videos after `RETENTION_DAYS` |
| `carcheck/app.py` | all | Web app: upload, review, secret client link, webhook |
| `tests/run_tests.py` | TESTs | Runs the guide's tests with fake videos |

## Install (Ubuntu VPS, 2 vCPU / 2 GB)

```bash
sudo apt install -y python3-venv ffmpeg caddy
sudo useradd -m -d /opt/carcheck carcheck
sudo -u carcheck bash
cd /opt/carcheck && mkdir vault
# copy this folder to /opt/carcheck/app
python3 -m venv venv && venv/bin/pip install -r app/requirements.txt
cp app/.env.example app/.env && nano app/.env      # set STAFF_PASSWORD, keys
cd app && ../venv/bin/python tests/run_tests.py     # must say "All tests passed."
```

Then, as root:

```bash
cp /opt/carcheck/app/deploy/carcheck.service /etc/systemd/system/
systemctl enable --now carcheck
cp /opt/carcheck/app/deploy/Caddyfile /etc/caddy/Caddyfile   # edit the domain
systemctl reload caddy
```

Set the server time zone to the agency's (`sudo timedatectl set-timezone Africa/Tunis`), then add the cron lines from `deploy/crontab.txt` (`crontab -e` as `carcheck`).

To try it on your own PC first: `pip install -r requirements.txt`, set `CARCHECK_VAULT=./vault` and `STAFF_PASSWORD` in `.env`, then `uvicorn carcheck.app:app --reload` and open http://localhost:8000.

## Daily use

1. **Exit:** staff open the site on the phone → plate, *Sortie*, client WhatsApp number → film. Add a **photo of the dashboard** (ignition on: odometer + fuel gauge). Client stands next to the car.
2. Open the check → confirm or reject each AI mark (add any it missed).
   **Dashboard:** the AI proposes km and fuel (in eighths); staff confirm or correct. Required at exit and at return.
3. **Rental duration (required):** on the same exit check, enter the number of days; the return date is calculated from the exit time and can be changed. A return video is refused until this is saved. Use the same form to extend a rental: the reminder is re-armed.
4. **Reminder:** 12 h before the planned return, the client and the agency get the same WhatsApp reminder.
5. **Return:** same route, choose *Retour*. NEW marks show *before / after* photos side by side.
   The check shows *rendu à l'heure ✓* or *rendu en retard de X h*.
6. When every mark is decided → *Envoyer le rapport WhatsApp*.
7. 1st of the month: open `/monthly`.

## Phone app: guided capture, offline queue

- `POST /api/upload` (staff login, multipart): `car` (empty = AI reads the plate), `kind`, `client_phone`, `video`, `dash`, `signature` (PNG), `license` (photo), `license_expiry` (YYYY-MM-DD), `recorded_at` (phone time, epoch seconds), `phone_sha256`. JSON answer; `422` + `error` when refused (expired licence, unreadable plate, hash mismatch...).
- The web upload page has the same fields, with a finger signature pad.
- **New agency app** (served on `/`, file `carcheck/static/agence.html`, same page inside the Android app): JSON API under `/api/a/` in `carcheck/agence.py` —
  `GET /api/a/state` (home, planning, cars), `POST /api/a/checks` (exit or return: video, dashboard photo, licence, km, fuel, days, price per day, deposit),
  `GET /api/a/checks/{id}`, `POST /api/a/marks/{id}`, `POST /api/a/checks/{id}/marks` (missed damage), `POST /api/a/checks/{id}/finish` (deposit, invoice, WhatsApp report),
  `POST /api/a/dash-read`, `GET|POST /api/a/cars…` (fleet, oil change), `GET /api/a/requests` + `POST /api/a/requests/res|ext/{id}` (price per day typed when accepting),
  `GET|POST /api/a/team…` and `GET /api/a/boss` (owner only). Every action is written in the `events` table (team journal).
- **Client page** `/reserver` (`carcheck/static/client.html`): `GET /api/public/cars` (free cars, no prices), `POST /api/public/book` (with ID + licence photos), `GET /api/public/res/{token}` (status, price once accepted).
- The old pages (`/ancien`, `/checks`, `/planning`, `/cars`, `/monthly`, `/users`) still work for detailed views and PDF invoices.
- Licence photo: staff only, never sent to the AI, never on the client link, deleted when the return report is sent; the expiry date stays.

## Team, maintenance, money

- **Équipe** (`/users`, owner only): one login per employee, optional agency. Every check, mark decision, dashboard, rental, deposit, booking and repair shows who did it. Staff see their agency; the owner sees everything. The `.env` login stays the owner's backup account.
- **Late returns**: `carcheck.reminders` (cron every 15 min) also sends one alert per late rental (agency + polite message to the client) after `LATE_GRACE_MIN`.
- **Extensions**: client replies on WhatsApp; staff approve on the Planning page; booking conflicts refuse automatically; price and reminders follow.
- **Car file** (`/cars/<plate>`): rentals, new damages, repairs and costs, revenue, margin; maintenance dates and oil change. Expired insurance, inspection or vignette **blocks the exit**. Daily maintenance summary to the owner.
- **Deposit and invoice**: deposit at exit; at return the page proposes fuel/km, staff enter damages/other, the app computes retained / returned / still due and creates a numbered PDF invoice (`/invoice/<id>.pdf`, also on the client link). The WhatsApp report waits for this closing.
- **Monthly**: revenue (invoices), occupancy per car, repair and upkeep costs, deposits retained.

## Planning and online booking

- **Voitures** (`/cars`): filmed cars are added automatically. Add the model and the price per day; tick "visible" to show the car to clients.
- **Planning** (`/planning`): today's numbers, "a client calls: which cars are free?", pending requests (Confirm / Refuse), 14-day grid, phone bookings.
- **Réserver** (`/reserver`, no login): clients pick dates, see free cars and the total price, and book with their name and WhatsApp. Share this link on WhatsApp, Facebook, Google Maps.
- **Client documents:** the public booking form asks for the ID card (both sides) or passport, and the driving licence with its validity date (`BOOKING_DOCS_REQUIRED`). Files are checked by content (JPEG/PNG/WebP/HEIC/PDF, 10 MB max), stored in `vault/bookings/<id>/`, served only to logged-in staff (`/bookdocs/...`), never to the AI. Staff check them at `/reservations/<id>/docs`. Deleted when the booking is refused or cancelled, when the rental closes, and at the latest `DOCS_RETENTION_DAYS` after the end (daily `cleanup`). No document number is stored.
- **No double rental:** a car that is out, booked or requested cannot be booked again on the same dates (plus `BOOKING_BUFFER_HOURS` for cleaning). A second exit of a car that is still out is refused, and so is a rental duration that overlaps another client's booking. When a client who booked takes the car, the booking becomes the rental.

## WhatsApp setup (start early — approval takes time)

1. Meta for Developers → create an app → add **WhatsApp** → note the *Phone number ID* and create a permanent token (System User). Put them in `WA_PHONE_ID` and `WA_TOKEN`.
2. WhatsApp Manager → Message templates → new template:
   - Name `car_return_report`, Category **Utility**, language French (`WA_LANG=fr`)
   - Body: `Voiture {{1}} · sortie {{2}} · retour {{3}}. Nouvelles marques : {{4}}. Déjà présentes : {{5}}. Photos et vidéo : {{6}}`
   - Quick-reply buttons: `OK` and `Je veux en parler`
   - Second template: name `rappel_retour`, Category **Utility**, French.
     Body: `Bonjour, rappel de {{3}} : la voiture {{1}} est à rendre le {{2}}. Le contrôle vidéo de retour sera fait avec vous. Pour prolonger la location, répondez à ce message.`
   - Template `nouvelle_reservation` (to the agency), Utility, French:
     `Nouvelle demande de réservation : {{1}}, du {{2}} au {{3}}. Client : {{4}}, {{5}}. Confirmez-la dans le Planning.`
   - Template `reservation_confirmee` (to the client), Utility, French:
     `Votre réservation de {{1}} du {{2}} au {{3}} est confirmée par {{4}}. Détails et annulation : {{5}}`
   - **Each client template exists in two languages** with the same name: French (`fr`) and Arabic (`ar`). The client's choice decides which one is sent.
   - Update `rappel_retour` to end with: `Pour prolonger, répondez « prolonger 2 jours ».` / Arabic: `للتمديد، أجب « تمديد 2 أيام ».`
   - Template `retard_client` (client, fr + ar): `Bonjour, la voiture {{1}} devait être rendue le {{2}}. Tout va bien ? Merci de nous la ramener ou de répondre « prolonger 1 jour ». {{3}}`
     Arabic: `مرحبًا، كان من المفروض إرجاع السيارة {{1}} يوم {{2}}. هل كل شيء على ما يرام؟ يُرجى إرجاعها أو الردّ بـ « تمديد 1 يوم ». {{3}}`
   - Template `retard_agence` (agency, fr): `Retard : la voiture {{1}} (client {{2}}) devait rentrer le {{3}}.`
   - Template `entretien` (agency, fr): `Entretien à prévoir : {{1}}`
   - Arabic versions of `car_return_report` and `reservation_confirmee` with the same parameters.
   - Extension replies (« prolonger 2 jours », « تمديد يومين ») arrive on the webhook; the agency's answer is a normal message, allowed by WhatsApp within 24 h of the client's message.
3. Webhook URL `https://your-domain/webhook`, verify token = `WA_VERIFY_TOKEN`, subscribe to `messages`. Button replies are stored in the `replies` table.
4. Add to the rental contract a line where the client agrees to receive the check report on WhatsApp.

## AI setup

Put an Anthropic API key in `ANTHROPIC_API_KEY`. Without it the app runs in `mock` mode: everything works, but staff add marks by hand. That is already useful on day one.

**Tuning (TEST 03):** take a car with 3 damages you know, film it 3 times. The AI must find the same 3 each time, in the same zone. If it marks dirt or reflections, add an example to `EXTRA_RULES` in `carcheck/ai.py`. Raise `MIN_CONFIDENCE` if it is too noisy.

## Build order (from the guide)

- **Today:** exit video only (mock mode). This alone protects you.
- **Day 1:** server + time + hash. **Day 2:** frames + AI + marks. **Day 3:** compare + staff confirm.
- **Then:** WhatsApp report and monthly page.
- Don't move to the next part until its test passes.

## Privacy rules

- Film the car, not people. **Face blurring is not built in** — staff must avoid filming faces and other cars; if they show, don't send that check to the AI (use mock / manual marks).
- Only car photos go to the AI: no name, phone or plate in the prompt.
- Videos are deleted after `RETENTION_DAYS` (set it to "case closed + one month" for you). Marks and hashes stay.
- HTTPS only; keys live in `.env`, never in code.
- Check local rules on video recording and personal data (in Tunisia: INPDP).

## Known limits

- Two separate scratches on the same door merge into one mark (by design: same zone + same kind = one mark). Staff can add a second mark by hand.
- The "before" photo is picked by position in the video, so both walk-arounds must follow the same route (front → right → rear → left).
- Night or rain → the AI lists `bad_photos`; refilm under light or write "not visible" in the report.
