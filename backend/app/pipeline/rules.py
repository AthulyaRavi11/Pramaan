"""Configurable regulatory rules engine.

Evaluates the rule list of an application category (categories.yaml) and
returns (checklist, findings). Every finding carries evidence: the document,
the extracted value and the line it came from, the expected value and the
configured reference, so an official can see *why* it was raised.
"""
from __future__ import annotations

from datetime import date
from difflib import SequenceMatcher

from ..core import config
from .extract import normalize_name, parse_date


def academic_year_start(ay: str | None) -> date | None:
    try:
        return date(int(ay.split("-")[0]), 7, 1)      # configurable convention: session starts 1 July
    except Exception:
        return None


def _docs_of(ctx, dtype):
    """Docs uploaded for this slot whose content the classifier does not contradict.
    (A file whose text can't be classified — e.g. unreadable scan — still counts; the
    completeness check flags it separately.)"""
    return [d for d in ctx["docs"] if d["declared_type"] == dtype
            and (not d.get("detected_type") or d["detected_type"] == dtype)]


def _field(doc, name):
    return ((doc.get("extraction") or {}).get("fields") or {}).get(name)


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def _ev(doc=None, field=None, **extra):
    e = {}
    if doc is not None:
        e["document_id"] = doc["id"]
        e["document"] = doc["original_name"]
        if field:
            f = _field(doc, field)
            if f:
                e.update({"field": field, "found_value": f["value"], "line": f["line"], "line_text": f["line_text"]})
    e.update(extra)
    return e


FIELD_LABELS = {"faculty_count": "Faculty count", "institution_name": "Institution name", "aicte_permanent_id": "AICTE Permanent ID",
                "academic_year": "Academic year", "built_up_area_sqm": "Built-up area"}


def _finding(rule, title, reason, doc=None, evidence=None, severity=None):
    return {"module": "rules", "rule_id": rule["id"], "severity": severity or rule.get("severity", "medium"),
            "title": rule.get("title") or title, "reason": reason, "document_id": doc["id"] if doc else None,
            "evidence": evidence or {}, "ref": rule.get("ref")}


def _resolve(spec: str, ctx):
    src, path = spec.split(":", 1)
    if src == "form":
        return ctx["form"].get(path), None
    if src == "record":
        return (_record_path(ctx["record"], path, ctx["form"]) if ctx.get("record") else None), None
    dtype, fname = path.split(".")
    for d in _docs_of(ctx, dtype):
        f = _field(d, fname)
        if f and f["normalized"] is not None:
            return f["normalized"], d
    return None, None


def _record_path(record: dict, path: str, form: dict):
    path = path.format(**form)
    cur = record
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


# -------------------------------------------------------------- rule handlers

def r_required_document(rule, ctx):
    if ctx.get("is_draft"):
        return "SKIP", []
    docs = _docs_of(ctx, rule["doc"])
    need = rule.get("min_count", 1)
    label = config.documents()[rule["doc"]]["label"]
    if len(docs) >= need:
        return "PASS", []
    return "FAIL", [_finding(rule, f"Missing: {label}" + (f" ({len(docs)}/{need})" if need > 1 else ""),
                             f"Category requires at least {need} × {label}; {len(docs)} uploaded.",
                             evidence={"required": need, "uploaded": len(docs)})]


def r_not_expired(rule, ctx):
    docs = _docs_of(ctx, rule["doc"])
    if not docs:
        return ("NA" if rule.get("optional_doc") else "SKIP"), []
    expiry_field = config.documents()[rule["doc"]].get("expiry_field", "valid_until")
    ref_date = academic_year_start(ctx["form"].get("academic_year")) if rule["reference"] == "academic_year_start" \
        else parse_date(ctx["form"].get("application_date")) or ctx["today"]
    out, status = [], "PASS"
    for d in docs:
        if d.get("detected_type") and d["detected_type"] != d["declared_type"]:
            continue
        f = _field(d, expiry_field)
        if not f or not f["normalized"]:
            continue  # missing-field finding is raised by completeness check
        exp = date.fromisoformat(f["normalized"])
        if exp < ref_date:
            status = "FAIL"
            out.append(_finding(rule, f"Expired: {config.documents()[rule['doc']]['label']}",
                                f"Valid until {exp:%d-%m-%Y}, but must be valid on {ref_date:%d-%m-%Y} "
                                f"({rule['reference'].replace('_', ' ')}).", d,
                                _ev(d, expiry_field, expected=f"on or after {ref_date.isoformat()}")))
    return status, out


def r_max_age_days(rule, ctx):
    docs = _docs_of(ctx, rule["doc"])
    if not docs:
        return "SKIP", []
    app_date = parse_date(ctx["form"].get("application_date")) or ctx["today"]
    out, status = [], "PASS"
    for d in docs:
        f = _field(d, rule["field"])
        if not f or not f["normalized"]:
            continue
        age = (app_date - date.fromisoformat(f["normalized"])).days
        if age > rule["days"]:
            status = "FAIL"
            out.append(_finding(rule, f"Outdated {config.documents()[rule['doc']]['label']}",
                                f"Dated {age} days before the application; limit is {rule['days']} days.", d,
                                _ev(d, rule["field"], age_days=age, limit_days=rule["days"])))
    return status, out


def r_field_consistency(rule, ctx):
    fname = rule["field"]
    form_val = ctx["form"].get(fname)
    vals = []
    for d in ctx["docs"]:
        f = _field(d, fname)
        if f and f["value"]:
            vals.append((d, f["value"]))
    if not vals:
        return "SKIP", []
    reference = form_val or vals[0][1]
    out = []
    for d, v in vals:
        ok = _sim(v, reference) >= rule["fuzzy"] if rule.get("fuzzy") else v.strip().upper() == str(reference).strip().upper()
        if not ok:
            out.append(_finding(rule, f"{FIELD_LABELS.get(fname, fname.replace('_', ' '))} differs from the application",
                                f"'{v}' in {d['original_name']} does not match '{reference}' declared in the application.",
                                d, _ev(d, fname, expected=reference,
                                       similarity=round(_sim(v, str(reference)), 2) if rule.get("fuzzy") else None)))
    return ("FAIL" if out else "PASS"), out


def r_numeric_tolerance(rule, ctx):
    a, doc_a = _resolve(rule["a"], ctx)
    b, doc_b = _resolve(rule["b"], ctx)
    if a is None or b is None:
        return "SKIP", []
    a, b = float(a), float(b)
    diff_pct = abs(a - b) / max(abs(b), 1) * 100
    if diff_pct <= rule["tolerance_pct"]:
        return "PASS", []
    doc = doc_a or doc_b
    fname = rule["a"].split(".")[-1].split(":")[-1]
    if doc is None:   # form vs AICTE record: no document involved
        if ctx.get("is_draft"):
            return "SKIP", []
        return "FAIL", [_finding(rule, f"Declared {FIELD_LABELS.get(fname, fname.replace('_', ' ')).lower()} differs from AICTE records",
                                 f"Application says {a:g}; AICTE records show {b:g} ({diff_pct:.0f}% apart; tolerance {rule['tolerance_pct']}%).",
                                 evidence={"application_value": a, "record_value": b, "difference_pct": round(diff_pct, 1),
                                           "record_source": "AICTE faculty records (synthetic)"})]
    desc_a = f"Certificate reads {a:g}" if rule["a"].startswith("doc:") else f"Form declares {a:g}"
    desc_b = f"Certificate reads {b:g}" if rule["b"].startswith("doc:") else f"Form declares {b:g}"
    return "FAIL", [_finding(rule, f"Declared {FIELD_LABELS.get(fname, fname).lower()} differs from the certificate",
                             f"{desc_a}, but {desc_b} ({diff_pct:.1f}% apart; allowable tolerance {rule['tolerance_pct']}%). Update your application parameters or certificate to match.",
                             doc, _ev(doc, fname, other_value=b, difference_pct=round(diff_pct, 1)))]


def r_record_match(rule, ctx):
    if ctx.get("is_draft"):
        return "SKIP", []
    rec = ctx["record"]
    if rec is None:
        return "FAIL", [_finding(rule, "Institution not found in AICTE records",
                                 "No authorized institutional record matches this application.", evidence={})]
    fv, rv = ctx["form"].get(rule["form_field"]), rec.get(rule["record_field"])
    if fv is None or rv is None:
        return "SKIP", []
    ok = _sim(str(fv), str(rv)) >= rule["fuzzy"] if rule.get("fuzzy") else str(fv).strip() == str(rv).strip()
    if ok:
        return "PASS", []
    return "FAIL", [_finding(rule, f"{FIELD_LABELS.get(rule['form_field'], rule['form_field'])} differs from the AICTE record",
                             f"Application says '{fv}'; AICTE institution master says '{rv}'.",
                             evidence={"application_value": fv, "record_value": rv, "record_source": "AICTE institution master (synthetic)"})]


def r_record_flag(rule, ctx):
    if ctx.get("is_draft"):
        return "SKIP", []
    rec = ctx["record"]
    if rec is None:
        return "SKIP", []
    val = _record_path(rec, rule["record_path"], ctx["form"])
    exp = rule["expect"]
    ok = (val in ([], None, {}) if exp == "EMPTY" else val == exp)
    if ok:
        return "PASS", []
    path = rule["record_path"].format(**ctx["form"])
    shown = val if val is not None else "no record"
    if exp == "EMPTY" and isinstance(val, list):
        reason = "AICTE records still list: " + "; ".join(map(str, val)) + "."
    else:
        what = {"ter_payments": "the processing fee (TER) for", "previous_eoa": "the previous approval"}.get(rule["record_path"].split(".")[0],
                                                                                                         rule["record_path"].split(".")[0].replace("_", " "))
        year = path.split(".")[-1] if rule["record_path"].startswith("ter_payments") else ""
        reason = f"AICTE records show {str(shown).lower()} for {what} {year}".rstrip() + f", where {exp.lower()} is required."
    return "FAIL", [_finding(rule, f"AICTE record does not show {exp.lower()}: {path}", reason,
                             evidence={"record_path": path, "record_value": shown, "expected": exp,
                                       "record_source": "AICTE systems (synthetic)"})]


def r_intake_within_approved(rule, ctx):
    if ctx.get("is_draft"):
        return "SKIP", []
    rec = ctx["record"]
    if rec is None:
        return "SKIP", []
    approved = {p["code"]: p for p in rec.get("approved_programmes", [])}
    out = []
    for p in ctx["form"].get("programmes", []):
        a = approved.get(p["code"])
        if a is None:
            out.append(_finding(rule, f"Programme not previously approved: {p['name']}",
                                "Programme does not appear in the approved list; EoA without change cannot add it.",
                                evidence={"programme": p["code"], "requested_intake": p["intake"]}))
        elif p["intake"] > a["intake"]:
            out.append(_finding(rule, f"Intake exceeds approval: {p['name']}",
                                f"Requested {p['intake']} vs approved {a['intake']}.",
                                evidence={"programme": p["code"], "requested_intake": p["intake"],
                                          "approved_intake": a["intake"], "record_source": "Approved intake (synthetic)"}))
    return ("FAIL" if out else "PASS"), out


HANDLERS = {
    "required_document": r_required_document,
    "not_expired": r_not_expired,
    "max_age_days": r_max_age_days,
    "field_consistency": r_field_consistency,
    "numeric_tolerance": r_numeric_tolerance,
    "record_match": r_record_match,
    "record_flag": r_record_flag,
    "intake_within_approved": r_intake_within_approved,
}


def evaluate(ctx) -> tuple[list[dict], list[dict]]:
    cat = config.categories()["categories"].get(ctx["category"])
    if not cat:
        raise ValueError(f"Unknown category {ctx['category']}")
    checklist, findings = [], []
    for rule in cat["rules"]:
        handler = HANDLERS.get(rule["type"])
        if handler is None:
            checklist.append({"rule_id": rule["id"], "type": rule["type"], "status": "UNSUPPORTED", "ref": rule.get("ref")})
            continue
        status, fs = handler(rule, ctx)
        checklist.append({"rule_id": rule["id"], "type": rule["type"], "status": status,
                          "severity": rule.get("severity"), "ref": rule.get("ref"),
                          "target": rule.get("doc") or rule.get("field") or rule.get("record_path") or rule.get("form_field")})
        findings.extend(fs)
    return checklist, findings


def completeness_findings(ctx) -> list[dict]:
    """Missing required fields per document, and slot/classification mismatches."""
    out = []
    docs_cfg = config.documents()
    for d in ctx["docs"]:
        dtype = d["declared_type"]
        spec = docs_cfg.get(dtype, {})
        ex = d.get("extraction") or {}
        declared_lbl = spec.get("label", dtype)
        
        # 1. Classified as another document type (mismatch)
        if dtype != "infra_photo" and d.get("detected_type") and d["detected_type"] != dtype:
            detected_lbl = docs_cfg.get(d["detected_type"], {}).get("label", d["detected_type"])
            out.append({"module": "extraction", "rule_id": "DOC-CLASS", "severity": "high",
                        "title": f"Wrong Document Uploaded: Detected as {detected_lbl}",
                        "reason": f"Uploaded as {declared_lbl}, but contents match {detected_lbl}. Wrong document uploaded for this slot.",
                        "document_id": d["id"], "evidence": {"document": d["original_name"], "declared_type": dtype,
                        "detected_type": d["detected_type"], "confidence": d.get("classification_conf"),
                        "scores": ex.get("class_scores")}, "ref": "Completeness"})
            continue  # field checks for the wrong document type would only add noise

        # 2. Fake, unreadable, or unrecognized document
        scores = ex.get("class_scores") or {}
        max_score = max(scores.values()) if scores else 0
        if dtype != "infra_photo" and (not d.get("detected_type") or (d.get("classification_conf") or 0) < 0.2 or max_score == 0):
            out.append({"module": "extraction", "rule_id": "DOC-UNRECOGNIZED", "severity": "high",
                        "title": f"Invalid Document: Unrecognized {declared_lbl}",
                        "reason": f"The uploaded file could not be recognized as a valid {declared_lbl}. The document content does not match the required format.",
                        "document_id": d["id"], "evidence": {"document": d["original_name"], "declared_type": dtype,
                        "confidence": d.get("classification_conf"), "ocr_used": bool(d.get("ocr_used"))}, "ref": "Completeness"})
            continue

        # 3. Correct document type: check missing required fields
        missing = [f for f in spec.get("required_fields", []) if f not in (ex.get("fields") or {})
                   or ex["fields"][f]["normalized"] in (None, "")]
        if missing:
            out.append({"module": "extraction", "rule_id": "DOC-FIELDS", "severity": "medium",
                        "title": f"Incomplete {declared_lbl}",
                        "reason": f"Could not find required field(s): {', '.join(missing)}. Missing on the document or unreadable.",
                        "document_id": d["id"], "evidence": {"document": d["original_name"], "missing_fields": missing,
                                                             "ocr_used": bool(d.get("ocr_used"))}, "ref": "Completeness"})
        low = [k for k, v in (ex.get("fields") or {}).items() if v["confidence"] < 0.6]
        if low:
            out.append({"module": "extraction", "rule_id": "DOC-LOWCONF", "severity": "low",
                        "title": f"Low-confidence reading in {d['original_name']}",
                        "reason": f"OCR confidence is low for: {', '.join(low)}. An official should read these by eye.",
                        "document_id": d["id"], "evidence": {"fields": low}, "ref": "Extraction quality"})
    return out


def ghost_faculty_check(ctx) -> list[dict]:
    """Detects 'ghost faculty': professors listed across multiple institutions' records simultaneously."""
    if ctx.get("is_draft"):
        return []
    out = []
    record = ctx.get("record") or {}
    my_roster = ctx.get("form", {}).get("faculty_roster") or record.get("faculty_roster") or []
    if not my_roster:
        return out
    all_insts = config.institutional_records().get("institutions", {})
    my_id = ctx.get("form", {}).get("institution_id") or record.get("permanent_id")
    for fac in my_roster:
        name = fac.get("name", "").strip()
        fid = fac.get("teacher_id") or fac.get("pan_hash")
        if not name and not fid:
            continue
        for inst_id, other_rec in all_insts.items():
            if inst_id == my_id or other_rec.get("permanent_id") == my_id:
                continue
            for o in other_rec.get("faculty_roster", []):
                match_id = fid and (o.get("teacher_id") == fid or o.get("pan_hash") == fid)
                match_name = name and o.get("name", "").strip().lower() == name.lower() and fac.get("department") == o.get("department")
                if match_id or match_name:
                    out.append({
                        "module": "rules",
                        "rule_id": "FAC-GHOST",
                        "severity": "high",
                        "title": f"Potential ghost faculty detected: {name or fid}",
                        "reason": f"Faculty member '{name}' ({fid or 'ID on record'}) is simultaneously registered on the active payroll of {other_rec.get('name', inst_id)}.",
                        "document_id": None,
                        "evidence": {
                            "faculty_name": name,
                            "faculty_id": fid or o.get("teacher_id"),
                            "other_institution": other_rec.get("name", inst_id),
                            "department": fac.get("department", "Engineering"),
                            "record_source": "AICTE Central Faculty Registry",
                            "recommendation": "Require biometric verification or Aadhaar-seeded salary bank statement",
                        },
                        "ref": "AICTE Anti-Ghost Faculty Regulations"
                    })
    return out
