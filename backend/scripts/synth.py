"""Building blocks for SYNTHETIC test documents (all names, numbers and authorities are fictional).

Produces PDFs that look like certificates, optionally:
  - with an Ed25519-signed QR code (as an issuing authority would print)
  - "scanned" (image-only, needs OCR)
  - tampered: one field re-typed in a different font after issue, metadata
    showing an editing tool, and an incremental save appended — the traces a
    real edit typically leaves.
"""
from __future__ import annotations

import os
os.environ["TZ"] = "UTC"   # pyHanko reads the local zone via tzlocal, which rejects some IANA aliases (generator only)

import base64
import io
import json
import random
from datetime import datetime
from pathlib import Path

import pypdfium2 as pdfium
import qrcode
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

W, H = A4

TEMPLATES = {
    "affidavit": {
        "issuer": "BEFORE THE NOTARY PUBLIC",
        "title": "AFFIDAVIT CUM UNDERTAKING",
        "labels": [("Name of the Institution", "institution_name"), ("AICTE Permanent ID", "aicte_permanent_id"),
                   ("Academic Year", "academic_year"), ("Date of Affirmation", "issue_date"),
                   ("Notary Reg. No.", "notary_reg_no")],
        "body": ["I, the deponent, being the authorised signatory of the institution named above, do hereby",
                 "solemnly affirm that the information furnished in the application for Extension of Approval",
                 "is true and correct, and undertake to comply with all applicable norms and conditions."],
    },
    "fire_noc": {
        "issuer": "STATE FIRE AND EMERGENCY SERVICES (DEMO AUTHORITY)",
        "title": "FIRE SAFETY NO OBJECTION CERTIFICATE",
        "labels": [("NOC No.", "certificate_no"), ("Name of the Premises", "institution_name"),
                   ("Date of Issue", "issue_date"), ("Valid Until", "valid_until"),
                   ("Built-up Area (sq m)", "built_up_area_sqm")],
        "body": ["Certified that the premises named above has been inspected and the fire safety measures",
                 "were found satisfactory under the applicable Fire Service rules, subject to annual maintenance."],
    },
    "building_completion": {
        "issuer": "MUNICIPAL CORPORATION — BUILDING DEPARTMENT (DEMO)",
        "title": "BUILDING COMPLETION AND OCCUPANCY CERTIFICATE",
        "labels": [("Certificate No.", "certificate_no"), ("Name of the Owner", "institution_name"),
                   ("Date of Issue", "issue_date"), ("Built-up Area (sq m)", "built_up_area_sqm")],
        "body": ["Certified that the building has been completed as per the sanctioned plan and is fit for",
                 "occupancy for educational use."],
    },
    "pollution_noc": {
        "issuer": "STATE POLLUTION CONTROL BOARD (DEMO AUTHORITY)",
        "title": "CONSENT TO OPERATE",
        "labels": [("Consent No.", "certificate_no"), ("Name of the Unit", "institution_name"),
                   ("Date of Issue", "issue_date"), ("Valid Until", "valid_until")],
        "body": ["Consent is granted under the Water and Air Acts for operation of the unit, subject to",
                 "conditions on effluent treatment and environment management."],
    },
    "nba_accreditation": {
        "issuer": "NATIONAL BOARD OF ACCREDITATION (DEMO REGISTRY)",
        "title": "CERTIFICATE OF ACCREDITATION",
        "labels": [("Accreditation No.", "certificate_no"), ("Name of the Institution", "institution_name"),
                   ("Programme", "programme"), ("Valid Until", "valid_until")],
        "body": ["This is to certify that the programme named above has been accredited by the National",
                 "Board of Accreditation for the period indicated."],
    },
    "university_affiliation": {
        "issuer": "OFFICE OF THE REGISTRAR, STATE TECHNICAL UNIVERSITY (DEMO)",
        "title": "LETTER OF AFFILIATION",
        "labels": [("Letter No.", "certificate_no"), ("Name of the College", "institution_name"),
                   ("Academic Year", "academic_year"), ("Date of Issue", "issue_date")],
        "body": ["The university hereby grants affiliation to the college named above for the academic year",
                 "indicated, for the programmes approved by AICTE."],
    },
    "ter_receipt": {
        "issuer": "AICTE ONLINE PAYMENT GATEWAY (DEMO)",
        "title": "PAYMENT RECEIPT — PROCESSING FEE",
        "labels": [("Transaction ID", "transaction_id"), ("Name of the Institution", "institution_name"),
                   ("AICTE Permanent ID", "aicte_permanent_id"), ("Payment Date", "payment_date"),
                   ("Amount Paid", "amount")],
        "body": ["Received the processing fee towards the application for approval. This is a",
                 "computer-generated receipt."],
    },
    "land_deed": {
        "issuer": "OFFICE OF THE SUB-REGISTRAR — REGISTRATION DEPARTMENT (DEMO)",
        "title": "REGISTERED SALE DEED — EXTRACT",
        "labels": [("Name of the Purchaser", "institution_name"), ("Survey No.", "survey_number"),
                   ("Total Area", "land_area"), ("Registration No.", "registration_no"),
                   ("Date of Registration", "issue_date")],
        "body": ["Extract of the registered sale deed. The schedule of property described above is conveyed",
                 "to the purchaser free of encumbrances, for institutional educational use."],
    },
    "town_planning_noc": {
        "issuer": "DIRECTORATE OF TOWN AND COUNTRY PLANNING (DEMO AUTHORITY)",
        "title": "LAND USE / ZONING CERTIFICATE",
        "labels": [("NOC No.", "certificate_no"), ("Name of the Applicant", "institution_name"),
                   ("Survey No.", "survey_number"), ("Zoning", "land_category"), ("Date of Issue", "issue_date")],
        "body": ["Certified that the land described above falls in a zone where educational use is permitted",
                 "under the master plan, and the competent authority has no objection to its use."],
    },
    "balance_sheet": {
        "issuer": "CHARTERED ACCOUNTANTS — STATUTORY AUDITORS (DEMO FIRM)",
        "title": "AUDITED BALANCE SHEET — SUMMARY CERTIFICATE",
        "labels": [("Name of the Trust", "institution_name"), ("Financial Year", "financial_year"),
                   ("Net Worth", "net_worth"), ("Membership No.", "ca_reg_no"), ("UDIN", "udin")],
        "body": ["We have audited the balance sheet and the income and expenditure account of the trust for",
                 "the financial year above. Certified by a chartered accountant in practice."],
    },
    "state_govt_noc": {
        "issuer": "GOVERNMENT OF THE STATE — HIGHER EDUCATION DEPARTMENT (DEMO)",
        "title": "NO OBJECTION CERTIFICATE",
        "labels": [("G.O. No.", "certificate_no"), ("Name of the Institution", "institution_name"),
                   ("Dated", "issue_date")],
        "body": ["The State Government has no objection to the proposal of the institution named above,",
                 "subject to approval by AICTE and affiliation by the university."],
    },
    "trust_resolution": {
        "issuer": "BOARD OF TRUSTEES — MINUTES OF MEETING",
        "title": "RESOLUTION OF THE GOVERNING BODY / TRUST",
        "labels": [("Name of the Trust", "institution_name"), ("Proposed Name", "proposed_name"),
                   ("Date of Meeting", "issue_date")],
        "body": ["RESOLVED THAT the society / trust approves the proposal recorded above and authorises",
                 "the Principal to submit the application to AICTE on its behalf."],
    },
}


# ------------------------------------------------------------------ keys

def make_keys(sources: list[str], keydir: Path, trustdir: Path) -> dict:
    keydir.mkdir(parents=True, exist_ok=True)
    trustdir.mkdir(parents=True, exist_ok=True)
    keys = {}
    for s in sources:
        k = Ed25519PrivateKey.generate()
        keys[s] = k
        pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        (trustdir / f"{s}.pub").write_text(pub.hex())
    return keys


def signed_qr_payload(key: Ed25519PrivateKey, src: str, ref: str, fields: dict) -> str:
    body = {"src": src, "ref": ref, "fields": fields}
    msg = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    body["sig"] = base64.b64encode(key.sign(msg)).decode()
    return json.dumps(body, separators=(",", ":"))


# ------------------------------------------------------------------ PDFs

def _pdf_date(d: datetime) -> str:
    return d.strftime("D:%Y%m%d%H%M%S+05'30'")


def _draw(c, dtype, values, qr_text=None, override=None, seed=0):
    t = TEMPLATES[dtype]
    rnd = random.Random(seed)
    accent = HexColor(rnd.choice(["#1f3b73", "#6b1d1d", "#1d4d3a", "#4a2b6b"]))
    c.setFillColor(accent)
    c.rect(0, H - 95, W, 95, fill=1, stroke=0)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(W / 2, H - 50, t["issuer"])
    c.setFont("Helvetica", 9)
    c.drawCentredString(W / 2, H - 68, "SYNTHETIC DOCUMENT FOR PROTOTYPE TESTING — NOT A REAL CERTIFICATE")
    c.setFillColor(HexColor("#111111"))
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(W / 2, H - 140, t["title"])
    y = H - 190
    for label, key in t["labels"]:
        val = values.get(key)
        if val is None:
            continue
        c.setFont("Helvetica-Bold", 11)
        txt = f"{label}: "
        c.drawString(72, y, txt)
        x = 72 + c.stringWidth(txt, "Helvetica-Bold", 11)
        if override and override[0] == key:
            c.setFont(override[1], override[2])
        else:
            c.setFont("Helvetica", 11)
        c.drawString(x, y, str(val))
        y -= 24
    y -= 16
    c.setFont("Helvetica", 10.5)
    for line in t["body"]:
        c.drawString(72, y, line)
        y -= 16
    # seal + signature
    c.setStrokeColor(accent)
    c.setLineWidth(2)
    c.circle(W - 150, 190, 42, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(accent)
    c.drawCentredString(W - 150, 192, "OFFICIAL SEAL")
    c.drawCentredString(W - 150, 182, "(DEMO)")
    c.setFillColor(HexColor("#111111"))
    c.setFont("Helvetica", 10)
    c.drawString(72, 150, "Authorised Signatory")
    c.line(72, 165, 230, 165)
    if qr_text:
        img = qrcode.make(qr_text, box_size=4, border=2).get_image()
        c.drawImage(ImageReader(img), 72, 40, 95, 95)
        c.setFont("Helvetica", 7)
        c.drawString(172, 60, "Scan to verify (signed by issuing authority)")


def ink_stamp(seed: int, size: int = 300) -> Image.Image:
    """A round rubber-stamp impression in coloured ink (transparent background)."""
    rnd = random.Random(seed)
    col = rnd.choice([(30, 40, 160), (110, 30, 140), (170, 30, 30)])
    st = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(st)
    d.ellipse((8, 8, size - 8, size - 8), outline=col + (255,), width=7)
    d.ellipse((48, 48, size - 48, size - 48), outline=col + (255,), width=3)
    for i, t in enumerate(["RECEIVED", f"No. {rnd.randint(1000, 9999)}", "SEAL"]):
        d.text((size * 0.32, size * 0.36 + i * 24), t, fill=col + (255,))
    for k in range(40):
        d.line((70 + k * 4, 200 + rnd.randint(0, 10), 76 + k * 4, 222 - rnd.randint(0, 10)), fill=col + (255,), width=2)
    return st


def build_pdf(path: Path, dtype: str, values: dict, issued: datetime, qr_text: str | None = None, seed: int = 0,
              cloned_stamp: bool = False):
    """cloned_stamp: the same ink stamp appears at two places (a copied seal) — for the copy-move indicator."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setCreator("AuthorityDocGen 3.2")
    c.setProducer("AuthorityDocGen 3.2 (ReportLab)")
    _draw(c, dtype, values, qr_text, seed=seed)
    if cloned_stamp:
        st = ImageReader(ink_stamp(seed))
        c.drawImage(st, 300, 300, 110, 110, mask="auto")
        c.drawImage(st, 90, 420, 110, 110, mask="auto")
    c.showPage()
    c.save()
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    w.add_metadata({"/CreationDate": _pdf_date(issued), "/ModDate": _pdf_date(issued),
                    "/Creator": "AuthorityDocGen 3.2", "/Producer": "AuthorityDocGen 3.2 (ReportLab)"})
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        w.write(f)


def build_tampered_pdf(path: Path, dtype: str, original: dict, field: str, new_value: str, issued: datetime,
                       edited: datetime, qr_text: str | None = None, seed: int = 0):
    """Original layout and QR, but `field` re-typed with another font, then saved by an editor."""
    vals = dict(original, **{field: new_value})
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _draw(c, dtype, vals, qr_text, override=(field, "Times-Roman", 11.5), seed=seed)
    c.showPage()
    c.save()
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    w.add_metadata({"/CreationDate": _pdf_date(issued), "/ModDate": _pdf_date(issued),
                    "/Creator": "AuthorityDocGen 3.2", "/Producer": "AuthorityDocGen 3.2 (ReportLab)"})
    first = io.BytesIO()
    w.write(first)
    # incremental save by an "editor"
    w2 = PdfWriter(io.BytesIO(first.getvalue()), incremental=True)
    w2.add_metadata({"/ModDate": _pdf_date(edited), "/Producer": "Foxit PhantomPDF 12.1"})
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        w2.write(f)


def build_scanned_pdf(path: Path, dtype: str, values: dict, issued: datetime, seed: int = 0, quality: str = "good"):
    """Render the certificate, degrade it like a scanner would, and embed only the image."""
    tmp = path.with_suffix(".tmp.pdf")
    build_pdf(tmp, dtype, values, issued, seed=seed)
    pdf = pdfium.PdfDocument(str(tmp))
    img = pdf[0].render(scale=200 / 72).to_pil().convert("L")
    pdf.close()
    tmp.unlink()
    rnd = random.Random(seed)
    img = img.rotate(rnd.uniform(-0.8, 0.8), fillcolor=255, expand=False)
    img = ImageEnhance.Contrast(img).enhance(0.85)
    if quality == "poor":
        img = img.resize((img.width // 3, img.height // 3)).resize((img.width, img.height)).filter(ImageFilter.GaussianBlur(1.6))
    import numpy as np
    arr = np.asarray(img).astype(np.int16)
    arr = np.clip(arr + np.random.default_rng(seed).normal(0, 6, arr.shape), 0, 255).astype("uint8")
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setCreator("ScanSoft Office Scanner")
    c.setProducer("ScanSoft Office Scanner")
    c.drawImage(ImageReader(img), 0, 0, W, H)
    c.showPage()
    c.save()
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    w.add_metadata({"/CreationDate": _pdf_date(issued), "/ModDate": _pdf_date(issued),
                    "/Creator": "ScanSoft Office Scanner", "/Producer": "ScanSoft Office Scanner"})
    with open(path, "wb") as f:
        w.write(f)


# ------------------------------------------------------------------ photos

ROOM_PALETTES = {
    "classroom": [(214, 204, 180), (120, 90, 60), (40, 60, 50)],
    "lab": [(220, 225, 230), (90, 95, 110), (30, 30, 35)],
    "library": [(205, 190, 160), (110, 70, 40), (150, 40, 40)],
}


def camera_exif(seed: int, lat: float | None = None, lon: float | None = None, when: str = "2026:09:18 11:20:00"):
    """EXIF like a phone camera writes: make, model, capture time and (optionally) GPS position."""
    from PIL import Image as _I
    rnd = random.Random(seed)
    make, model = rnd.choice([("Samsung", "SM-A546E"), ("Xiaomi", "Redmi Note 13"), ("Apple", "iPhone 13"), ("OnePlus", "CPH2491")])
    ex = _I.Exif()
    ex[271], ex[272], ex[306] = make, model, when                  # Make, Model, DateTime
    if lat is not None and lon is not None:
        def dms(v):
            v = abs(v)
            d_ = int(v)
            m_ = int((v - d_) * 60)
            return (float(d_), float(m_), round((v - d_ - m_ / 60) * 3600, 2))
        ex[0x8825] = {1: "N" if lat >= 0 else "S", 2: dms(lat), 3: "E" if lon >= 0 else "W", 4: dms(lon)}
    return ex


class PhotoLibrary:
    """Realistic room photos (data/photo_library/manifest.json): which crop of which photo each demo
    college submits, and the sample uploads. Colleges not in the manifest get drawn rooms."""

    def __init__(self, libdir: Path):
        self.dir = libdir
        man = libdir / "manifest.json"
        self.man = json.loads(man.read_text()) if man.exists() else {}

    def rooms_for(self, code: str) -> list[dict] | None:
        return (self.man.get("demo") or {}).get(code)

    def test_uploads(self) -> list[dict]:
        return self.man.get("test_upload") or []

    def source(self, name: str) -> Path:
        return self.dir / self.man["sources"][name]


def real_photo(src: Path, path: Path, crop=(0.0, 1.0), blur: bool = False, dark: bool = False, exif=None,
               width: int = 800):
    """Save a crop of a library photo as a phone-style JPEG with our EXIF (original metadata dropped)."""
    img = Image.open(src).convert("RGB")
    w, h = img.size
    img = img.crop((round(crop[0] * w), 0, round(crop[1] * w), h))
    img = img.resize((width, round(width * img.height / img.width)), Image.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=200, threshold=1))   # offset the upscaling softness
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(7))
    if dark:
        img = ImageEnhance.Brightness(img).enhance(0.18)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=90, **({"exif": exif} if exif is not None else {}))


def room_photo(path: Path, kind: str, seed: int, blur: bool = False, dark: bool = False, exif=None):
    """A drawn room (used for colleges without realistic photos in the photo library)."""
    rnd = random.Random(seed)
    wall, furn, accent = ROOM_PALETTES[kind]
    jitter = lambda c: tuple(max(0, min(255, v + rnd.randint(-18, 18))) for v in c)
    img = Image.new("RGB", (960, 640), jitter(wall))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 400, 960, 640], fill=jitter((150, 140, 125)))           # floor
    for i in range(rnd.randint(2, 4)):                                     # windows
        x = 60 + i * rnd.randint(200, 240)
        d.rectangle([x, 70, x + 130, 230], fill=jitter((190, 215, 235)), outline=(80, 80, 80), width=4)
    if kind == "classroom":
        d.rectangle([300, 90, 680, 260], fill=jitter(accent))               # board
        for r in range(3):
            for col in range(rnd.randint(4, 6)):
                x, y = 80 + col * 150 + r * 12, 420 + r * 70
                d.rectangle([x, y, x + 110, y + 28], fill=jitter(furn))
    elif kind == "lab":
        for r in range(2):
            y = 380 + r * 120
            d.rectangle([60, y, 900, y + 40], fill=jitter(furn))
            for col in range(rnd.randint(5, 7)):
                x = 90 + col * 125
                d.rectangle([x, y - 70, x + 80, y - 8], fill=jitter(accent), outline=(10, 10, 10), width=3)
    else:
        for col in range(rnd.randint(5, 7)):
            x = 40 + col * 135
            d.rectangle([x, 120, x + 110, 400], fill=jitter(furn))
            for sh in range(5):
                yy = 140 + sh * 52
                for b in range(8):
                    d.rectangle([x + 6 + b * 13, yy, x + 16 + b * 13, yy + 40],
                                fill=jitter((rnd.randint(60, 200), rnd.randint(40, 160), rnd.randint(40, 160))))
    # noise/texture so photos are not perfectly flat
    import numpy as np
    arr = np.asarray(img).astype(np.int16)
    arr = np.clip(arr + np.random.default_rng(seed).normal(0, 7, arr.shape), 0, 255).astype("uint8")
    img = Image.fromarray(arr)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(9))
    if dark:
        img = ImageEnhance.Brightness(img).enhance(0.18)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=88, **({"exif": exif} if exif is not None else {}))


def reused_photo(src: Path, dst: Path, seed: int):
    """Same photo, lightly cropped/brightened — as if re-submitted as another room."""
    img = Image.open(src)
    rnd = random.Random(seed)
    w, h = img.size
    img = img.crop((rnd.randint(5, 25), rnd.randint(5, 25), w - rnd.randint(5, 25), h - rnd.randint(5, 25))).resize((w, h))
    exif = img.getexif()                                   # the camera metadata travels with the copy
    img = ImageEnhance.Brightness(img).enhance(rnd.uniform(1.05, 1.15))
    img.save(dst, "JPEG", quality=85, exif=exif)


# ------------------------------------------------------------------ PDF digital signatures (PAdES)

def make_signing_ca(sources: list[str], keydir: Path, trustdir: Path) -> dict:
    """A demo root CA (public cert -> trust store) and one signing certificate per issuing authority.
    Real deployments trust the CCA India root / authority certificates instead."""
    import datetime as dt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    def name(cn):
        return x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
                          x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Demo Trust Services (synthetic)"),
                          x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    def ku(ca):
        return x509.KeyUsage(digital_signature=True, content_commitment=not ca, key_encipherment=False, data_encipherment=False,
                             key_agreement=False, key_cert_sign=ca, crl_sign=ca, encipher_only=False, decipher_only=False)

    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    rk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root = (x509.CertificateBuilder().subject_name(name("Demo Root CA (synthetic)")).issuer_name(name("Demo Root CA (synthetic)"))
            .public_key(rk.public_key()).serial_number(x509.random_serial_number()).not_valid_before(start)
            .not_valid_after(start + dt.timedelta(days=3650)).add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(ku(True), critical=True).sign(rk, hashes.SHA256()))
    keydir.mkdir(parents=True, exist_ok=True)
    trustdir.mkdir(parents=True, exist_ok=True)
    pem = serialization.Encoding.PEM
    (trustdir / "demo_root_ca.pem").write_bytes(root.public_bytes(pem))
    names = {"affiliating_university": "Registrar, State Technical University (demo)"}
    out = {}
    for src in sources:
        sk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = (x509.CertificateBuilder().subject_name(name(names.get(src, src))).issuer_name(root.subject).public_key(sk.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(start).not_valid_after(start + dt.timedelta(days=1825))
                .add_extension(ku(False), critical=True).sign(rk, hashes.SHA256()))
        kp, cp = keydir / f"{src}.sig.key", keydir / f"{src}.sig.pem"
        kp.write_bytes(sk.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cp.write_bytes(leaf.public_bytes(pem))
        out[src] = (str(kp), str(cp), str(trustdir / "demo_root_ca.pem"))
    return out


def sign_pdf(path: Path, creds: tuple, reason: str):
    """Apply a PAdES signature in place, as the issuing authority would."""
    import logging
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    logging.getLogger("pyhanko").setLevel(logging.ERROR)
    key, cert, root = creds
    signer = signers.SimpleSigner.load(key, cert, ca_chain_files=(root,))
    with open(path, "rb") as f:
        out = signers.sign_pdf(IncrementalPdfFileWriter(f), signers.PdfSignatureMetadata(field_name="IssuerSignature", reason=reason,
                               location="India (demo)"), signer=signer)
    path.write_bytes(out.getbuffer())


def edit_after_signing(path: Path, old_value: str, new_value: str):
    """Change a value the way a PDF editor does — rewrite it in the page's content stream — and append
    the result as an incremental update. The signature stays mathematically valid for the original
    revision, but no longer covers the file."""
    from pypdf import PdfWriter
    w = PdfWriter(str(path), incremental=True)
    page = w.pages[0]
    content = page.get_contents()
    data = content.get_data()
    assert old_value.encode() in data, "value not found in content stream"
    content.set_data(data.replace(old_value.encode(), new_value.encode(), 1))
    page.replace_contents(content)
    w.add_metadata({"/ModDate": "D:20260918113000+05'30'", "/Producer": "PDF-XChange Editor 10.2"})
    with open(path, "wb") as f:
        w.write(f)
