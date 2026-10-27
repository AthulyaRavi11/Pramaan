"""Anomaly and potential-manipulation indicators.

Every function here returns *preliminary indicators* for a human to check —
never a verdict. Genuine documents can trip some of these (e.g. a PDF re-saved
by an office scanner), which is why each flag explains its evidence.
"""
from __future__ import annotations

import io
import re
from collections import Counter, defaultdict
from datetime import date, datetime

import numpy as np
from PIL import Image

from ..core import config
from .extract import parse_date

EDITOR_SIGNATURES = ["phantompdf", "foxit", "pdf-xchange", "acrobat pro", "ilovepdf", "smallpdf", "sejda",
                     "nitro", "pdfescape", "pdf editor", "libreoffice draw"]
DISCLAIMER = "Preliminary indicator only — requires human verification; not proof of manipulation."


def dhash(img: Image.Image, size: int = 8) -> str:
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def phash(img: Image.Image, hash_size: int = 8) -> str:
    """Perceptual hash using Discrete Cosine Transform (DCT) to catch cross-institution collisions."""
    try:
        import cv2
        gray = np.array(img.convert("L").resize((32, 32), Image.LANCZOS), dtype=np.float32)
        dct = cv2.dct(gray)
        dct_low = dct[:hash_size, :hash_size]
        med = float(np.median(dct_low[1:]))
        bits = (dct_low > med).flatten()
        return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"
    except Exception:
        return dhash(img, size=hash_size)


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _f(doc, sev, rule, title, reason, evidence):
    evidence = dict(evidence, document=doc["original_name"], note=DISCLAIMER)
    return {"module": "anomaly", "rule_id": rule, "severity": sev, "title": title, "reason": reason,
            "document_id": doc["id"], "evidence": evidence, "ref": "Forensic indicator"}


def _pdf_date(s):
    if not s:
        return None
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?", str(s))
    if not m:
        return None
    y, mo, d, h, mi = m.groups()
    return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0))


# ------------------------------------------------------------------ PDF structure

def pdf_metadata_checks(doc, raw: bytes, meta: dict) -> list[dict]:
    out = []
    created, modified = _pdf_date(meta.get("CreationDate")), _pdf_date(meta.get("ModDate"))
    producer = str(meta.get("Producer", "")).lower()
    creator = str(meta.get("Creator", "")).lower()
    eof_count = raw.count(b"%%EOF")
    # A digital signature is applied as its own incremental revision: that is expected, not an edit.
    signatures = raw.count(b"/ByteRange")
    unexplained = max(eof_count - 1 - signatures, 0)
    evidence = {"creation_date": str(created) if created else None, "modification_date": str(modified) if modified else None,
                "producer": meta.get("Producer"), "creator": meta.get("Creator"), "incremental_saves": unexplained,
                "signature_revisions": signatures or None}

    reasons, score = [], 0
    if created and modified and (modified - created).days > 2 and not (signatures and not unexplained):
        reasons.append(f"modified {(modified - created).days} days after creation")
        score += 1
    editor = next((e for e in EDITOR_SIGNATURES if e in producer and e not in creator), None)
    if editor:
        reasons.append(f"last saved by an editing tool ('{meta.get('Producer')}') different from the creator ('{meta.get('Creator')}')")
        score += 1
    if unexplained:
        reasons.append(f"{unexplained} incremental update(s) appended after the original save"
                       + (" and after the digital signature" if signatures else ""))
        score += 1
    if score:
        sev = "high" if score >= 3 else "medium" if score == 2 else "low"
        out.append(_f(doc, sev, "ANOM-META", "Document edited after issue (metadata)",
                      "PDF metadata shows it was " + "; ".join(reasons) + ".", evidence))
    return out


def _lines(chars):
    lines = defaultdict(list)
    for c in chars:
        lines[(c["page"], round(c["top"] / 3))].append(c)
    return [sorted(v, key=lambda c: c["x0"]) for v in lines.values()]


def font_checks(doc, chars: list[dict], fields: dict) -> list[dict]:
    """Flags field values printed in a font/size that differs from the rest of the line
    and is rare in the document — a common trace of text pasted over an original value."""
    if not chars:
        return []
    font_freq = Counter(c["font"] for c in chars)
    total = sum(font_freq.values())
    located = {}                                   # field -> (font, size, chars)
    for line in _lines(chars):
        nonspace = [c for c in line if c["text"].strip()]
        txt = "".join(c["text"] for c in nonspace)
        for fname, f in fields.items():
            if fname in located:
                continue
            val = f["value"].replace(" ", "")
            pos = txt.find(val)
            if pos < 0 or len(val) < 4:
                continue
            vc = nonspace[pos:pos + len(val)]
            located[fname] = (Counter(c["font"] for c in vc).most_common(1)[0][0],
                              Counter(c["size"] for c in vc).most_common(1)[0][0], vc)
    if len(located) < 3:
        return []                                  # too little to establish how values are normally typeset
    ref_font = Counter(v[0] for v in located.values()).most_common(1)[0][0]
    ref_size = Counter(v[1] for v in located.values()).most_common(1)[0][0]
    out = []
    for fname, (vf, vs, vc) in located.items():
        if (vf != ref_font or abs(vs - ref_size) > 0.4) and font_freq[vf] / total < 0.05:
            f = fields[fname]
            out.append(_f(doc, "high", "ANOM-FONT", f"Different font in '{fname.replace('_', ' ')}'",
                          f"The value '{f['value']}' is set in {vf} {vs}pt, while the other {len(located) - 1} field values "
                          f"use {ref_font} {ref_size}pt. This font appears in only {font_freq[vf]} of {total} characters "
                          f"in the document — a common trace of a value typed over the original.",
                          {"field": fname, "value": f["value"], "value_font": f"{vf} {vs}pt",
                           "expected_font": f"{ref_font} {ref_size}pt", "page": vc[0]["page"],
                           "bbox": [round(vc[0]["x0"]), round(vc[0]["top"]), round(vc[-1]["x1"]), round(vc[-1]["bottom"])]}))
    return out


def overlap_checks(doc, chars: list[dict]) -> list[dict]:
    """Two different glyphs drawn at the same spot = text hidden under other text."""
    seen = {}
    hits = []
    for c in chars:
        if not c["text"].strip():
            continue
        key = (c["page"], round(c["x0"]), round(c["top"]))
        if key in seen and seen[key] != c["text"]:
            hits.append(key)
        seen[key] = c["text"]
    if len(hits) >= 3:
        return [_f(doc, "high", "ANOM-OVERLAP", "Overlapping text layers",
                   f"{len(hits)} positions have two different characters printed on top of each other.",
                   {"positions": [list(h) for h in hits[:10]]})]
    return []


def baseline_jitter_checks(doc, chars: list[dict], fields: dict) -> list[dict]:
    """Identifies vertical baseline misalignment on sensitive numeric fields (dates, intake, area)."""
    if not chars:
        return []
    out = []
    sensitive_keys = {"intake", "built_up_area_sqm", "land_area_acres", "valid_until", "issue_date", "certificate_no"}
    
    # Concatenate text from chars to find exact contiguous slices
    chars_text = "".join(c.get("text", "") for c in chars)

    for fname, f in fields.items():
        if fname not in sensitive_keys:
            continue
        val = str(f.get("value", "")).strip()
        if len(val) < 3:
            continue
        
        # Look for contiguous occurrence of val in chars
        idx = chars_text.find(val)
        if idx != -1:
            matched_chars = chars[idx : idx + len(val)]
            tops = [c["top"] for c in matched_chars if "top" in c]
            if len(tops) >= 3:
                std = float(np.std(tops))
                if std > 2.5:
                    p = matched_chars[0].get("page", 1)
                    x0 = round(min(c.get("x0", 0) for c in matched_chars))
                    y0 = round(min(c.get("top", 0) for c in matched_chars))
                    x1 = round(max(c.get("x1", 0) for c in matched_chars))
                    y1 = round(max(c.get("bottom", 0) for c in matched_chars))
                    out.append(_f(doc, "medium", "ANOM-ALIGN", f"Baseline misalignment in '{fname.replace('_', ' ')}'",
                                  f"Characters in '{f['value']}' exhibit abnormal vertical baseline jitter (variance {std:.1f}pt), "
                                  "indicating potential manual insertion or copy-paste over the original certificate.",
                                  {"field": fname, "value": f["value"], "baseline_std": round(std, 2), "page": p,
                                   "bbox": [x0, y0, x1, y1]}))
    return out


def date_checks(doc, fields: dict, today: date) -> list[dict]:
    out = []
    spec = config.documents().get(doc["declared_type"], {})
    dates = {k: date.fromisoformat(v["normalized"]) for k, v in fields.items()
             if k in (spec.get("date_fields") or []) and v.get("normalized")}
    issue = dates.get("issue_date") or dates.get("payment_date")
    if issue and issue > today:
        out.append(_f(doc, "high", "ANOM-DATE", "Issue date is in the future",
                      f"Issued {issue:%d-%m-%Y}, which is after today ({today:%d-%m-%Y}).", {"issue_date": issue.isoformat()}))
    if issue and dates.get("valid_until"):
        span = (dates["valid_until"] - issue).days
        if span < 0:
            out.append(_f(doc, "high", "ANOM-DATE", "Valid-until date before issue date",
                          f"Document expires {abs(span)} days before it was issued.", {"span_days": span}))
        elif span > 365 * 6:
            out.append(_f(doc, "medium", "ANOM-DATE", "Unusually long validity",
                          f"Validity of {span // 365} years is atypical for this document type.", {"span_days": span}))
    return out


# ------------------------------------------------------------------ images

def ela_check(doc, img: Image.Image) -> list[dict]:
    """Error Level Analysis for JPEG scans: regions re-compressed differently stand out."""
    rgb = img.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=90)
    re_img = Image.open(io.BytesIO(buf.getvalue()))
    diff = np.abs(np.asarray(rgb, dtype=np.int16) - np.asarray(re_img, dtype=np.int16)).mean(axis=2)
    h, w = diff.shape
    bs = 32
    blocks = [diff[y:y + bs, x:x + bs].mean() for y in range(0, h - bs, bs) for x in range(0, w - bs, bs)]
    if not blocks:
        return []
    med, top = float(np.median(blocks)), float(np.max(blocks))
    if top > 12 and top > 5 * max(med, 0.5):
        return [_f(doc, "low", "ANOM-ELA", "Uneven compression levels (ELA)",
                   f"One region's error level ({top:.1f}) is far above the image median ({med:.1f}); "
                   "can indicate pasted content, but also stamps or signatures.", {"max_block": round(top, 1), "median": round(med, 1)})]
    return []


def copy_move_checks(doc, img: Image.Image) -> list[dict]:
    """Copy-move indicator: the same seal, stamp or signature pasted at two places on one page.

    Only coloured ink is examined (seals, stamps and signatures are usually blue, violet, red or green).
    Black printed text repeats the same glyphs everywhere and would otherwise look "cloned". Matching
    ORB keypoints are grouped by their displacement; a flag needs many matches sharing one displacement
    whose source points form one compact patch, which is what a pasted stamp looks like.
    """
    try:
        import cv2
        from collections import Counter
        rgb = np.array(img.convert("RGB"))
        h, w = rgb.shape[:2]
        scale = min(1.0, 1600.0 / max(h, w))
        if scale < 1.0:
            rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        ink = ((hsv[..., 1] > 70) & (hsv[..., 2] > 40) & (hsv[..., 2] < 235)).astype(np.uint8) * 255
        # ignore large solid colour areas (letterhead bands, photos): keep thin strokes only
        solid = cv2.dilate(cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8)), np.ones((15, 15), np.uint8))
        ink = cv2.dilate(cv2.subtract(ink, solid), np.ones((5, 5), np.uint8))
        if cv2.countNonZero(ink) < 400:
            return []
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        orb = cv2.ORB_create(nfeatures=3000, edgeThreshold=15, patchSize=15)
        kp, des = orb.detectAndCompute(gray, ink)
        if des is None or len(kp) < 30:
            return []
        # A stamp is mostly rings and lettering, so a feature's nearest look-alikes are often on the same
        # stamp; look further down each feature's match list for a twin elsewhere on the page.
        matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(des, des, k=min(12, len(kp)))
        pairs = []
        for m_list in matches:
            for m in m_list[1:]:
                p1, p2 = kp[m.queryIdx].pt, kp[m.trainIdx].pt
                if m.distance < 40 and np.hypot(p1[0] - p2[0], p1[1] - p2[1]) > 40 and p1 < p2:
                    pairs.append((p1, p2))                        # each pair once (p1 < p2)
        if not pairs:
            return []
        # Vote for the shift between the two copies. Ring-shaped features pair with slightly different
        # points, so shifts wobble by a few tens of pixels: bin them and count each bin with its neighbours.
        B = 20.0
        d = np.array([(b[0] - a[0], b[1] - a[1]) for a, b in pairs])
        cells = Counter((int(round(x / B)), int(round(y / B))) for x, y in d)
        votes = {c: sum(cells.get((c[0] + i, c[1] + j), 0) for i in (-1, 0, 1) for j in (-1, 0, 1)) for c in cells}
        gh, gw = gray.shape
        for cell, size in sorted(votes.items(), key=lambda kv: -kv[1])[:8]:
            if size < 25:
                break
            sel = (np.abs(d[:, 0] / B - cell[0]) <= 1.5) & (np.abs(d[:, 1] / B - cell[1]) <= 1.5)
            src = np.array([pairs[i][0] for i in np.nonzero(sel)[0]])
            xs, ys = src[:, 0], src[:, 1]
            if (xs.max() - xs.min()) > 0.25 * gw or (ys.max() - ys.min()) > 0.25 * gh:
                continue                                          # spread over the page: repeated print, not a patch
            if np.hypot(*np.median(d[sel], axis=0)) < max(xs.max() - xs.min(), ys.max() - ys.min()):
                continue                                          # shift smaller than the patch: one ring matching itself
            sx = lambda v: int(round(float(v) / scale))
            off = [sx(np.median(d[sel, 0])), sx(np.median(d[sel, 1]))]
            return [_f(doc, "high", "ANOM-COPYMOVE", "Suspected copy-move forgery",
                       f"{int(sel.sum())} matching ink features appear twice on the page, shifted by about "
                       f"({off[0]}, {off[1]}) px — consistent with a seal, stamp or signature pasted at a second place.",
                       {"keypoint_cluster_size": int(sel.sum()), "total_matches": len(pairs), "page": 1, "offset_px": off,
                        "bbox": [sx(xs.min()), sx(ys.min()), sx(xs.max()), sx(ys.max())]})]
    except Exception as e:                                # never block validation on this indicator
        import logging
        logging.getLogger(__name__).warning("copy-move check skipped for %s: %s", doc.get("original_name"), e)
    return []


def exif_manipulation_checks(doc, img: Image.Image | None) -> list[dict]:
    """Checks for editing software signatures in EXIF and stripped camera metadata on photos."""
    out = []
    if not img:
        return out
    try:
        exif = img.getexif()
        software = (exif.get(0x0131) or "").lower() if exif else ""
        if any(tool in software for tool in ["photoshop", "gimp", "illustrator", "paint.net", "coreldraw"]):
            out.append(_f(doc, "high", "ANOM-EXIF-EDIT", "Image processed in graphic editing software",
                          f"EXIF metadata indicates the image was modified with '{software}'.",
                          {"software": software}))
        if doc.get("declared_type") == "infra_photo" and (not exif or len(exif) < 2):
            out.append(_f(doc, "medium", "ANOM-EXIF-STRIPPED", "Camera metadata stripped from campus photograph",
                          "Photo does not contain standard camera EXIF metadata (Make/Model/Lens), indicating it was exported or resaved through a graphics editor.",
                          {"exif_tags_count": len(exif) if exif else 0}))
    except Exception:
        pass
    return out


# ------------------------------------------------------------------ cross-document

def duplicate_checks(doc, others: list[dict], own_name: str | None = None) -> list[dict]:
    """others: documents from OTHER applications (sha256, dhash, application ref, institution).
    If the document names this application's own institution it is probably the original,
    so the copy elsewhere is reported as information, not as a flag against this applicant."""
    from difflib import SequenceMatcher
    from .extract import normalize_name
    out = []
    doc_name = (((doc.get("extraction") or {}).get("fields") or {}).get("institution_name") or {}).get("value")
    names_self = bool(doc_name and own_name and
                      SequenceMatcher(None, normalize_name(doc_name), normalize_name(own_name)).ratio() >= 0.88)
    for o in others:
        if o["sha256"] == doc["sha256"] and o["institution_id"] != doc.get("institution_id"):
            if names_self:
                out.append(_f(doc, "info", "ANOM-DUP-ORIGIN", "A copy of this document appears in another application",
                              f"Byte-identical file found in {o['app_ref']} ({o['institution_id']}). This document names "
                              f"this institution, so it is likely the original.",
                              {"other_document_id": o["id"], "other_application": o["app_ref"]}))
            else:
                out.append(_f(doc, "high", "ANOM-DUP", "Identical file submitted by another institution",
                              f"Byte-identical to '{o['original_name']}' in application {o['app_ref']} ({o['institution_id']}).",
                              {"other_document_id": o["id"], "other_application": o["app_ref"], "sha256": doc["sha256"][:16],
                               "name_on_document": doc_name}))
            continue
        if (doc["declared_type"] == "infra_photo" or o["declared_type"] != doc["declared_type"]
                or o["institution_id"] == doc.get("institution_id")):
            continue
        # Same certificate / transaction number presented by two institutions.
        mine, theirs = _ref_no(doc), _ref_no(o)
        if mine and mine == theirs:
            out.append(_f(doc, "high", "ANOM-REFREUSE", "Reference number also used by another institution",
                          f"Number '{mine}' also appears on '{o['original_name']}' in {o['app_ref']} ({o['institution_id']}). "
                          f"A certificate number should belong to one institution.",
                          {"reference": mine, "other_document_id": o["id"], "other_application": o["app_ref"]}))
            continue
        # Near-duplicate: same content re-saved/re-scanned. Page-image hashes are useless here because
        # every certificate from one authority shares a template, so compare the full text — strictly,
        # because short template-heavy certificates are naturally very similar.
        if doc.get("text") and o.get("text") and not names_self:
            a, b = _norm_text(doc["text"]), _norm_text(o["text"])
            sm = SequenceMatcher(None, a, b, autojunk=False)
            if sm.real_quick_ratio() >= 0.99 and sm.quick_ratio() >= 0.99 and sm.ratio() >= 0.99:
                out.append(_f(doc, "high", "ANOM-NEARDUP", "Same content as another institution's document",
                              f"Text is {sm.ratio():.0%} identical to '{o['original_name']}' in {o['app_ref']} "
                              f"({o['institution_id']}), although the files differ (re-saved or re-scanned copy?).",
                              {"other_document_id": o["id"], "other_application": o["app_ref"],
                               "text_similarity": round(sm.ratio(), 3), "name_on_document": doc_name}))
    return out


def _ref_no(d: dict) -> str | None:
    ex = d.get("extraction")
    if isinstance(ex, str):
        import json
        ex = json.loads(ex)
    fields = (ex or {}).get("fields") or {}
    for k in ("certificate_no", "transaction_id"):
        v = (fields.get(k) or {}).get("normalized")
        if v:
            return str(v).upper()
    return None


def _norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", t.lower())[:4000]


def phash_collision_checks(doc: dict, others: list[dict]) -> list[dict]:
    """Check perceptual hash collisions across other institutions' uploaded documents."""
    out = []
    my_phash = doc.get("phash")
    if not my_phash:
        return []
    for o in others:
        if o.get("phash") and o.get("institution_id") != doc.get("institution_id"):
            dist = hamming(my_phash, o["phash"])
            if dist <= 5:
                out.append(_f(doc, "high", "ANOM-PHASH-COLLISION", "Perceptual image collision across institutions",
                              f"Document visually matches (Hamming distance {dist}/64) '{o.get('original_name')}' "
                              f"submitted by institution {o.get('institution_id')} in application {o.get('app_ref')}.",
                              {"other_document_id": o["id"], "other_application": o.get("app_ref"), "hamming_dist": dist}))
    return out
