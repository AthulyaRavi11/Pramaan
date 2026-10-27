"""Generate the SYNTHETIC dataset: mock AICTE records, mock issuing-authority
registries, authority signing keys, certificates (clean / faulty / tampered),
infrastructure photos, and a ground-truth manifest for evaluation.

    python scripts/generate_synthetic.py            # 3 demo institutions
    python scripts/generate_synthetic.py --batch 30 # + 30 random apps for evaluation

Everything is fictional. No real institution, authority or person is represented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
KEYDIR = ROOT / "scripts" / "_demo_signing_keys"     # private keys: demo only, never ship real keys

APP_DATE = "20-10-2026"
AY = "2027-28"
SIGNING_SOURCES = ["state_fire_services", "nba_registry"]

# fault -> rule ids the platform is expected to raise (used by evaluate.py)
EXPECTED = {
    "expired_fire": ["EOA-VAL-01", "VER-EXPIRED"],
    "tampered_fire": ["ANOM-FONT", "ANOM-META", "VER-MISMATCH"],
    "old_affidavit": ["EOA-VAL-04"],
    "missing_building": ["EOA-DOC-03"],
    "wrong_slot_building": ["DOC-CLASS", "EOA-DOC-03"],
    "intake_exceeds": ["EOA-REC-06"],
    "ter_unpaid": ["EOA-REC-03"],
    "open_deficiency": ["EOA-REC-04"],
    "copied_nba": ["ANOM-DUP"],
    "id_mismatch_affidavit": ["EOA-CON-02"],
    "dup_photos": ["INFRA-PHOTO-DUP"],
    "blurry_photo": ["INFRA-PHOTO-BLUR"],
    "missing_library_photo": ["INFRA-PHOTO-COVER"],
    "fake_ter": ["VER-MISMATCH"],
    "ay_mismatch_univ": ["EOA-CON-03"],
    "area_mismatch": ["EOA-CON-04"],
    "low_faculty": ["INFRA-FACULTY"],
    "edited_after_signing": ["VER-SIGNATURE", "VER-REPOSITORY"],
    "faculty_record_mismatch": ["EOA-REC-07"],
    "cloned_stamp": ["ANOM-COPYMOVE"],
}
BATCH_FAULTS = [f for f in EXPECTED if f != "copied_nba"]


def d(s):  # dd-mm-yyyy -> datetime
    return datetime.strptime(s, "%d-%m-%Y")


def iso(s):
    return d(s).date().isoformat()


class World:
    def __init__(self, keys, sig_creds=None):
        self.keys = keys
        self.sig = sig_creds or {}
        self.records = {"institutions": {}, "payment_transactions": {}}
        self.registry = {s: {} for s in ["state_fire_services", "state_pollution_board", "nba_registry", "affiliating_university",
                                         "municipal_records"]}
        self.photos = synth.PhotoLibrary(DATA / "photo_library")    # realistic photos for the demo colleges


def make_application(w: World, inst: dict, faults: set, outdir: Path, rnd: random.Random, copy_nba_from: Path | None = None):
    """Creates records, registry entries and files for one application. Returns manifest entry."""
    name, pid, code = inst["name"], inst["permanent_id"], inst["code"]
    seed = rnd.randint(0, 10**6)
    progs = inst["programmes"]
    approved = [{"code": p["code"], "name": p["name"], "level": p["level"], "intake": p["intake"]} for p in progs]
    requested = [dict(p) for p in approved]
    if "intake_exceeds" in faults:
        requested[0]["intake"] += 60
    total = sum(p["intake"] for p in requested)
    area = float(rnd.randrange(8000, 16000, 50))
    form = {"institution_name": name, "aicte_permanent_id": pid, "academic_year": AY, "application_date": APP_DATE,
            "built_up_area_sqm": area if "area_mismatch" not in faults else area + 1500,
            "classrooms": rnd.randint(10, 18), "labs": rnd.randint(10, 18),
            "faculty_count": max(10, total // 12) if "low_faculty" not in faults else max(5, total // 28),
            "programmes": requested}

    # registered campus location (used to check photo geo-tags); a city in the state plus a small offset
    # (own random stream, so certificate and transaction numbers stay the same as before geo-tags were added)
    geo = random.Random(code)
    clat, clon = STATE_CITY[inst["state_code"]]
    campus = (round(clat + geo.uniform(-0.08, 0.08), 4), round(clon + geo.uniform(-0.08, 0.08), 4))
    w.records["institutions"][code] = {
        "permanent_id": pid, "name": name, "state": inst["state"], "established": inst["established"],
        "approved_programmes": approved,
        "previous_eoa": {"academic_year": "2026-27", "letter_no": f"F.No.EOA/{rnd.randint(10000, 99999)}/2026", "status": "GRANTED"},
        "open_deficiencies": ["Library area shortfall noted in 2025-26 scrutiny"] if "open_deficiency" in faults else [],
        "ter_payments": {AY: "PENDING" if "ter_unpaid" in faults else "PAID", "2026-27": "PAID"},
        "faculty_on_record": int(form["faculty_count"] * 0.7) if "faculty_record_mismatch" in faults else form["faculty_count"],
        "application_history": [
            {"academic_year": "2026-27", "type": "Extension of Approval", "ref": f"EOA-2026-{rnd.randint(10**5, 10**6 - 1)}",
             "outcome": "Approved", "remarks": ""},
            {"academic_year": "2025-26", "type": "Extension of Approval", "ref": f"EOA-2025-{rnd.randint(10**5, 10**6 - 1)}",
             "outcome": "Approved with conditions" if "open_deficiency" in faults else "Approved",
             "remarks": "Library area shortfall to be closed within one year" if "open_deficiency" in faults else ""},
            {"academic_year": str(inst["established"]) + "-" + str(inst["established"] + 1)[2:], "type": "New institution",
             "ref": f"NEW-{inst['established']}-{rnd.randint(10**5, 10**6 - 1)}", "outcome": "Approved", "remarks": ""},
        ],
        "latitude": campus[0], "longitude": campus[1],
    }

    docs, truth = [], {}

    def add(fname, dtype, fields_true, tag=None):
        docs.append({"file": fname, "declared_type": dtype, "tag": tag})
        if fields_true is not None:
            truth[fname] = fields_true

    outdir.mkdir(parents=True, exist_ok=True)

    # --- affidavit (scanned -> OCR path)
    aff_date = "02-01-2026" if "old_affidavit" in faults else f"{rnd.randint(1, 28):02d}-0{rnd.randint(7, 9)}-2026"
    aff_pid = pid
    if "id_mismatch_affidavit" in faults:   # transpose two digits (a typical copy error); ensure it really changes
        aff_pid = pid[:-2] + pid[-1] + pid[-2] if pid[-1] != pid[-2] else pid[:-1] + str((int(pid[-1]) + 3) % 10)
    aff = {"institution_name": name, "aicte_permanent_id": aff_pid, "academic_year": AY, "issue_date": aff_date,
           "notary_reg_no": f"{inst['state_code']}/NOT/{rnd.randint(1000, 99999):05d}"}
    synth.build_scanned_pdf(outdir / "affidavit.pdf", "affidavit", aff, d(aff_date), seed=seed + 1,
                            quality="poor" if inst.get("poor_scan") else "good")
    add("affidavit.pdf", "affidavit", {**aff, "issue_date": iso(aff_date)})

    # --- fire NOC (signed QR)
    fire_no = f"FSN/{inst['state_code']}/2024/{rnd.randint(10000, 99999)}"
    fire_issue = "01-04-2024"
    fire_valid_true = "31-03-2026" if faults & {"expired_fire", "tampered_fire"} else f"31-03-20{rnd.randint(28, 30)}"
    fire = {"certificate_no": fire_no, "institution_name": name, "issue_date": fire_issue, "valid_until": fire_valid_true,
            "built_up_area_sqm": f"{int(area):,}"}
    signed = {"certificate_no": fire_no, "institution_name": name, "valid_until": iso(fire_valid_true)}
    qr = synth.signed_qr_payload(w.keys["state_fire_services"], "state_fire_services", fire_no, signed)
    w.registry["state_fire_services"][fire_no] = {**signed, "status": "ACTIVE" if "expired" not in str(faults) else "EXPIRED"}
    if "tampered_fire" in faults:
        synth.build_tampered_pdf(outdir / "fire_noc.pdf", "fire_noc", fire, "valid_until", "31-03-2028",
                                 d(fire_issue), datetime(2026, 9, 14, 16, 2), qr, seed=seed + 2)
        add("fire_noc.pdf", "fire_noc", {**fire, "valid_until": "2028-03-31", "issue_date": iso(fire_issue),
                                         "built_up_area_sqm": area})
    else:
        synth.build_pdf(outdir / "fire_noc.pdf", "fire_noc", fire, d(fire_issue), qr, seed=seed + 2)
        add("fire_noc.pdf", "fire_noc", {**fire, "valid_until": iso(fire_valid_true), "issue_date": iso(fire_issue),
                                         "built_up_area_sqm": area})

    # --- building completion (or wrong document in its slot)
    bc = {"certificate_no": f"MC/OC/{rnd.randint(2010, 2020)}/{rnd.randint(100, 999)}", "institution_name": name,
          "issue_date": f"{rnd.randint(1, 28):02d}-0{rnd.randint(1, 9)}-2015", "built_up_area_sqm": f"{int(area):,}"}
    pol = {"certificate_no": f"PCB/CTO/{rnd.randint(10000, 99999)}", "institution_name": name, "issue_date": "15-05-2025",
           "valid_until": "31-03-2028"}
    w.registry["state_pollution_board"][pol["certificate_no"]] = {"certificate_no": pol["certificate_no"], "valid_until": iso(pol["valid_until"]),
                                                                   "institution_name": name, "status": "ACTIVE"}
    if "wrong_slot_building" in faults:
        synth.build_pdf(outdir / "building_completion.pdf", "pollution_noc", pol, d(pol["issue_date"]), seed=seed + 3)
        add("building_completion.pdf", "building_completion", None)
    elif "missing_building" not in faults:
        w.registry["municipal_records"][bc["certificate_no"]] = {"certificate_no": bc["certificate_no"], "institution_name": name,
                                                                "issue_date": iso(bc["issue_date"]), "status": "VALID"}
        synth.build_pdf(outdir / "building_completion.pdf", "building_completion", bc, d(bc["issue_date"]), seed=seed + 3)
        add("building_completion.pdf", "building_completion", {**bc, "issue_date": iso(bc["issue_date"]), "built_up_area_sqm": area})

    # --- pollution consent
    synth.build_pdf(outdir / "pollution_consent.pdf", "pollution_noc", pol, d(pol["issue_date"]), seed=seed + 4,
                    cloned_stamp="cloned_stamp" in faults)
    add("pollution_consent.pdf", "pollution_noc", {**pol, "issue_date": iso(pol["issue_date"]), "valid_until": iso(pol["valid_until"])})

    # --- NBA accreditation (signed QR) or a copy of someone else's
    if "copied_nba" in faults and copy_nba_from:
        shutil.copy(copy_nba_from, outdir / "nba_accreditation.pdf")
        add("nba_accreditation.pdf", "nba_accreditation", None)
    elif inst.get("nba", True):
        nba_no = f"NBA/ACC/2023/{rnd.randint(1000, 9999)}"
        nba = {"certificate_no": nba_no, "institution_name": name, "programme": progs[0]["name"], "valid_until": "30-06-2028"}
        sig = {"certificate_no": nba_no, "institution_name": name, "valid_until": "2028-06-30"}
        w.registry["nba_registry"][nba_no] = {**sig, "programme": progs[0]["name"], "status": "ACTIVE"}
        synth.build_pdf(outdir / "nba_accreditation.pdf", "nba_accreditation", nba, datetime(2023, 7, 1),
                        synth.signed_qr_payload(w.keys["nba_registry"], "nba_registry", nba_no, sig), seed=seed + 5)
        add("nba_accreditation.pdf", "nba_accreditation", {**nba, "valid_until": "2028-06-30"})

    # --- university affiliation
    uni_no = f"UNIV/AFF/{rnd.randint(1000, 9999)}/2026"
    uni_ay = "2026-27" if faults & {"ay_mismatch_univ", "edited_after_signing"} else AY
    uni = {"certificate_no": uni_no, "institution_name": name, "academic_year": uni_ay, "issue_date": "10-08-2026"}
    upath = outdir / "university_affiliation.pdf"
    synth.build_pdf(upath, "university_affiliation", uni, d("10-08-2026"), seed=seed + 6)
    if w.sig.get("affiliating_university"):          # the university signs its letters digitally (PAdES)
        synth.sign_pdf(upath, w.sig["affiliating_university"], "Affiliation granted by the university")
    w.registry["affiliating_university"][uni_no] = {"certificate_no": uni_no, "academic_year": uni_ay, "institution_name": name,
                                                    "status": "ACTIVE", "file_sha256": hashlib.sha256(upath.read_bytes()).hexdigest()}
    if "edited_after_signing" in faults:             # year changed to match the application, after the university signed
        synth.edit_after_signing(upath, uni_ay, AY)
        uni = {**uni, "academic_year": AY}
    add("university_affiliation.pdf", "university_affiliation", {**uni, "issue_date": "2026-08-10"})

    # --- TER receipt
    txn = f"AICTE{rnd.randint(10**9, 10**10 - 1)}"
    if "fake_ter" not in faults:
        w.records["payment_transactions"][txn] = {"transaction_id": txn, "permanent_id": pid, "academic_year": AY,
                                                  "status": "SUCCESS"}
    ter = {"transaction_id": txn, "institution_name": name, "aicte_permanent_id": pid, "payment_date": "05-10-2026",
           "amount": "Rs. 1,50,000 (demo)"}
    synth.build_pdf(outdir / "ter_receipt.pdf", "ter_receipt", ter, d("05-10-2026"), seed=seed + 7)
    add("ter_receipt.pdf", "ter_receipt", {k: v for k, v in ter.items() if k != "amount"} | {"payment_date": "2026-10-05"})

    # --- photos
    rooms = [("classroom", "classroom-101"), ("classroom", "classroom-102"), ("lab", "lab-cse-1"), ("lab", "lab-ece-1"),
             ("library", "library-main")]
    if "missing_library_photo" in faults:
        rooms = rooms[:4]
    planned = {r["tag"]: r for r in (w.photos.rooms_for(inst["code"]) or [])}
    if planned:                        # demo college: realistic photos, rooms as listed in the photo library
        rooms = [(t.split("-")[0], t) for t in planned]
    for i, (kind, tag) in enumerate(rooms):
        fn = f"photo_{tag}.jpg"
        if "dup_photos" in faults and tag == "lab-ece-1":
            synth.reused_photo(outdir / "photo_lab-cse-1.jpg", outdir / fn, seed + 30)
        else:
            # phone photo taken on campus: camera EXIF plus a GPS fix within a few hundred metres
            gps = (campus[0] + geo.uniform(-0.002, 0.002), campus[1] + geo.uniform(-0.002, 0.002))
            exif = synth.camera_exif(seed + 40 + i, *gps)
            blur = "blurry_photo" in faults and i == 1
            p = planned.get(tag)
            if p and p.get("source"):
                synth.real_photo(w.photos.source(p["source"]), outdir / fn, p.get("crop", (0, 1)), blur=blur, exif=exif)
            else:
                synth.room_photo(outdir / fn, kind, seed + 20 + i, blur=blur, exif=exif)
        add(fn, "infra_photo", None, tag)

    expected = sorted({r for f in faults for r in EXPECTED.get(f, [])})
    return {"institution_id": code, "category": "EOA", "form": form, "dir": str(outdir.relative_to(ROOT)),
            "documents": docs, "faults": sorted(faults), "expected_rules": expected, "truth": truth}


DEMO = [
    {"code": "INST-TN-0412", "name": "Coromandel Institute of Technology", "permanent_id": "1-4412870301",
     "state": "Tamil Nadu (demo)", "state_code": "TN", "established": 2004, "user": "coromandel",
     "programmes": [{"code": "BE-CSE", "name": "B.E. Computer Science and Engineering", "level": "UG_ENGINEERING", "intake": 120},
                    {"code": "BE-ECE", "name": "B.E. Electronics and Communication Engineering", "level": "UG_ENGINEERING", "intake": 60},
                    {"code": "BE-MECH", "name": "B.E. Mechanical Engineering", "level": "UG_ENGINEERING", "intake": 60},
                    {"code": "ME-CSE", "name": "M.E. Computer Science and Engineering", "level": "PG_ENGINEERING", "intake": 18}],
     "faults": set()},
    {"code": "INST-MH-1187", "name": "Sahyadri College of Engineering", "permanent_id": "1-3398120455",
     "state": "Maharashtra (demo)", "state_code": "MH", "established": 2009, "user": "sahyadri", "nba": False,
     "programmes": [{"code": "BE-CSE", "name": "B.E. Computer Engineering", "level": "UG_ENGINEERING", "intake": 120},
                    {"code": "BE-IT", "name": "B.E. Information Technology", "level": "UG_ENGINEERING", "intake": 60},
                    {"code": "BE-CIVIL", "name": "B.E. Civil Engineering", "level": "UG_ENGINEERING", "intake": 60}],
     "faults": {"expired_fire", "old_affidavit", "wrong_slot_building", "intake_exceeds", "ter_unpaid", "open_deficiency",
                "ay_mismatch_univ", "low_faculty", "blurry_photo", "missing_library_photo", "faculty_record_mismatch"}},
    {"code": "INST-UP-2290", "name": "Ganga Valley Institute of Engineering", "permanent_id": "1-5520771190",
     "state": "Uttar Pradesh (demo)", "state_code": "UP", "established": 2012, "user": "gangavalley",
     "programmes": [{"code": "BTECH-CSE", "name": "B.Tech Computer Science and Engineering", "level": "UG_ENGINEERING", "intake": 180},
                    {"code": "BTECH-EE", "name": "B.Tech Electrical Engineering", "level": "UG_ENGINEERING", "intake": 60},
                    {"code": "MCA", "name": "Master of Computer Applications", "level": "MCA", "intake": 60}],
     "faults": {"tampered_fire", "copied_nba", "id_mismatch_affidavit", "dup_photos", "fake_ter", "edited_after_signing"}},
]

PREFIX = ["Vindhya", "Kaveri", "Narmada", "Aravalli", "Deccan", "Konkan", "Malabar", "Brahmaputra", "Satpura", "Nilgiri",
          "Godavari", "Tapti", "Mahanadi", "Chambal", "Sabari", "Pamba", "Tungabhadra", "Krishna Valley", "Shivalik", "Vaigai"]
SUFFIX = ["Institute of Technology", "College of Engineering", "Institute of Engineering and Technology", "Engineering College"]
STATE_CITY = {"TN": (13.0827, 80.2707), "KA": (12.9716, 77.5946), "MH": (18.5204, 73.8567), "UP": (26.8467, 80.9462),
              "KL": (9.9312, 76.2673), "GJ": (23.0225, 72.5714)}
STATES = [("TN", "Tamil Nadu"), ("KA", "Karnataka"), ("MH", "Maharashtra"), ("UP", "Uttar Pradesh"), ("KL", "Kerala"), ("GJ", "Gujarat")]


def random_inst(rnd, i):
    sc, sn = rnd.choice(STATES)
    name = f"{PREFIX[i % len(PREFIX)]} {rnd.choice(SUFFIX)}" + (f" {['North', 'South', 'East', 'West'][i // len(PREFIX)]}" if i >= len(PREFIX) else "")
    progs = [{"code": "BE-CSE", "name": "B.E. Computer Science and Engineering", "level": "UG_ENGINEERING", "intake": rnd.choice([60, 120, 180])},
             {"code": "BE-ECE", "name": "B.E. Electronics and Communication Engineering", "level": "UG_ENGINEERING", "intake": rnd.choice([60, 120])}]
    if rnd.random() < 0.5:
        progs.append({"code": "MCA", "name": "Master of Computer Applications", "level": "MCA", "intake": 60})
    return {"code": f"INST-{sc}-{9000 + i}", "name": name, "permanent_id": f"1-{rnd.randint(10**9, 10**10 - 1)}",
            "state": f"{sn} (demo)", "state_code": sc, "established": rnd.randint(1995, 2015), "user": f"inst{9000 + i}",
            "programmes": progs, "poor_scan": rnd.random() < 0.4}   # ~40% low-quality scans to stress OCR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=0, help="extra random applications for evaluation")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    rnd = random.Random(args.seed)

    for p in [DATA / "demo_docs", DATA / "eval_docs", DATA / "trust_store"]:
        shutil.rmtree(p, ignore_errors=True)
    w = World(synth.make_keys(SIGNING_SOURCES, KEYDIR, DATA / "trust_store"),
              synth.make_signing_ca(["affiliating_university"], KEYDIR, DATA / "trust_store"))

    manifest = []
    for inst in DEMO:
        copy_from = DATA / "demo_docs" / DEMO[0]["code"] / "nba_accreditation.pdf" if "copied_nba" in inst["faults"] else None
        m = make_application(w, inst, inst["faults"], DATA / "demo_docs" / inst["code"], rnd, copy_from)
        m["user"] = inst["user"]
        manifest.append(m)
        print(f"  demo  {inst['code']:14} {inst['name']:40} faults={sorted(inst['faults']) or 'none'}")

    batch = []
    for i in range(args.batch):
        inst = random_inst(rnd, i)
        k = rnd.choice([0, 1, 1, 2, 3])
        faults = set(rnd.sample(BATCH_FAULTS, k))
        if "tampered_fire" in faults:
            faults.discard("expired_fire")
        if faults & {"wrong_slot_building", "missing_building"}:
            faults.discard("area_mismatch")          # no completion certificate to compare the area against
        if "wrong_slot_building" in faults:
            faults.discard("missing_building")
        if "edited_after_signing" in faults:
            faults.discard("ay_mismatch_univ")
        if "low_faculty" in faults:
            faults.discard("faculty_record_mismatch")
        m = make_application(w, inst, faults, DATA / "eval_docs" / inst["code"], rnd)
        m["user"] = inst["user"]
        batch.append(m)
    if batch:
        print(f"  batch {len(batch)} applications, {sum(len(b['faults']) for b in batch)} injected faults")

    # Hand-made certificates in synthetic_test_certificates/ (see make_test_certificates.py) are registered
    # with their demo authorities through registry_additions.json, so they survive regeneration.
    extra = DATA / "registry_additions.json"
    if extra.exists():
        add = json.loads(extra.read_text())
        for source, entries in add.get("authority_registry", {}).items():
            reg = w.registry.setdefault(source, {})
            for ref, rec in entries.items():          # merge, so a generated record keeps its own fields
                cur = reg.setdefault(ref, {})
                shas = cur.get("valid_sha256s", []) + [x for x in rec.get("valid_sha256s", []) if x not in cur.get("valid_sha256s", [])]
                cur.update({k: v for k, v in rec.items() if k != "valid_sha256s"})
                if shas:
                    cur["valid_sha256s"] = shas
        w.records["payment_transactions"].update(add.get("payment_transactions", {}))

    (DATA / "aicte_records.json").write_text(json.dumps(w.records, indent=2))
    (DATA / "authority_registry.json").write_text(json.dumps(w.registry, indent=2))
    (DATA / "demo_manifest.json").write_text(json.dumps(manifest, indent=2, default=list))
    (DATA / "eval_manifest.json").write_text(json.dumps(batch, indent=2, default=list))
    print("Synthetic data written to", DATA)


if __name__ == "__main__":
    main()
