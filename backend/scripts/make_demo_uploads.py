"""Build demo_uploads/: ready-to-upload files for every application type, for recording the demo.

    cd backend && python scripts/make_demo_uploads.py

Everything is for the `coromandel` account (Coromandel Institute of Technology), so a set uploaded as
listed comes out clean. 7_EoA_with_problems/ is the same application with deliberate mistakes.
Run again after generate_synthetic.py (the documents are copied from the regenerated demo data).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth  # noqa: E402

OUT = ROOT.parent / "demo_uploads"
DEMO = ROOT / "data" / "demo_docs" / "INST-TN-0412"
CERTS = ROOT.parent / "synthetic_test_certificates"

# file name in the folder -> (source file, upload slot as the app labels it)
DOC = {
    "affidavit":       (DEMO / "affidavit.pdf", "Affidavit / Undertaking"),
    "fire_noc":        (DEMO / "fire_noc.pdf", "Fire Safety NOC"),
    "building":        (DEMO / "building_completion.pdf", "Building Completion / Occupancy Certificate"),
    "pollution":       (DEMO / "pollution_consent.pdf", "Pollution Control Board Consent"),
    "nba":             (DEMO / "nba_accreditation.pdf", "NBA Accreditation Certificate"),
    "university":      (DEMO / "university_affiliation.pdf", "University Affiliation Letter"),
    "fee_receipt":     (DEMO / "ter_receipt.pdf", "Processing Fee (TER) Payment Receipt"),
    "land_deed":       (CERTS / "11_land_deed_valid.pdf", "Registered Land Sale / Lease Deed"),
    "town_planning":   (CERTS / "12_town_planning_noc_valid.pdf", "Town Planning Authority / Land Use NOC"),
    "balance_sheet":   (CERTS / "13_balance_sheet_valid.pdf", "Audited Balance Sheet & Financial Viability"),
    "state_govt_noc":  (CERTS / "15_state_govt_noc_valid.pdf", "State Government NOC"),
    "trust_resolution": (CERTS / "16_trust_resolution_valid.pdf", "Society / Trust Resolution"),
}

# photos/<room>_<number>.jpg: pick <room> in the room-type list and type <number> as the room
PHOTOS = [("classroom_101", "classroom", (0.0, 0.5)), ("classroom_102", "classroom", (0.5, 1.0)),
          ("lab_1", "computer_lab", (0.0, 0.5)), ("lab_2", "computer_lab", (0.5, 1.0)),
          ("library_1", "library", (0.0, 0.5)), ("library_2", "library", (0.5, 1.0)),
          ("seminar-hall_1", "seminar_hall", (0.0, 0.5)), ("seminar-hall_2", "seminar_hall", (0.5, 1.0))]

SETS = [
    ("1_Extension_of_Approval", "EOA", ["affidavit", "fire_noc", "building", "pollution", "university", "fee_receipt"], 4),
    ("2_Increase_in_Intake", "INTAKE_INCREASE", ["affidavit", "fire_noc", "building", "nba"], 6),
    ("3_New_Programme", "NEW_PROGRAMME", ["affidavit", "university", "state_govt_noc", "building", "fire_noc"], 6),
    ("4_Change_of_Name", "CHANGE_OF_NAME", ["affidavit", "trust_resolution", "state_govt_noc", "university"], 0),
    ("5_New_Institution", "NEW_INSTITUTION",
     ["affidavit", "land_deed", "town_planning", "building", "fire_noc", "balance_sheet"], 8),
    ("6_Course_Closure", "COURSE_CLOSURE", ["affidavit", "trust_resolution", "university"], 0),
]

# deliberate mistakes: (file name, source, slot to upload it into, what Pramaan should say)
PROBLEMS = [
    ("affidavit.pdf", DEMO / "affidavit.pdf", "Affidavit / Undertaking", None),
    ("fire_noc_EXPIRED.pdf", None, "Fire Safety NOC", "expired NOC"),          # built below
    ("pollution_consent_IN_BUILDING_SLOT.pdf", DEMO / "pollution_consent.pdf",
     "Building Completion / Occupancy Certificate", "wrong document in this slot"),
    ("pollution.pdf", DEMO / "pollution_consent.pdf", "Pollution Control Board Consent", None),
    ("university.pdf", DEMO / "university_affiliation.pdf", "University Affiliation Letter", None),
    ("fee_receipt.pdf", DEMO / "ter_receipt.pdf", "Processing Fee (TER) Payment Receipt", None),
]


EXPIRED_NOC = {"certificate_no": "FSN/TN/2023/31877", "institution_name": "Coromandel Institute of Technology",
               "issue_date": "01-04-2023", "valid_until": "31-03-2026", "built_up_area_sqm": "12,050"}


def make_expired_noc(path: Path):
    """Coromandel's own fire NOC, genuinely issued (on the authority's record) but expired on 31-03-2026."""
    from datetime import datetime
    synth.build_pdf(path, "fire_noc", EXPIRED_NOC, datetime(2023, 4, 1), seed=811)
    entry = {"certificate_no": EXPIRED_NOC["certificate_no"], "institution_name": EXPIRED_NOC["institution_name"],
             "valid_until": "2026-03-31", "status": "VALID"}
    for f, key in [(ROOT / "data" / "registry_additions.json", "authority_registry"),
                   (ROOT / "data" / "authority_registry.json", None)]:   # survives regeneration / works now
        data = json.loads(f.read_text())
        reg = data.setdefault(key, {}) if key else data
        reg.setdefault("state_fire_services", {})[EXPIRED_NOC["certificate_no"]] = entry
        f.write_text(json.dumps(data, indent=2))


def main():
    OUT.mkdir(exist_ok=True)
    for old in OUT.iterdir():                     # rebuild the sets; keep the hand-written README.md
        if old.is_dir():
            shutil.rmtree(old)
    (OUT / "photos").mkdir()
    lib = synth.PhotoLibrary(ROOT / "data" / "photo_library")
    rec = json.loads((ROOT / "data" / "aicte_records.json").read_text())["institutions"]["INST-TN-0412"]
    for i, (stem, src, crop) in enumerate(PHOTOS):          # GPS fix on Coromandel's registered campus
        gps = (rec["latitude"] + 0.0004 * (i - 4), rec["longitude"] + 0.0003 * (i - 4))
        synth.real_photo(lib.source(src), OUT / "photos" / f"{stem}.jpg", crop, exif=synth.camera_exif(900 + i, *gps))
    for folder, _cat, docs, _n in SETS:
        d = OUT / folder
        d.mkdir()
        for name in docs:
            shutil.copy(DOC[name][0], d / f"{name}.pdf")
    d = OUT / "7_EoA_with_problems"
    d.mkdir()
    make_expired_noc(d / "fire_noc_EXPIRED.pdf")
    for name, src, _slot, _why in PROBLEMS:
        if src:
            shutil.copy(src, d / name)
    # optional swap: another college's certificate (Sahyadri's) uploaded as Coromandel's
    shutil.copy(CERTS / "04_fire_noc_expired.pdf", d / "fire_noc_OF_ANOTHER_COLLEGE.pdf")
    print("demo_uploads/ written:", sum(1 for _ in OUT.rglob("*.*")), "files")


if __name__ == "__main__":
    main()
