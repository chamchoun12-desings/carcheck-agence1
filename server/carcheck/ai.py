"""Part 03 · The damage map: the AI reads photos 8 by 8 and returns JSON marks.
The AI only PROPOSES. Every mark starts with status 'ai' until staff confirm or reject it.
Only car photos are sent — no names, no phone numbers, no plate in the prompt."""
import base64
import json
import re
import urllib.request

from .config import AI_MODE, AI_MODEL, ANTHROPIC_API_KEY, BATCH_SIZE, MIN_CONFIDENCE
from .zones import KINDS, SIZES, ZONES

SIZE_RANK = {s: i for i, s in enumerate(SIZES)}

PROMPT = f"""You inspect a rental car from walk-around photos (numbered).
List every visible scratch, dent, cracked glass or damaged wheel.
Use ONLY these zones: {", ".join(ZONES)}.
Kinds: {", ".join(KINDS)}. Sizes: small (< 3 cm), medium, large (> 15 cm).
Return JSON only, no other text:
{{"marks": [{{"zone": "...", "kind": "...", "size": "...", "photo": number, "confidence": 0-1}}],
 "bad_photos": [numbers]}}
If a photo is too dark, blurred or wet, add it to "bad_photos" instead of guessing.
Do not mark reflections, dirt or water drops as damage.
If you see no damage, return {{"marks": [], "bad_photos": []}}."""

# Add your own false-positive examples here after testing (see TEST in part 03), e.g.:
# "A light-coloured streak that disappears in the next photo is a reflection, not a scratch."
EXTRA_RULES: list[str] = []


def _call_api(images: list[bytes], prompt: str | None = None) -> str:
    content = []
    for i, img in enumerate(images, start=1):
        content.append({"type": "text", "text": f"Photo {i}:"})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": base64.b64encode(img).decode()}})
    if prompt is None:
        prompt = PROMPT + ("\n" + "\n".join(EXTRA_RULES) if EXTRA_RULES else "")
    content.append({"type": "text", "text": prompt})
    body = json.dumps({"model": AI_MODEL, "max_tokens": 2000,
                       "messages": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data.get("content", []))


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"marks": [], "bad_photos": []}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"marks": [], "bad_photos": []}
    marks = []
    for x in data.get("marks", []) or []:
        if not isinstance(x, dict):
            continue
        if x.get("zone") in ZONES and x.get("kind") in KINDS and x.get("size") in SIZES:
            try:
                marks.append({"zone": x["zone"], "kind": x["kind"], "size": x["size"],
                              "photo": int(x.get("photo", 0)),
                              "confidence": float(x.get("confidence", 0.5))})
            except (TypeError, ValueError):
                continue
    bad = [int(b) for b in data.get("bad_photos", []) or [] if str(b).isdigit()]
    return {"marks": marks, "bad_photos": bad}


def merge(raw_marks: list[dict]) -> list[dict]:
    """Same zone + same kind across many photos = one mark.
    Keeps the largest size, the best confidence, and every photo where it was seen."""
    groups: dict[tuple, dict] = {}
    for m in raw_marks:
        key = (m["zone"], m["kind"])
        g = groups.get(key)
        if not g:
            groups[key] = {**m, "photos": [m["photo"]]}
            continue
        g["photos"].append(m["photo"])
        if SIZE_RANK[m["size"]] > SIZE_RANK[g["size"]]:
            g["size"] = m["size"]
        if m["confidence"] > g["confidence"]:
            g["confidence"], g["photo"] = m["confidence"], m["photo"]
    return list(groups.values())


def analyze(frame_paths) -> dict:
    """Returns {"marks": [...merged...], "bad_photos": [frame filenames]}."""
    raw, bad = [], []
    if AI_MODE == "mock":
        return {"marks": [], "bad_photos": []}
    for start in range(0, len(frame_paths), BATCH_SIZE):
        batch = frame_paths[start:start + BATCH_SIZE]
        result = parse(_call_api([p.read_bytes() for p in batch]))
        for m in result["marks"]:
            if 1 <= m["photo"] <= len(batch) and m["confidence"] >= MIN_CONFIDENCE:
                m["photo"] = batch[m["photo"] - 1].name   # local number -> real file
                raw.append(m)
        bad += [batch[b - 1].name for b in result["bad_photos"] if 1 <= b <= len(batch)]
    for m in raw:
        m["photo"] = str(m["photo"])
    merged = merge(raw)
    for m in merged:
        m["photos"] = [str(p) for p in m["photos"]]
    return {"marks": merged, "bad_photos": sorted(set(bad))}


# ---------- Compteur : kilométrage + jauge de carburant ----------
DASH_PROMPT = """Photo 1 shows the instrument cluster of a rental car. Cars differ a lot; handle every kind:
- ANALOG: round dials with needles; odometer as a small mechanical drum counter or a small LCD strip
  under the speedometer; fuel as a needle between E/0/R and F/1 (often with 1/2 in the middle).
- DIGITAL LCD: odometer as "ODO 123456" or digits with "km"; fuel as a column or arc of segments/bars.
- FULL SCREEN (TFT/virtual cockpit): odometer may be in a corner or a menu; fuel as a bar, a needle drawing or a percentage.
- HYBRID/ELECTRIC: report the FUEL tank level only; ignore the battery % unless there is no fuel gauge (then null).

ODOMETER rules:
- Read the TOTAL distance only. Ignore TRIP / TRIP A / TRIP B / "A" / "B" counters, the trip time,
  the average speed, the outside temperature and the RANGE (autonomy, "km to empty", a pump icon with a distance).
- Ignore the tenths digit if it is separated or a different colour (mechanical counters).
- If the unit is miles ("mi", "miles"), set "unit": "mi" and give the number as shown; never convert yourself.
- If the total is not on screen (only TRIP visible), set km to null and problem to "odo_hidden".

FUEL rules, always in eighths (0 = empty, 4 = half, 8 = full):
- Needle: position between empty and full, rounded to the nearest eighth.
- Segments/bars: lit bars divided by total bars, rounded to the nearest eighth (e.g. 3 of 6 bars = 4).
- Percentage: percent / 12.5, rounded.

Return JSON only:
{"km": integer or null, "unit": "km" or "mi", "fuel_eighths": integer 0-8 or null,
 "dash_type": "analog" | "digital" | "screen" | "unknown",
 "problem": null | "odo_hidden" | "glare" | "blurry" | "screen_off" | "not_dashboard",
 "confidence": 0-1}
Use null for any value you cannot read clearly. Never guess digits."""

MILES_TO_KM = 1.609344


def parse_dashboard(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    out = {"km": None, "fuel": None, "confidence": 0.0, "dash_type": "unknown", "problem": None, "unit": "km"}
    if not m:
        return out
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return out
    if data.get("dash_type") in ("analog", "digital", "screen", "unknown"):
        out["dash_type"] = data["dash_type"]
    if data.get("problem") in ("odo_hidden", "glare", "blurry", "screen_off", "not_dashboard"):
        out["problem"] = data["problem"]
    try:
        km = data.get("km")
        if km is not None and 0 <= int(km) <= 2_000_000:
            if str(data.get("unit", "km")).lower().startswith("mi"):
                out["unit"] = "mi"
                km = round(int(km) * MILES_TO_KM)
            out["km"] = int(km)
        f = data.get("fuel_eighths")
        if f is not None and 0 <= int(f) <= 8:
            out["fuel"] = int(f) / 8
        out["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        pass
    return out


def read_dashboard(image: bytes) -> dict | None:
    """Propose km + carburant. None en mode mock : l'employé saisit les valeurs."""
    if AI_MODE == "mock":
        return None
    return parse_dashboard(_call_api([image], DASH_PROMPT))


# ---------- Plaque d'immatriculation ----------
PLATE_PROMPT = """These photos are the first seconds of a walk-around video of a rental car (it starts at the front).
Read the car's licence plate. Tunisian plates read "NNN تونس NNNN": write them "NNN TU NNNN".
Return JSON only: {"plate": "123 TU 4567" or null, "confidence": 0-1}
Use null if the plate is not clearly readable. Never guess digits."""


def parse_plate(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    plate = data.get("plate")
    if not isinstance(plate, str):
        return None
    plate = plate.upper().replace("تونس", "TU").strip()
    if not re.fullmatch(r"[0-9A-Z][0-9A-Z \-]{2,13}[0-9A-Z]", plate):
        return None
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        conf = 0.5
    return {"plate": plate, "confidence": conf}


def read_plate(images: list[bytes]) -> dict | None:
    """None en mode mock ou si la plaque n'est pas lisible : l'employé la tape."""
    if AI_MODE == "mock" or not images:
        return None
    r = parse_plate(_call_api(images, PLATE_PROMPT))
    return r if r and r["confidence"] >= 0.6 else None
