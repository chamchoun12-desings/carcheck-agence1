"""All settings come from environment variables (.env). Never put keys in code."""
import os
import pathlib


def _load_dotenv(path: pathlib.Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if v[:1] in ('"', "'") and v[0] in v[1:]:
            v = v[1:v.index(v[0], 1)]                 # "valeur entre guillemets"
        else:
            v = v.split(" #", 1)[0].split("\t#", 1)[0].strip()   # valeur   # commentaire
        os.environ.setdefault(k.strip(), v)


ROOT = pathlib.Path(__file__).resolve().parent.parent
_load_dotenv(ROOT / ".env")

VAULT = pathlib.Path(os.getenv("CARCHECK_VAULT", "/opt/carcheck/vault"))
DB_PATH = pathlib.Path(os.getenv("CARCHECK_DB", str(VAULT / "carcheck.db")))
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
AGENCY_NAME = os.getenv("AGENCY_NAME", "My Agency")

# Walk-around rules
MIN_SECONDS = float(os.getenv("MIN_SECONDS", "45"))      # shorter videos are refused
MAX_SECONDS = float(os.getenv("MAX_SECONDS", "240"))
FRAME_FPS = os.getenv("FRAME_FPS", "1")                  # 1 photo per second
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "8"))           # photos per AI call
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "60"))  # videos deleted after this

# AI (Anthropic API). AI_MODE=mock runs without a key (no marks, staff adds them).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-5-5")
AI_MODE = os.getenv("AI_MODE", "live" if ANTHROPIC_API_KEY else "mock")
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.4"))

# WhatsApp Cloud API
WA_TOKEN = os.getenv("WA_TOKEN", "")
WA_PHONE_ID = os.getenv("WA_PHONE_ID", "")
WA_TEMPLATE = os.getenv("WA_TEMPLATE", "car_return_report")
WA_LANG = os.getenv("WA_LANG", "fr")
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "")
OWNER_PHONE = os.getenv("OWNER_PHONE", "")   # agency owner, international format, no +
WA_REMINDER_TEMPLATE = os.getenv("WA_REMINDER_TEMPLATE", "rappel_retour")
REMINDER_HOURS = float(os.getenv("REMINDER_HOURS", "12"))   # rappel avant le retour prévu
LATE_GRACE_MIN = float(os.getenv("LATE_GRACE_MIN", "60"))   # tolérance avant « en retard »

# Kilométrage et carburant (réglez les prix de votre agence dans .env)
KM_BILLING = os.getenv("KM_BILLING", "0").strip().lower() in ("1", "true", "oui", "yes")      # 0 = km notés seulement, sans frais
FUEL_BILLING = os.getenv("FUEL_BILLING", "1").strip().lower() in ("1", "true", "oui", "yes")  # 0 = carburant noté seulement, sans frais
CURRENCY = os.getenv("CURRENCY", "DT")
KM_PER_DAY = float(os.getenv("KM_PER_DAY", "250"))           # km inclus par jour, 0 = illimité
EXTRA_KM_PRICE = float(os.getenv("EXTRA_KM_PRICE", "0.2"))   # prix par km en plus
TANK_LITERS = float(os.getenv("TANK_LITERS", "45"))          # réservoir moyen de la flotte
FUEL_PRICE = float(os.getenv("FUEL_PRICE", "2.5"))           # prix du litre
FUEL_FEE = float(os.getenv("FUEL_FEE", "10"))                # frais de service si carburant manquant

# Planning et réservations
BOOKING_AUTO_CONFIRM = os.getenv("BOOKING_AUTO_CONFIRM", "0").strip().lower() in ("1", "true", "oui", "yes")
BOOKING_MAX_DAYS = int(os.getenv("BOOKING_MAX_DAYS", "60"))
BOOKING_BUFFER_HOURS = float(os.getenv("BOOKING_BUFFER_HOURS", "2"))   # temps de préparation entre deux locations
BOOKING_DOCS_REQUIRED = os.getenv("BOOKING_DOCS_REQUIRED", "1").strip().lower() in ("1", "true", "oui", "yes")
DOCS_RETENTION_DAYS = int(os.getenv("DOCS_RETENTION_DAYS", "30"))    # au plus tard N jours après la fin prévue
WA_TPL_NEW_BOOKING = os.getenv("WA_TPL_NEW_BOOKING", "nouvelle_reservation")      # à l'agence
WA_TPL_BOOKING_OK = os.getenv("WA_TPL_BOOKING_OK", "reservation_confirmee")       # au client

# Pendant la location : retard, langue des messages
WA_TPL_LATE_CLIENT = os.getenv("WA_TPL_LATE_CLIENT", "retard_client")
WA_TPL_LATE_OWNER = os.getenv("WA_TPL_LATE_OWNER", "retard_agence")
WA_TPL_MAINTENANCE = os.getenv("WA_TPL_MAINTENANCE", "entretien")
LANGS = {"fr": "Français", "ar": "العربية"}
MAX_EXTENSION_DAYS = int(os.getenv("MAX_EXTENSION_DAYS", "30"))

# Entretien
OIL_EVERY_KM = int(os.getenv("OIL_EVERY_KM", "10000"))
OIL_WARN_KM = int(os.getenv("OIL_WARN_KM", "500"))
DOC_WARN_DAYS = int(os.getenv("DOC_WARN_DAYS", "30"))
MAINTENANCE_DIGEST_HOUR = int(os.getenv("MAINTENANCE_DIGEST_HOUR", "8"))

# Facture (à faire vérifier par votre comptable)
AGENCY_ADDRESS = os.getenv("AGENCY_ADDRESS", "")
AGENCY_PHONE = os.getenv("AGENCY_PHONE", "")
AGENCY_TAX_ID = os.getenv("AGENCY_TAX_ID", "")          # matricule fiscal
VAT_RATE = float(os.getenv("VAT_RATE", "0"))             # ex. 19 : prix affichés TTC, TVA détaillée
FISCAL_STAMP = float(os.getenv("FISCAL_STAMP", "0"))     # timbre fiscal ajouté à la facture, si applicable
INVOICE_PREFIX = os.getenv("INVOICE_PREFIX", "F")

# Staff login (HTTP Basic)
STAFF_USER = os.getenv("STAFF_USER", "staff")
STAFF_PASSWORD = os.getenv("STAFF_PASSWORD", "")
