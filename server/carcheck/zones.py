"""The shared language: 14 fixed zones, 4 kinds, 3 sizes (part 01 of the guide)."""

ZONES = [
    "front_bumper", "bonnet", "windscreen",
    "roof", "rear_window", "boot",
    "rear_bumper", "front_left_wing",
    "front_left_door", "rear_left_door",
    "front_right_wing", "front_right_door",
    "rear_right_door", "wheels",
]
KINDS = ["scratch", "dent", "glass", "wheel"]
SIZES = ["small", "medium", "large"]

# Labels shown to staff and clients (edit to Arabic/French as you like)
ZONE_LABELS = {
    "front_bumper": "Pare-choc avant", "bonnet": "Capot", "windscreen": "Pare-brise",
    "roof": "Toit", "rear_window": "Lunette arrière", "boot": "Coffre",
    "rear_bumper": "Pare-choc arrière", "front_left_wing": "Aile avant gauche",
    "front_left_door": "Porte avant gauche", "rear_left_door": "Porte arrière gauche",
    "front_right_wing": "Aile avant droite", "front_right_door": "Porte avant droite",
    "rear_right_door": "Porte arrière droite", "wheels": "Jantes / roues",
}
KIND_LABELS = {"scratch": "Rayure", "dent": "Bosse", "glass": "Vitre", "wheel": "Jante"}
SIZE_LABELS = {"small": "petite (< 3 cm)", "medium": "moyenne", "large": "grande (> 15 cm)"}

# Arabe : pour les messages WhatsApp des clients qui ont choisi l'arabe
ZONE_LABELS_AR = {
    "front_bumper": "الصدّام الأمامي", "bonnet": "غطاء المحرّك", "windscreen": "الزجاج الأمامي",
    "roof": "السقف", "rear_window": "الزجاج الخلفي", "boot": "صندوق السيارة",
    "rear_bumper": "الصدّام الخلفي", "front_left_wing": "الجناح الأمامي الأيسر",
    "front_left_door": "الباب الأمامي الأيسر", "rear_left_door": "الباب الخلفي الأيسر",
    "front_right_wing": "الجناح الأمامي الأيمن", "front_right_door": "الباب الأمامي الأيمن",
    "rear_right_door": "الباب الخلفي الأيمن", "wheels": "العجلات والجنوط",
}
KIND_LABELS_AR = {"scratch": "خدش", "dent": "انبعاج", "glass": "زجاج", "wheel": "جنط"}
