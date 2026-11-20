"""Messages WhatsApp libres (réponses au client dans les 24 h après son message), en français ou en arabe.
Les messages qui ouvrent la conversation passent par des modèles Meta : un modèle par langue, même nom."""
import time

TEXT = {
    "fr": {
        "ext_received": "Bonjour {name}, nous avons bien reçu votre demande de prolongation de {days} jour(s) "
                        "pour la voiture {car}. L’agence vous confirme rapidement.",
        "ext_ok": "C’est confirmé : votre location de la voiture {car} est prolongée jusqu’au {date}. Merci !",
        "ext_refused": "Désolé, nous ne pouvons pas prolonger la location de la voiture {car} ({reason}). "
                       "Merci de la rendre le {date} comme prévu, ou appelez l’agence.",
        "ext_help": "Pour prolonger votre location, répondez par exemple : prolonger 2 jours",
        "reason_booked": "elle est réservée par un autre client",
        "reason_agency": "décision de l’agence",
        "book_ok": "Votre réservation de la voiture {car} est acceptée : {days} jour(s) × {price} = {total} DT. "
                   "Suivez-la ici : {link}",
        "book_refused": "Désolé, la voiture {car} n’est pas disponible pour ces dates. "
                        "Essayez d’autres dates ou une autre voiture.",
    },
    "ar": {
        "ext_received": "مرحبًا {name}، تلقّينا طلبك لتمديد كراء السيارة {car} لمدة {days} يوم. "
                        "ستؤكّد الوكالة الطلب قريبًا.",
        "ext_ok": "تمّ التأكيد: تمّ تمديد كراء السيارة {car} إلى غاية {date}. شكرًا لك!",
        "ext_refused": "نعتذر، لا يمكننا تمديد كراء السيارة {car} ({reason}). "
                       "يُرجى إرجاعها يوم {date} كما هو مُتّفق عليه، أو الاتصال بالوكالة.",
        "ext_help": "لتمديد الكراء، أجب مثلًا: تمديد 2 أيام",
        "reason_booked": "السيارة محجوزة لحريف آخر",
        "reason_agency": "قرار الوكالة",
        "book_ok": "تمّ قبول حجزك للسيارة {car}: {days} يوم × {price} = {total} دينار. تابع حجزك هنا: {link}",
        "book_refused": "نعتذر، السيارة {car} غير متوفّرة في هذه التواريخ. جرّب تواريخ أخرى أو سيارة أخرى.",
    },
}


def lang_of(v):
    return v if v in TEXT else "fr"


def t(lang, key, **kw):
    return TEXT[lang_of(lang)][key].format(**kw)


def date(ts):
    """Même format dans les deux langues : 21/11/2026 10:00."""
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))
