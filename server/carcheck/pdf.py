"""Petit générateur de PDF sans dépendance (texte, traits, cadres), suffisant pour une facture A4.
Polices Helvetica / Helvetica-Bold, accents français (WinAnsi). Les caractères arabes deviennent « ? » :
la facture est en français."""

W, H = 595.28, 841.89          # A4 en points


class PDF:
    def __init__(self):
        self.pages = []
        self.ops = []

    @staticmethod
    def _esc(s):
        b = str(s).encode("cp1252", errors="replace")
        return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")

    @staticmethod
    def width(s, size, bold=False):
        """Largeur approximative (Helvetica) pour aligner à droite."""
        w = 0.0
        for ch in str(s):
            if ch in "il.,:;'|!" or ch == " ":
                w += 0.28
            elif ch.isdigit():
                w += 0.556
            elif ch.isupper() or ch in "mwMW":
                w += 0.72
            else:
                w += 0.5
        return w * size * (1.05 if bold else 1.0)

    def text(self, x, y, s, size=10, bold=False, gray=0.0, right=False):
        """x, y depuis le coin en haut à gauche, en points."""
        if right:
            x -= self.width(s, size, bold)
        self.ops.append(b"BT /%s %.1f Tf %.3f g %.2f %.2f Td (%s) Tj ET" % (
            b"F2" if bold else b"F1", size, gray, x, H - y, self._esc(s)))

    def line(self, x1, y1, x2, y2, width=0.6, gray=0.0):
        self.ops.append(b"%.2f w %.3f G %.2f %.2f m %.2f %.2f l S" % (width, gray, x1, H - y1, x2, H - y2))

    def rect(self, x, y, w, h, fill=0.95):
        self.ops.append(b"%.3f g %.2f %.2f %.2f %.2f re f 0 g" % (fill, x, H - y - h, w, h))

    def new_page(self):
        self.pages.append(b"\n".join(self.ops))
        self.ops = []

    def output(self):
        if self.ops or not self.pages:
            self.new_page()
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
        kids = []
        for content in self.pages:
            objs.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
            cid = len(objs)
            objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R"
                        b" /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>" % (W, H, cid))
            kids.append(len(objs))
        objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, o in enumerate(objs, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n%s\nendobj\n" % (i, o)
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
        return bytes(out)


def invoice_pdf(data, agency):
    """data = money.invoice_data(...), agency = {name, address, phone, tax_id}."""
    from .billing import money as fmt_money
    p = PDF()
    inv, c, out, car = data["invoice"], data["check"], data["out"], data["car"]
    p.rect(40, 40, W - 80, 70, fill=0.11)
    p.text(56, 72, agency["name"], 18, bold=True, gray=1.0)
    p.text(56, 92, " · ".join(x for x in (agency.get("address"), agency.get("phone")) if x) or " ", 9, gray=0.85)
    if agency.get("tax_id"):
        p.text(56, 104, f"Matricule fiscal : {agency['tax_id']}", 8, gray=0.85)
    p.text(W - 56, 72, "FACTURE", 16, bold=True, gray=1.0, right=True)
    p.text(W - 56, 92, f"N° {inv['number']}", 10, gray=1.0, right=True)
    import time as _t
    p.text(W - 56, 104, "Date : " + _t.strftime("%d/%m/%Y", _t.localtime(inv["created"])), 9, gray=0.85, right=True)

    y = 140
    p.text(40, y, "Client", 9, gray=0.45)
    p.text(40, y + 15, out.get("client_name") or "—", 11, bold=True)
    p.text(40, y + 29, out.get("client_phone") or "", 9)
    p.text(300, y, "Véhicule", 9, gray=0.45)
    p.text(300, y + 15, c["car"] if car["name"] in (None, "", c["car"]) else f"{car['name']} · {c['car']}", 11, bold=True)
    p.text(300, y + 29, f"Sortie {out['server_time'][:16]}  ->  Retour {c['server_time'][:16]}", 9)
    if data.get("km"):
        k = data["km"]
        p.text(300, y + 42, f"Compteur {k['km_out']} -> {k['km_in']} km ({k['distance']} km)", 9)

    y = 215
    p.rect(40, y, W - 80, 22, fill=0.93)
    p.text(48, y + 15, "Désignation", 9, bold=True)
    p.text(W - 48, y + 15, "Montant", 9, bold=True, right=True)
    y += 22
    for label, amount in data["lines"]:
        y += 20
        p.text(48, y, label[:95], 10)
        p.text(W - 48, y, fmt_money(amount), 10, right=True)
        p.line(40, y + 7, W - 40, y + 7, 0.3, 0.8)
    y += 28
    p.text(W - 200, y, "TOTAL", 12, bold=True)
    p.text(W - 48, y, fmt_money(data["total"]), 12, bold=True, right=True)
    if data["vat_rate"]:
        y += 16
        p.text(W - 200, y, f"dont TVA {data['vat_rate']:g} %", 9, gray=0.35)
        p.text(W - 48, y, fmt_money(data["vat"]), 9, gray=0.35, right=True)

    y += 40
    p.rect(40, y, W - 80, 74, fill=0.96)
    p.text(52, y + 18, "Caution", 10, bold=True)
    dep = data["deposit"]
    method = f" ({data['deposit_method']})" if data.get("deposit_method") else ""
    p.text(52, y + 36, f"Reçue{method} : {fmt_money(dep)}", 10)
    p.text(52, y + 52, f"Retenue (frais ci-dessus hors location) : {fmt_money(data['retained'])}", 10)
    p.text(52, y + 68, f"Restituée : {fmt_money(data['returned'])}", 10, bold=True)
    if data["still_due"]:
        p.text(W - 52, y + 68, f"Reste à payer : {fmt_money(data['still_due'])}", 10, bold=True, right=True)

    p.text(40, H - 50, f"{agency['name']} · facture {inv['number']} · générée par Car Check", 8, gray=0.5)
    return p.output()
