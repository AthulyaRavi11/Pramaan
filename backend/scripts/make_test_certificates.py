"""Sample certificates for the newer application categories (New institution, Change of name,
New programme, Course closure), written to synthetic_test_certificates/ for hand-testing uploads.

    cd backend && python scripts/make_test_certificates.py

Each certificate is also registered with its (demo) issuing authority in data/registry_additions.json,
which generate_synthetic.py merges into authority_registry.json. All values are synthetic.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth  # noqa: E402

OUT = ROOT.parent / "synthetic_test_certificates"
ADDITIONS = ROOT / "data" / "registry_additions.json"
NAME = "Coromandel Institute of Technology"
SURVEY = "SY-402/1A, SY-402/1B"            # same land as 11_land_deed_valid.pdf

CERTS = [
    ("12_town_planning_noc_valid", "town_planning_noc", datetime(2019, 3, 2),
     {"certificate_no": "TP/LU/2019/3318", "institution_name": NAME, "survey_number": SURVEY,
      "land_category": "Institutional", "issue_date": "02-03-2019"},
     ("state_land_records", "TP/LU/2019/3318",
      {"certificate_no": "TP/LU/2019/3318", "survey_number": SURVEY, "institution_name": NAME, "status": "VALID"})),
    ("13_balance_sheet_valid", "balance_sheet", datetime(2026, 7, 30),
     {"institution_name": NAME, "financial_year": "2025-26", "net_worth": "Rs. 48,75,00,000",
      "ca_reg_no": "214567", "udin": "25214567ABCDEF1234"},
     ("digilocker_nad", "25214567ABCDEF1234",
      {"udin": "25214567ABCDEF1234", "institution_name": NAME, "financial_year": "2025-26", "status": "VALID"})),
    ("14_balance_sheet_udin_not_found", "balance_sheet", datetime(2026, 7, 30),
     {"institution_name": NAME, "financial_year": "2025-26", "net_worth": "Rs. 61,20,00,000",
      "ca_reg_no": "214567", "udin": "25214567ZZZZZZ9999"}, None),
    ("15_state_govt_noc_valid", "state_govt_noc", datetime(2026, 5, 12),
     {"certificate_no": "HED/2026/118", "institution_name": NAME, "issue_date": "12-05-2026"}, None),
    ("16_trust_resolution_valid", "trust_resolution", datetime(2026, 7, 10),
     {"institution_name": NAME, "proposed_name": "Coromandel Institute of Technology and Science",
      "issue_date": "10-07-2026"}, None),
]


# Room photos for hand-testing uploads: realistic photos from data/photo_library (manifest "test_upload"),
# with phone-style EXIF and a GPS fix on Coromandel's registered campus.
def make_photos():
    lib = synth.PhotoLibrary(ROOT / "data" / "photo_library")
    rec = json.loads((ROOT / "data" / "aicte_records.json").read_text())["institutions"].get("INST-TN-0412", {})
    lat, lon = rec.get("latitude"), rec.get("longitude")
    for i, p in enumerate(lib.test_uploads()):
        gps = (lat + 0.0007 * (i - 1.5), lon + 0.0005 * (i - 1.5)) if lat and lon else (None, None)
        synth.real_photo(lib.source(p["source"]), OUT / f"{p['stem']}.jpg", p.get("crop", (0, 1)),
                         exif=synth.camera_exif(700 + i, *gps))
        print(f"  {p['stem']}.jpg  ({p['source']})")


def main():
    make_photos()
    additions = json.loads(ADDITIONS.read_text()) if ADDITIONS.exists() else {"authority_registry": {}}
    for i, (stem, dtype, issued, values, reg) in enumerate(CERTS):
        pdf = OUT / f"{stem}.pdf"
        synth.build_pdf(pdf, dtype, values, issued, seed=500 + i)
        import pypdfium2 as pdfium
        pdfium.PdfDocument(str(pdf))[0].render(scale=2).to_pil().save(OUT / f"{stem}.png")
        if reg:
            source, ref, rec = reg
            additions.setdefault("authority_registry", {}).setdefault(source, {})[ref] = rec
        print(f"  {stem}.pdf / .png")
    ADDITIONS.write_text(json.dumps(additions, indent=2))
    print("Registry entries saved to", ADDITIONS.relative_to(ROOT.parent))


if __name__ == "__main__":
    main()
