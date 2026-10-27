"""Structured validation report as a PDF an official can file or forward.

Built from the stored run (no re-validation), so the report matches what the
dashboard showed and what the audit trail recorded.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

INK = colors.HexColor("#1A1D23")
MUTED = colors.HexColor("#6A7180")
LINE = colors.HexColor("#DCE0E6")
NAVY = colors.HexColor("#0F1D3A")
SEV_COLOR = {"high": colors.HexColor("#C2361F"), "medium": colors.HexColor("#A86400"), "low": colors.HexColor("#6A7180"),
             "info": colors.HexColor("#6A7180")}
STATUS_COLOR = {"VERIFIED": "#1F7A4C", "MISMATCH": "#C2361F", "EXPIRED": "#A86400", "PENDING": "#2550C0",
                "SOURCE_UNAVAILABLE": "#6A7180", "MANUAL_REVIEW": "#6A7180", "PASS": "#1F7A4C", "FAIL": "#C2361F",
                "SKIP": "#6A7180", "NA": "#6A7180"}
CHECKS = [("checklist", "Checklist"), ("records", "AICTE records"), ("authenticity", "Authenticity"),
          ("sources", "Issuing authority"), ("infrastructure", "Infrastructure")]
REVIEW = {"OPEN": "Not yet reviewed", "CONFIRMED": "Confirmed", "DISMISSED": "Dismissed",
          "RECTIFICATION_REQUESTED": "Rectification requested", "INSPECTION_REQUIRED": "Inspection required"}
DECISIONS = {"RECOMMEND_FOR_APPROVAL": "Recommend for approval", "RETURN_FOR_RECTIFICATION": "Return to the institution",
             "REFER_FOR_INSPECTION": "Refer for physical inspection", "REFER_TO_EXPERT_COMMITTEE": "Refer to expert committee"}
SYSTEM = {"ACTION_REQUIRED": "Needs review — high-severity issues", "DEFICIENCIES_FOUND": "Deficiencies found",
          "MANUAL_VERIFICATION": "Awaiting manual confirmation from sources", "READY_FOR_SCRUTINY": "Clear — no issues raised"}

S = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=INK, spaceAfter=2),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=INK, spaceBefore=12, spaceAfter=6),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK, alignment=TA_LEFT),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=7.8, leading=10.5, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.2, leading=10.5, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8.4, leading=10.8, textColor=INK),
    "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7.8, leading=10, textColor=MUTED),
}


def P(text, style="cell"):
    return Paragraph(escape(str(text if text is not None else "—")).replace("\n", "<br/>"), S[style])


def Pc(text, color, bold=True):
    st = ParagraphStyle("c", parent=S["cellb" if bold else "cell"], textColor=colors.HexColor(color) if isinstance(color, str) else color)
    return Paragraph(escape(str(text)), st)


def check_of(f):
    if f["module"] == "rules" and "-REC-" in (f.get("rule_id") or ""):
        return "records"
    return {"rules": "checklist", "extraction": "checklist", "anomaly": "authenticity", "verification": "sources",
            "infrastructure": "infrastructure"}[f["module"]]


def table(rows, widths, header=True, zebra=False):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F5F8")), ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE)]
    t.setStyle(TableStyle(style))
    return t


def _evidence_lines(f) -> list[str]:
    ev = f.get("evidence") or {}
    out = []
    if ev.get("document"):
        out.append(f"Document: {ev['document']}")
    if ev.get("found_value"):
        out.append(f"Printed: {ev['found_value']}" + (f"   Expected: {ev['expected']}" if ev.get("expected") else ""))
    for c in ev.get("comparison") or []:
        out.append(f"{c['field'].replace('_', ' ')}: document {c.get('document')} | source {c.get('source')} | {'match' if c.get('match') else 'MISMATCH'}")
    resp = ev.get("response") or {}
    if resp.get("signature"):
        out.append(f"QR signature: {resp['signature']}")
    if resp.get("signer"):
        out.append(f"Signed by: {resp['signer']}  (coverage {resp.get('coverage')})")
    for k in ("application_value", "record_value", "value_font", "expected_font", "producer", "modification_date",
              "requested_intake", "approved_intake", "texture_correlation", "other_application", "missing_fields"):
        if ev.get(k) not in (None, "", []):
            v = ", ".join(ev[k]) if isinstance(ev[k], list) else ev[k]
            out.append(f"{k.replace('_', ' ').capitalize()}: {v}")
    if ev.get("checked_at"):
        out.append(f"Checked: {ev['checked_at']}")
    return out


def build(app: dict, report: dict, findings: list, verifications: list, documents: list, record: dict | None,
          audit_head: str, generated_by: str, institution_view: bool = False) -> bytes:
    buf = io.BytesIO()
    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    ref = app["ref"]

    def frame(canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(NAVY)
        canvas.rect(0, h - 14 * mm, w, 14 * mm, fill=1, stroke=0)
        for i, c in enumerate(("#FF9933", "#FFFFFF", "#138808")):
            canvas.setFillColor(colors.HexColor(c))
            canvas.rect(i * w / 3, h - 15 * mm, w / 3, 1 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 10.5)
        canvas.drawString(16 * mm, h - 9 * mm, "Pramaan  ·  Validation report")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(w - 16 * mm, h - 9 * mm, f"{ref}  ·  decision-support output  ·  prototype, synthetic data")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(16 * mm, 9 * mm, f"Generated {generated} by {generated_by}  ·  run {report.get('run_id')}  ·  "
                          f"rule set {report.get('ruleset_version')} ({report.get('ruleset_fingerprint')})  ·  audit head {audit_head[:16]}")
        canvas.drawRightString(w - 16 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=22 * mm, bottomMargin=16 * mm,
                            title=f"Validation report {ref}", author="Pramaan (prototype)")
    W = A4[0] - 32 * mm
    story = []

    # ---------------------------------------------------------------- summary
    story += [P(app["form"].get("institution_name"), "h1"),
              P(f"{report.get('category_label', app['category'])}  ·  Academic year {app['form'].get('academic_year')}  ·  "
                f"AICTE Permanent ID {app['form'].get('aicte_permanent_id')}", "small"), Spacer(1, 8)]
    counts = report.get("finding_counts") or {}
    by_check = {k: [f for f in findings if check_of(f) == k and f["severity"] != "info"] for k, _ in CHECKS}
    worst = lambda fs: next((s for s in ("high", "medium", "low") if any(f["severity"] == s for f in fs)), None)  # noqa: E731
    summary = [[P("System assessment", "th"), Pc(SYSTEM.get(report.get("system_status"), report.get("system_status")),
                                                 "#C2361F" if report.get("system_status") == "ACTION_REQUIRED" else INK)],
               [P("Issues raised", "th"), P(f"{counts.get('high', 0)} high · {counts.get('medium', 0)} medium · {counts.get('low', 0)} low"
                                           f" · {counts.get('info', 0)} notes")],
               [P("Checked", "th"), P(f"{report.get('validated_at')} (as of {report.get('as_of')}) in {report.get('timings', {}).get('total_ms')} ms")]]
    if report.get("risk_score") is not None:
        rec_color = "#C2361F" if report.get("inspection_recommendation") == "EVC_PHYSICAL_VISIT" else "#1F7A4C"
        summary.append([P("Inspection Risk", "th"),
                        Pc(f"{report.get('risk_score', 0):.1f} / 100 — {report.get('inspection_recommendation_label', '')}", rec_color)])
    if app.get("decision"):
        summary.append([P("Official’s recommendation", "th"), Pc(f"{DECISIONS.get(app['decision'], app['decision'])} — by {app.get('decision_by')}", INK)])
    story.append(table(summary, [42 * mm, W - 42 * mm], header=False))
    story.append(Spacer(1, 8))
    strip = [[P(lbl, "th") for _, lbl in CHECKS]]
    strip.append([Pc(f"{len(by_check[k])} issue(s), worst {worst(by_check[k])}" if by_check[k] else "No issues",
                     SEV_COLOR.get(worst(by_check[k]), colors.HexColor("#1F7A4C"))) for k, _ in CHECKS])
    story.append(table(strip, [W / 5] * 5))

    # ---------------------------------------------------------------- findings
    story.append(P("1. Issues and evidence", "h2"))
    story.append(P("Each issue lists the rule or method that raised it, the evidence behind it and its review status. "
                   "Authenticity indicators are preliminary and require human verification; they are not proof of manipulation.", "small"))
    sev_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    for key, label in CHECKS:
        fs = sorted([f for f in findings if check_of(f) == key], key=lambda f: sev_rank[f["severity"]])
        if not fs:
            continue
        story.append(Spacer(1, 6))
        story.append(P(label, "cellb"))
        rows = [[P("Severity", "th"), P("Issue and evidence", "th"), P("Review", "th")]]
        for f in fs:
            body = [Paragraph(f"<b>{escape(f['title'])}</b>", S["cell"]), P(f["reason"])]
            body += [Paragraph(escape(x), S["small"]) for x in _evidence_lines(f)]
            body.append(Paragraph(f"Rule {escape(f.get('rule_id') or '')} · basis: {escape(f.get('ref') or '')}", S["small"]))
            review = [Pc(REVIEW.get(f["review_status"], f["review_status"]), MUTED if f["review_status"] == "OPEN" else INK)]
            if f.get("reviewer"):
                review += [P(f"{f['reviewer']}, {str(f.get('reviewed_at'))[:16]}", "small"), P(f.get("review_remark"), "small")]
            rows.append([Pc(f["severity"].capitalize(), SEV_COLOR[f["severity"]]), body, review])
        story.append(table(rows, [18 * mm, W - 68 * mm, 50 * mm]))

    # ---------------------------------------------------------------- checklist
    story.append(PageBreak())
    story.append(P("2. Regulatory checklist", "h2"))
    story.append(P("Rules applied for this application type, from the configured rule set. Values are illustrative until set from the "
                   "applicable Approval Process Handbook.", "small"))
    rows = [[P("Rule", "th"), P("Check", "th"), P("Applies to", "th"), P("Result", "th"), P("Basis", "th")]]
    for c in report.get("checklist", []):
        rows.append([P(c["rule_id"]), P(c["type"].replace("_", " ")), P(str(c.get("target") or "").replace("_", " ")),
                     Pc({"PASS": "Pass", "FAIL": "Fail", "SKIP": "Not checked", "NA": "N/A"}.get(c["status"], c["status"]),
                        STATUS_COLOR.get(c["status"], "#6A7180")), P(c.get("ref"), "small")])
    story.append(table(rows, [22 * mm, 30 * mm, 34 * mm, 18 * mm, W - 104 * mm]))

    if not institution_view:
        # ------------------------------------------------------------ verification
        story.append(P("3. Verification with issuing authorities", "h2"))
        names = {d["id"]: d["original_name"] for d in documents}
        method = {"qr_signed": "Signed QR code", "api": "Reference lookup", "pdf_signature": "PDF digital signature",
                  "repository": "Issuer’s repository copy", "manual": "No automated source"}
        rows = [[P("Document", "th"), P("Source · method", "th"), P("Status", "th"), P("Detail", "th")]]
        for v in verifications:
            resp = v.get("response") or {}
            detail = resp.get("message") or resp.get("signature") or ""
            bad = [c["field"].replace("_", " ") for c in (v.get("comparison") or []) if not c["match"]]
            if bad:
                detail = f"Differs on: {', '.join(bad)}. {detail}"
            rows.append([P(names.get(v["document_id"])), P(f"{v['source'].replace('_', ' ')} · {method.get(v['method'], v['method'])}"),
                         Pc(v["status"].replace("_", " ").capitalize(), STATUS_COLOR.get(v["status"], "#6A7180")),
                         [P(detail, "small"), P(str(v.get("checked_at")), "small")]])
        story.append(table(rows, [36 * mm, 46 * mm, 26 * mm, W - 108 * mm]))

        # ------------------------------------------------------------ records + infrastructure
        story.append(P("4. AICTE records consulted", "h2"))
        if record:
            ay = app["form"].get("academic_year")
            rows = [[P("Item", "th"), P("Application", "th"), P("AICTE record", "th")],
                    [P("Institution name"), P(app["form"].get("institution_name")), P(record.get("name"))],
                    [P("Permanent ID"), P(app["form"].get("aicte_permanent_id")), P(record.get("permanent_id"))],
                    [P("Faculty"), P(app["form"].get("faculty_count")), P(record.get("faculty_on_record"))],
                    [P("Previous approval"), P(""), P(f"{record.get('previous_eoa', {}).get('academic_year')}: {record.get('previous_eoa', {}).get('status')}")],
                    [P(f"Processing fee {ay}"), P(""), P((record.get("ter_payments") or {}).get(ay, "not recorded"))],
                    [P("Open deficiencies"), P(""), P("; ".join(record.get("open_deficiencies") or []) or "None")]]
            for p in record.get("approved_programmes", []):
                req = next((x for x in app["form"].get("programmes", []) if x["code"] == p["code"]), None)
                rows.append([P(f"{p['name']} — intake"), P(req["intake"] if req else "—"), P(p["intake"])])
            story.append(table(rows, [60 * mm, (W - 60 * mm) / 2, (W - 60 * mm) / 2]))
            hist = record.get("application_history") or []
            if hist:
                story.append(Spacer(1, 6))
                rows = [[P("Year", "th"), P("Application", "th"), P("Outcome", "th"), P("Remarks", "th")]]
                rows += [[P(h["academic_year"]), P(f"{h['type']} ({h['ref']})"), P(h["outcome"]), P(h.get("remarks") or "—", "small")] for h in hist]
                story.append(table(rows, [22 * mm, 66 * mm, 40 * mm, W - 128 * mm]))
        else:
            story.append(P("No matching institutional record."))

    inf = report.get("infrastructure") or {}
    if inf.get("norms"):
        n = inf["norms"]
        story.append(P(("5. " if not institution_view else "3. ") + "Infrastructure against norms (advisory)", "h2"))
        rows = [[P("Item", "th"), P("Declared", "th"), P("Required for requested intake", "th")]]
        for k, lbl in (("classrooms", "Classrooms"), ("labs", "Laboratories"), ("built_up_area_sqm", "Built-up area (sq m)")):
            have, need = n["declared"].get(k), n["required"].get(k)
            rows.append([P(lbl), Pc(have, "#C2361F" if have is not None and have < need else INK, bold=False), P(need)])
        story.append(table(rows, [60 * mm, 40 * mm, W - 100 * mm]))
        story.append(P(f"{inf.get('photos', {}).get('photos', 0)} photographs; room types covered: "
                       f"{', '.join(inf.get('photos', {}).get('room_types', [])) or 'none'}.", "small"))

    story += [Spacer(1, 14), KeepTogether([P("Note", "cellb"), P(
        "This report is a decision-support output generated from automated checks on the documents and records listed. Statutory "
        "scrutiny, physical inspections where required, and the final regulatory decision rest with the competent AICTE authorities. "
        "The audit-trail hash printed in the footer identifies the state of the tamper-evident log when this report was produced.", "small")])]

    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()
