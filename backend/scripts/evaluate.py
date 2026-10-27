"""Evaluate the platform against the synthetic ground truth.

    python scripts/generate_synthetic.py --batch 30
    python scripts/seed.py --with-eval
    python scripts/evaluate.py

Metrics (as listed in the SIH26261 evaluation criteria):
  - document classification accuracy
  - field extraction accuracy (text-layer vs OCR)
  - issue / anomaly detection recall per injected fault type
  - unexpected high/medium flags (false alarms)
  - automated source-verification rate
  - average validation time
  - share of documents cleared without manual re-check (manual-effort proxy)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import config  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from generate_synthetic import EXPECTED  # noqa: E402

# faults the submission gate reports by naming the missing document
GATE_LABELS = {"missing_building": "Building Completion"}

# Manual-effort model. ASSUMED minutes per task for a scrutiny officer working by hand —
# replace with time-and-motion figures from AICTE before quoting the result.
MANUAL_MINUTES = {"read_document": 4, "confirm_with_authority": 15, "check_record": 3, "review_photo": 1.5, "review_flag": 3}

# legitimate consequences of a fault that are not false alarms
SIDE_EFFECTS = {
    "copied_nba": {"EOA-CON-01"},
    "intake_exceeds": {"INFRA-NORM", "INFRA-FACULTY"},
    "low_faculty": set(),
    "edited_after_signing": {"ANOM-META", "VER-MISMATCH"},   # the edit also leaves metadata traces; the registry year differs
    "faculty_record_mismatch": set(),
}


def norm(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return " ".join(v.upper().split())
    return v


def main():
    demo = json.loads((config.DATA_DIR / "demo_manifest.json").read_text())
    batch = json.loads((config.DATA_DIR / "eval_manifest.json").read_text())
    manifest = {m["institution_id"]: m for m in demo + batch}
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row

    cls_ok = cls_n = 0
    fld = {"text": [0, 0], "ocr": [0, 0]}
    fld_errors = []
    fault_hits = defaultdict(lambda: [0, 0])
    false_alarms, clean_apps, clean_with_alarm = [], 0, 0
    ver = defaultdict(int)
    times = []
    docs_total = docs_clear = 0
    flags_total = flags_explained = 0
    manual_before = manual_after = 0.0

    seed = config.STORAGE_DIR / "seed_results.json"
    blocked = {r["app_id"]: r["blocked_at_submission"] for r in (json.loads(seed.read_text()) if seed.exists() else [])
               if r.get("blocked_at_submission")}
    not_reached = []

    for a in con.execute("SELECT * FROM applications"):
        m = manifest.get(a["institution_id"])
        if not m or not a["report_json"]:
            continue
        rep = json.loads(a["report_json"])
        times.append(rep["timings"]["total_ms"])
        docs = {d["original_name"]: d for d in con.execute("SELECT * FROM documents WHERE application_id=? AND superseded=0", (a["id"],))}
        findings = [dict(f) for f in con.execute("SELECT * FROM findings WHERE application_id=?", (a["id"],))]
        raised = {f["rule_id"] for f in findings}

        # classification + extraction
        for dm in m["documents"]:
            if dm["declared_type"] == "infra_photo":
                continue
            d = docs[dm["file"]]
            true_type = "pollution_noc" if (dm["file"] == "building_completion.pdf" and "wrong_slot_building" in m["faults"]) \
                else dm["declared_type"]
            cls_n += 1
            cls_ok += d["detected_type"] == true_type
            truth = m["truth"].get(dm["file"])
            if not truth:
                continue
            ex = json.loads(d["extraction_json"])["fields"]
            bucket = "ocr" if d["ocr_used"] else "text"
            for k, tv in truth.items():
                fld[bucket][1] += 1
                got = (ex.get(k) or {}).get("normalized")
                if norm(got) == norm(tv):
                    fld[bucket][0] += 1
                else:
                    fld_errors.append({"doc": f"{a['institution_id']}/{dm['file']}", "field": k, "expected": tv, "got": got})

        # detection. An application the submission gate refused stays a draft: the gate message is itself the
        # detection of a missing document, and checks that only run after submission (AICTE records, etc.)
        # were never reached, so those faults are reported separately instead of counted as misses.
        gate_msg = blocked.get(a["id"])
        for fault in m["faults"]:
            exp = set(EXPECTED[fault])
            hit = exp <= raised
            if not hit and gate_msg:
                label = GATE_LABELS.get(fault)
                if label and label in gate_msg:
                    hit = True
                else:
                    not_reached.append({"app": a["institution_id"], "fault": fault})
                    continue
            fault_hits[fault][1] += 1
            fault_hits[fault][0] += hit
        allowed = {r for f in m["faults"] for r in EXPECTED[f]} | {r for f in m["faults"] for r in SIDE_EFFECTS.get(f, set())}
        unexpected = [f for f in findings if f["severity"] in ("high", "medium") and f["rule_id"] not in allowed]
        for f in unexpected:
            false_alarms.append({"app": a["institution_id"], "rule": f["rule_id"], "title": f["title"], "faults": m["faults"]})
        if not m["faults"]:
            clean_apps += 1
            clean_with_alarm += bool(unexpected)
        hm = [f for f in findings if f["severity"] in ("high", "medium")]
        flags_total += len(hm)
        flags_explained += len(hm) - len(unexpected)

        # verification + manual-effort proxy
        vs = list(con.execute("SELECT * FROM verifications WHERE application_id=?", (a["id"],)))
        for v in vs:
            ver[v["status"]] += 1
        flagged_docs = {f["document_id"] for f in findings if f["severity"] in ("high", "medium", "low")}
        for d in docs.values():
            if d["declared_type"] == "infra_photo":
                continue
            docs_total += 1
            dv = [v["status"] for v in vs if v["document_id"] == d["id"]]
            if d["id"] not in flagged_docs and dv and all(s == "VERIFIED" for s in dv):
                docs_clear += 1
        # manual effort: every document read and confirmed by hand, every record looked up, every photo viewed
        rep_checks = sum(1 for c in rep["checklist"] if c["type"] in ("record_match", "record_flag", "intake_within_approved"))
        n_docs = sum(1 for d in docs.values() if d["declared_type"] != "infra_photo")
        n_photos = sum(1 for d in docs.values() if d["declared_type"] == "infra_photo")
        manual_before += (n_docs * (MANUAL_MINUTES["read_document"] + MANUAL_MINUTES["confirm_with_authority"])
                          + rep_checks * MANUAL_MINUTES["check_record"] + n_photos * MANUAL_MINUTES["review_photo"])
        # with Pramaan: only routed confirmations and raised flags need a person
        routed = sum(1 for v in vs if v["status"] in ("MANUAL_REVIEW", "SOURCE_UNAVAILABLE", "PENDING"))
        manual_after += routed * MANUAL_MINUTES["confirm_with_authority"] + len(hm) * MANUAL_MINUTES["review_flag"]

    total_faults = sum(n for _, n in fault_hits.values())
    detected = sum(h for h, _ in fault_hits.values())
    auto = sum(ver[s] for s in ("VERIFIED", "MISMATCH", "EXPIRED"))
    res = {
        "applications_evaluated": len(times),
        "classification_accuracy": round(cls_ok / cls_n, 4) if cls_n else None,
        "field_extraction_accuracy": {
            "text_layer": round(fld["text"][0] / fld["text"][1], 4) if fld["text"][1] else None,
            "ocr_scanned": round(fld["ocr"][0] / fld["ocr"][1], 4) if fld["ocr"][1] else None,
            "fields_checked": fld["text"][1] + fld["ocr"][1]},
        "fault_detection_recall": round(detected / total_faults, 4) if total_faults else None,
        "fault_detection_by_type": {k: {"detected": h, "injected": n} for k, (h, n) in sorted(fault_hits.items())},
        "faults_not_reached_blocked_at_submission": not_reached,
        "unexpected_high_medium_flags": len(false_alarms),
        "clean_applications": clean_apps,
        "clean_applications_with_false_alarm": clean_with_alarm,
        "verification_status_counts": dict(ver),
        "automated_verification_rate": round(auto / sum(ver.values()), 4) if ver else None,
        "avg_validation_ms": round(sum(times) / len(times)) if times else None,
        "documents_cleared_without_manual_recheck": round(docs_clear / docs_total, 4) if docs_total else None,
        "discrepancy_precision": round(flags_explained / flags_total, 4) if flags_total else None,
        "time_to_first_alert_ms": round(sum(times) / len(times)) if times else None,
        "manual_effort": {"minutes_by_hand": round(manual_before), "minutes_with_pramaan": round(manual_after),
                          "estimated_reduction": round(1 - manual_after / manual_before, 4) if manual_before else None,
                          "assumed_minutes": MANUAL_MINUTES},
        "extraction_errors_sample": fld_errors[:15],
        "false_alarms_sample": false_alarms[:15],
        "note": "Synthetic data. These numbers show the pipeline works as designed; they are not a field accuracy claim.",
    }
    (config.STORAGE_DIR / "evaluation.json").write_text(json.dumps(res, indent=2, default=str))

    print(f"Applications evaluated            {res['applications_evaluated']}")
    print(f"Classification accuracy           {res['classification_accuracy']:.1%}")
    print(f"Field extraction (text layer)     {res['field_extraction_accuracy']['text_layer']:.1%}")
    print(f"Field extraction (OCR, scanned)   {res['field_extraction_accuracy']['ocr_scanned']:.1%}")
    print(f"Fault detection recall            {res['fault_detection_recall']:.1%}  ({detected}/{total_faults})")
    for k, v in res["fault_detection_by_type"].items():
        print(f"    {k:24} {v['detected']}/{v['injected']}")
    if not_reached:
        print(f"    (+{len(not_reached)} not reached: application blocked at submission before that check runs: "
              f"{', '.join(sorted({x['fault'] for x in not_reached}))})")
    print(f"Unexpected high/medium flags      {len(false_alarms)}  (clean apps with any: {clean_with_alarm}/{clean_apps})")
    print(f"Automated verification rate       {res['automated_verification_rate']:.1%}  {dict(ver)}")
    print(f"Docs cleared w/o manual re-check  {res['documents_cleared_without_manual_recheck']:.1%}")
    print(f"Avg validation time               {res['avg_validation_ms']} ms")
    print(f"Discrepancy precision (hi/med)    {res['discrepancy_precision']:.1%}  ({flags_explained}/{flags_total} flags explained by injected faults)")
    me = res["manual_effort"]
    print(f"Manual effort (assumed minutes)   {me['minutes_by_hand']} by hand -> {me['minutes_with_pramaan']} with Pramaan "
          f"({me['estimated_reduction']:.0%} less)")
    if fld_errors:
        print("Extraction errors (sample):")
        for e in fld_errors[:8]:
            print("   ", e)
    if false_alarms:
        print("Unexpected flags (sample):")
        for e in false_alarms[:10]:
            print("   ", e)


if __name__ == "__main__":
    main()
