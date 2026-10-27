"""Orchestrates the full validation run for one application."""
from __future__ import annotations

import json
import time
import uuid
from datetime import date

from ..core import audit, config
from ..core.notify import notify
from ..core.db import now_iso, row, rows, tx
from . import anomaly, extract, infra, rules, verify

SEV_RANK = {"high": 3, "medium": 2, "low": 1, "info": 0}
INSTITUTION_VISIBLE_MODULES = {"rules", "extraction"}   # forensic flags stay with officials


def process_document(doc_id: int) -> dict:
    """Read, OCR, classify and extract one document. Runs at upload time so the
    institution gets completeness feedback immediately."""
    with tx() as c:
        d = row(c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())
    is_photo = d["declared_type"] == "infra_photo"
    rr = extract.read_document(d["stored_path"], d["mime"], ocr=not is_photo)
    dh = anomaly.dhash(rr.images[0]) if rr.images else None
    ph = anomaly.phash(rr.images[0]) if rr.images else None
    if is_photo:
        ex = {"fields": {}, "photo_metrics": infra.photo_metrics(rr.images[0])}
        detected, conf = "infra_photo", 1.0
    else:
        detected, conf, scores = extract.classify(rr.text)
        base_conf = rr.ocr_confidence if rr.ocr_used and rr.ocr_confidence is not None else 0.99
        ex = {"fields": extract.extract_fields(rr.text, d["declared_type"], round(base_conf, 2)),
              "class_scores": scores, "page_count": rr.page_count, "ocr_confidence": rr.ocr_confidence,
              "pdf_metadata": {k: str(v) for k, v in rr.pdf_metadata.items()}}
    with tx() as c:
        c.execute("UPDATE documents SET detected_type=?, classification_conf=?, extraction_json=?, text=?, ocr_used=?, dhash=?, phash=? WHERE id=?",
                  (detected, conf, json.dumps(ex), rr.text[:20000], int(rr.ocr_used), dh, ph, doc_id))
    return {"detected_type": detected, "confidence": conf, "fields": ex.get("fields"), "ocr_used": rr.ocr_used}


def _carry_reviews(c, app_id, new_findings):
    old = {(f["rule_id"], f["document_id"], f["title"]): f for f in rows(c.execute(
        "SELECT * FROM findings WHERE application_id=? AND review_status!='OPEN'", (app_id,)).fetchall())}
    for f in new_findings:
        o = old.get((f["rule_id"], f["document_id"], f["title"]))
        if o:
            f["review_status"], f["reviewer"], f["review_remark"], f["reviewed_at"] = \
                o["review_status"], o["reviewer"], o["review_remark"], o["reviewed_at"]


def validate_application(app_id: int, actor: str = "system", role: str = "system", today: date | None = None) -> dict:
    today = today or date.today()
    run_id = uuid.uuid4().hex[:12]
    timings = {}
    t0 = time.perf_counter()

    with tx() as c:
        app = row(c.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone())
        docs = rows(c.execute("SELECT * FROM documents WHERE application_id=? AND superseded=0 AND purged=0 ORDER BY id", (app_id,)).fetchall())
        others = rows(c.execute(
            "SELECT d.id,d.sha256,d.dhash,d.declared_type,d.original_name,d.text,d.extraction_json,a.ref AS app_ref,a.institution_id "
            "FROM documents d JOIN applications a ON a.id=d.application_id WHERE d.application_id!=? AND d.superseded=0 AND d.purged=0",
            (app_id,)).fetchall())

    record = config.institutional_records()["institutions"].get(app["institution_id"])
    audit.log(actor, role, "VALIDATION_STARTED", app_id, {"run_id": run_id, "ruleset_version": config.categories()["version"],
              "ruleset_fingerprint": config.ruleset_fingerprint(), "documents": len(docs)})
    audit.log("system", "system", "RECORDS_ACCESSED", app_id, {"run_id": run_id, "institution_id": app["institution_id"],
              "record_found": record is not None, "datasets": ["institution_master", "approved_intake", "previous_eoa",
                                                               "deficiencies", "ter_payments"]})

    # 1. extraction (only for docs not processed yet)
    for d in docs:
        if d.get("extraction") is None:
            process_document(d["id"])
    with tx() as c:
        docs = rows(c.execute("SELECT * FROM documents WHERE application_id=? AND superseded=0 AND purged=0 ORDER BY id", (app_id,)).fetchall())
    for d in docs:
        d["institution_id"] = app["institution_id"]
    timings["extraction_ms"] = round((time.perf_counter() - t0) * 1000)

    is_draft = not app.get("is_frozen") and app.get("status") == "DRAFT"
    ctx = {"category": app["category"], "form": app["form"], "docs": docs, "record": record, "today": today, "is_draft": is_draft}

    # 2. rules + completeness
    t = time.perf_counter()
    checklist, findings = rules.evaluate(ctx)
    findings += rules.completeness_findings(ctx)
    findings += rules.ghost_faculty_check(ctx)
    timings["rules_ms"] = round((time.perf_counter() - t) * 1000)

    # 3. anomaly + 4. verification (both need the rendered pages)
    t_an, t_ver = 0.0, 0.0
    verifications, photos = [], []
    for d in docs:
        is_photo = d["declared_type"] == "infra_photo"
        rr = extract.read_document(d["stored_path"], d["mime"], ocr=False)
        fields = (d.get("extraction") or {}).get("fields") or {}
        s = time.perf_counter()
        findings += anomaly.duplicate_checks(d, others, app["form"].get("institution_name"))
        findings += anomaly.phash_collision_checks(d, others)
        if not is_photo:
            if d["mime"] == "application/pdf":
                raw = open(d["stored_path"], "rb").read()
                findings += anomaly.pdf_metadata_checks(d, raw, rr.pdf_metadata)
                findings += anomaly.font_checks(d, rr.chars, fields)
                findings += anomaly.overlap_checks(d, rr.chars)
                findings += anomaly.baseline_jitter_checks(d, rr.chars, fields)
            elif d["mime"] == "image/jpeg":
                findings += anomaly.ela_check(d, rr.images[0])
            if rr.images:
                findings += anomaly.copy_move_checks(d, rr.images[0])
                findings += anomaly.exif_manipulation_checks(d, rr.images[0])
            findings += anomaly.date_checks(d, fields, today)
        else:
            if rr.images:
                findings += anomaly.exif_manipulation_checks(d, rr.images[0])
            photos.append({"doc": d, "metrics": d["extraction"]["photo_metrics"], "dhash": d["dhash"], "image": rr.images[0]})
        t_an += time.perf_counter() - s

        s = time.perf_counter()
        if not is_photo:
            res = verify.verify_document(d, rr.images, today)
            for r in res:
                r["document_id"] = d["id"]
                audit.log("system", "system", "SOURCE_RESPONSE", app_id, {"run_id": run_id, "document": d["original_name"],
                          "source": r["source"], "method": r["method"], "status": r["status"]})
            verifications += res
            findings += verify.findings_from_verification(d, res)
        t_ver += time.perf_counter() - s
    timings["anomaly_ms"] = round(t_an * 1000)
    timings["verification_ms"] = round(t_ver * 1000)

    # 5. infrastructure
    t = time.perf_counter()
    campus_coords = {"latitude": record.get("latitude"), "longitude": record.get("longitude")} if record and record.get("latitude") else None
    norm_summary, f_norm = infra.norms_check(app["form"])
    if is_draft:
        f_norm = []
        if len(photos) == 0:
            photo_summary = {"total_photos": 0, "by_room": {}, "rooms_covered": 0, "verified_rooms": 0, "gps_match_pct": 0, "indoor_pct": 0}
            f_photo = []
        else:
            photo_summary, f_photo = infra.photo_checks(photos, campus_coords=campus_coords)
    else:
        photo_summary, f_photo = infra.photo_checks(photos, campus_coords=campus_coords)
    findings += f_norm + f_photo
    timings["infrastructure_ms"] = round((time.perf_counter() - t) * 1000)
    timings["total_ms"] = round((time.perf_counter() - t0) * 1000)

    # status per document
    doc_status = {}
    for d in docs:
        res = [v for v in verifications if v["document_id"] == d["id"]]
        doc_status[d["id"]] = verify.overall_status(res) if res else "NOT_APPLICABLE"

    # system recommendation (decision-support only)
    open_high = [f for f in findings if f["severity"] == "high"]
    needs_manual = any(v["status"] in ("PENDING", "SOURCE_UNAVAILABLE", "MANUAL_REVIEW") for v in verifications)
    if open_high:
        system_status = "ACTION_REQUIRED"
    elif any(f["severity"] == "medium" for f in findings):
        system_status = "DEFICIENCIES_FOUND"
    elif needs_manual:
        system_status = "MANUAL_VERIFICATION"
    else:
        system_status = "READY_FOR_SCRUTINY"

    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEV_RANK}
    risk_info = infra.compute_inspection_risk_score(findings, verifications, norm_summary)
    report = {"run_id": run_id, "validated_at": now_iso(), "as_of": today.isoformat(),
              "ruleset_version": config.categories()["version"], "ruleset_fingerprint": config.ruleset_fingerprint(),
              "category": app["category"], "category_label": config.categories()["categories"][app["category"]]["label"],
              "checklist": checklist, "finding_counts": counts, "document_status": {str(k): v for k, v in doc_status.items()},
              "infrastructure": {"norms": norm_summary, "photos": photo_summary}, "timings": timings,
              "record_found": record is not None, "system_status": system_status,
              "risk_score": risk_info["risk_score"],
              "inspection_recommendation": risk_info["recommendation"],
              "inspection_recommendation_label": risk_info["recommendation_label"],
              "risk_factors": risk_info["risk_factors"],
              "disclaimer": "Decision-support output. Statutory scrutiny, inspection and final decisions rest with competent AICTE authorities."}

    with tx() as c:
        _carry_reviews(c, app_id, findings)
        c.execute("DELETE FROM findings WHERE application_id=?", (app_id,))
        c.execute("DELETE FROM verifications WHERE application_id=?", (app_id,))
        c.execute("DELETE FROM alerts WHERE application_id=? AND acknowledged_by IS NULL", (app_id,))
        for f in findings:
            cur = c.execute(
                "INSERT INTO findings(application_id,run_id,document_id,module,rule_id,severity,title,reason,evidence_json,ref,"
                "review_status,reviewer,review_remark,reviewed_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (app_id, run_id, f.get("document_id"), f["module"], f.get("rule_id"), f["severity"], f["title"], f["reason"],
                 json.dumps(f.get("evidence"), default=str), f.get("ref"), f.get("review_status", "OPEN"), f.get("reviewer"),
                 f.get("review_remark"), f.get("reviewed_at"), now_iso()))
            fid = cur.lastrowid
            if f["severity"] in ("high", "medium") and f.get("review_status", "OPEN") == "OPEN":
                inst_visible = f["module"] in INSTITUTION_VISIBLE_MODULES     # forensic flags stay with officials
                if app.get("is_frozen") or app["status"] != "DRAFT":
                    # Submitted: officers get every alert; the institution only checklist/extraction ones.
                    audience = "both" if inst_visible else "officer"
                else:
                    # Draft uploads: alerts go to the institution only (missing/expired/wrong documents),
                    # never to scrutiny officers.
                    rid = f.get("rule_id", "")
                    if not (inst_visible and ("-DOC-" in rid or "-VAL-" in rid or rid.startswith("DOC-"))):
                        continue
                    audience = "institution"
                kind = {"anomaly": "SUSPECTED_ANOMALY", "verification": "VERIFICATION", "infrastructure": "INFRASTRUCTURE"}.get(
                    f["module"], "DEFICIENCY")
                c.execute("INSERT INTO alerts(application_id,finding_id,severity,kind,message,audience,created_at) VALUES (?,?,?,?,?,?,?)",
                          (app_id, fid, f["severity"], kind, f["title"], audience, now_iso()))
        for v in verifications:
            c.execute("INSERT INTO verifications(application_id,run_id,document_id,source,method,status,comparison_json,response_json,checked_at)"
                      " VALUES (?,?,?,?,?,?,?,?,?)",
                      (app_id, run_id, v["document_id"], v["source"], v["method"], v["status"], json.dumps(v["comparison"], default=str),
                       json.dumps(v["response"], default=str), v["checked_at"]))
            if v["status"] in ("PENDING", "SOURCE_UNAVAILABLE"):
                if app.get("is_frozen") or app["status"] != "DRAFT":
                    c.execute("INSERT INTO alerts(application_id,severity,kind,message,audience,created_at) VALUES (?,?,?,?,?,?)",
                              (app_id, "low", "VERIFICATION_" + v["status"], f"{v['source']}: {v['status'].replace('_', ' ').lower()}",
                               "both", now_iso()))
        # email digests: what the institution must fix, and what needs an official's eye
        inst_items = [f["title"] for f in findings if f["severity"] in ("high", "medium") and f["module"] in INSTITUTION_VISIBLE_MODULES
                      and f.get("review_status", "OPEN") == "OPEN"]
        if inst_items:
            notify(c, "institution", app_id, f"{app['ref']}: {len(inst_items)} item(s) to fix",
                   [f"Automated checks on application {app['ref']} found:"] + [f"  - {t}" for t in inst_items], app["institution_id"])
        off_items = [f["title"] for f in findings if f["severity"] == "high" and f.get("review_status", "OPEN") == "OPEN"]
        if off_items and (app.get("is_frozen") or app["status"] != "DRAFT"):
            notify(c, "officer", app_id, f"{app['ref']}: {len(off_items)} high-severity issue(s) need review",
                   [f"{app['form'].get('institution_name')} — {app['ref']}"] + [f"  - {t}" for t in off_items])
        if app.get("is_frozen") or app["status"] not in ("DRAFT",):
            new_status = app["status"] if app["status"] in ("DECIDED", "RECTIFICATION_REQUESTED") else "UNDER_SCRUTINY"
        else:
            new_status = app["status"]
        cols = {col["name"] for col in c.execute("PRAGMA table_info(applications)")}
        if "risk_score" in cols:
            c.execute("UPDATE applications SET report_json=?, system_status=?, validated_at=?, status=?, risk_score=?, inspection_recommendation=? WHERE id=?",
                      (json.dumps(report), system_status, report["validated_at"], new_status, risk_info["risk_score"], risk_info["recommendation"], app_id))
        else:
            c.execute("UPDATE applications SET report_json=?, system_status=?, validated_at=?, status=? WHERE id=?",
                      (json.dumps(report), system_status, report["validated_at"], new_status, app_id))

    audit.log("system", "system", "VALIDATION_COMPLETED", app_id, {"run_id": run_id, "system_status": system_status,
              "finding_counts": counts, "rules_evaluated": len(checklist), "timings": timings})
    return report
