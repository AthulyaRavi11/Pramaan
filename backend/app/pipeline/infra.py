"""Infrastructure compliance assistance (advisory).

1. Declared infrastructure vs configurable norms (infra_norms.yaml).
2. Photo-evidence quality and reuse checks with computer vision:
   blur (Laplacian variance), darkness, near-duplicate photos submitted as
   different rooms (perceptual hash), and coverage of required room types.
Outcomes recommend "additional evidence" or "physical inspection"; they never
decide compliance on their own.
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image

from ..core import config
from .anomaly import hamming

ADVISORY = "Advisory — for review by an authorized official; may warrant additional evidence or inspection."


def _f(rule, sev, title, reason, evidence, doc_id=None):
    return {"module": "infrastructure", "rule_id": rule, "severity": sev, "title": title, "reason": reason,
            "document_id": doc_id, "evidence": dict(evidence, note=ADVISORY), "ref": "Infra norms (configurable)"}


def norms_check(form: dict) -> tuple[dict, list[dict]]:
    n = config.infra_norms()
    req = {"classrooms": 0, "labs": 0, "built_up_area_sqm": 0.0}
    total_intake = 0
    for p in form.get("programmes", []):
        spec = n["per_programme"].get(p.get("level"))
        if not spec:
            continue
        total_intake += p["intake"]
        req["classrooms"] += math.ceil(p["intake"] / spec["classroom_per_intake"])
        req["labs"] += spec["lab_min_per_programme"]
        req["built_up_area_sqm"] += p["intake"] * spec["built_up_area_sqm_per_intake"]
    declared = {k: form.get(k) for k in ("classrooms", "labs", "built_up_area_sqm")}
    out = []
    for k, need in req.items():
        have = declared.get(k)
        if have is not None and have < need:
            out.append(_f("INFRA-NORM", "medium", f"Declared {k.replace('_', ' ')} below norm",
                          f"Declared {have:g}, norm for requested intake is {need:g} (shortfall {need - have:g}).",
                          {"declared": have, "required": need, "basis": "sum over programmes"}))

    # Land requirement check based on geographic classification
    land = n.get("land", {})
    land_mins = land.get("min_acres_by_location", {})
    geo_class = (form.get("geographic_classification") or form.get("land_category") or land.get("default_location", "Urban")).capitalize()
    land_min = land_mins.get(geo_class, land_mins.get(land.get("default_location", "Urban")))
    declared_land = form.get("land_area_acres")
    if land_min is not None and declared_land is not None and declared_land < land_min:
        out.append(_f("INFRA-LAND-SHORTFALL", "high", f"Land area below the configured norm for a {geo_class} location",
                      f"Declared land is {declared_land} acres; the configured minimum for a {geo_class} location is {land_min} acres.",
                      {"declared_acres": declared_land, "required_acres": land_min, "geographic_classification": geo_class,
                       "basis": "infra_norms.yaml → land.min_acres_by_location"}))

    # Built-up area breakdown (shares of the required built-up area, from infra_norms.yaml)
    shares = n.get("area_shares", {})
    if req["built_up_area_sqm"] > 0 and shares:
        inst_need = req["built_up_area_sqm"] * shares.get("instructional", 0)
        admin_need = req["built_up_area_sqm"] * shares.get("administrative", 0)
        if form.get("instructional_area_sqm") and form["instructional_area_sqm"] < inst_need:
            out.append(_f("INFRA-INSTRUCTIONAL-AREA", "medium", "Instructional area below norm",
                          f"Declared instructional area ({form['instructional_area_sqm']:.0f} sqm) is below requirement ({inst_need:.0f} sqm).",
                          {"declared": form["instructional_area_sqm"], "required": round(inst_need, 1)}))
        if form.get("admin_area_sqm") and form["admin_area_sqm"] < admin_need:
            out.append(_f("INFRA-ADMIN-AREA", "low", "Administrative area below norm",
                          f"Declared administrative area ({form['admin_area_sqm']:.0f} sqm) is below requirement ({admin_need:.0f} sqm).",
                          {"declared": form["admin_area_sqm"], "required": round(admin_need, 1)}))

    # Faculty & Cadre Ratio (Professor : Associate Prof : Asst Prof = 1 : 2 : 6)
    fac = form.get("faculty_count")
    ratio_max = n["faculty"]["student_faculty_ratio_max"]
    if fac and total_intake and total_intake / fac > ratio_max:
        out.append(_f("INFRA-FACULTY", "medium", "Student–faculty ratio above norm",
                      f"Annual intake {total_intake} ÷ {fac} faculty = {total_intake / fac:.1f}; maximum {ratio_max}.",
                      {"intake": total_intake, "faculty": fac, "ratio": round(total_intake / fac, 1), "max": ratio_max}))

    profs = form.get("professors_count")
    assoc = form.get("assoc_professors_count")
    asst = form.get("asst_professors_count")
    if profs is not None and assoc is not None and asst is not None and (profs + assoc + asst) > 0:
        tot_cadre = profs + assoc + asst
        cadre = n["faculty"].get("cadre_ratio", [1, 2, 6])          # professor : associate : assistant
        exp_profs = max(1, math.floor(tot_cadre * cadre[0] / sum(cadre)))
        if profs < exp_profs:
            out.append(_f("INFRA-CADRE-DEFICIT", "medium", "Cadre ratio non-compliant: Professor deficit",
                          f"Institution reports {profs} Professors for {tot_cadre} faculty (configured cadre ratio "
                          f"{':'.join(str(x) for x in cadre)} needs at least {exp_profs}).",
                          {"professors": profs, "required_min_professors": exp_profs, "cadre_total": tot_cadre}))

    summary = {"required": req, "declared": declared, "total_intake": total_intake, "faculty": fac,
               "geographic_classification": geo_class, "land_min_acres": land_min}
    return summary, out


def extract_geo_metadata(img: Image.Image) -> dict:
    """Extract EXIF GPS metadata if present."""
    try:
        exif = img.getexif()
        if not exif:
            return {"geo_tagged": False}
        from PIL.ExifTags import TAGS, GPSTAGS, IFD
        gps_info = {}
        try:
            gps_ifd = exif.get_ifd(IFD.GPSInfo)
            if gps_ifd:
                for g_id, g_val in gps_ifd.items():
                    gps_info[GPSTAGS.get(g_id, g_id)] = g_val
        except Exception:
            pass
        if not gps_info:
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag == "GPSInfo" and isinstance(value, dict):
                    for g_id, g_val in value.items():
                        gps_info[GPSTAGS.get(g_id, g_id)] = g_val
        if "GPSLatitude" in gps_info and "GPSLongitude" in gps_info:
            def _to_deg(val):
                if isinstance(val, (tuple, list)) and len(val) == 3:
                    return float(val[0]) + float(val[1]) / 60.0 + float(val[2]) / 3600.0
                return float(val)
            lat = _to_deg(gps_info["GPSLatitude"])
            if gps_info.get("GPSLatitudeRef") == "S":
                lat = -lat
            lon = _to_deg(gps_info["GPSLongitude"])
            if gps_info.get("GPSLongitudeRef") == "W":
                lon = -lon
            return {"geo_tagged": True, "latitude": round(lat, 6), "longitude": round(lon, 6)}
    except Exception:
        pass
    return {"geo_tagged": False}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def photo_metrics(img: Image.Image) -> dict:
    # Sharpness (variance of the Laplacian) depends on resolution: the same scene scores lower the more
    # pixels it has. Score every photo at a common width so a sharp 12-megapixel phone photo is not
    # called blurry and a small one is not called sharp just for being small.
    rgb = img.convert("RGB")
    if rgb.width > 640:
        rgb = rgb.resize((640, max(1, round(rgb.height * 640 / rgb.width))), Image.LANCZOS)
    g = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2GRAY)
    return {"blur_var": float(cv2.Laplacian(g, cv2.CV_64F).var()), "brightness": float(g.mean()),
            "width": img.width, "height": img.height, "geo": extract_geo_metadata(img)}


_orb = None


def _gray(img: Image.Image, width: int = 640) -> np.ndarray:
    g = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    return cv2.resize(g, (width, int(width * g.shape[0] / g.shape[1])))


def _band(g: np.ndarray) -> np.ndarray:
    g = g.astype(np.float32)
    return cv2.GaussianBlur(g, (0, 0), 1.5) - cv2.GaussianBlur(g, (0, 0), 6)


def reuse_score(img_a: Image.Image, img_b: Image.Image) -> tuple[float, int]:
    """Is B the same photograph as A (possibly cropped, resized or brightened)?
    1. ORB keypoints + RANSAC homography align A onto B.
    2. Correlate fine image texture (band-pass) in the overlap. A re-used photo keeps its
       texture almost exactly (≈0.99); two different rooms do not, even if similar-looking.
    Returns (texture correlation, RANSAC inliers)."""
    global _orb
    _orb = _orb or cv2.ORB_create(1500)
    ga, gb = _gray(img_a), _gray(img_b)
    ka, da = _orb.detectAndCompute(ga, None)
    kb, db = _orb.detectAndCompute(gb, None)
    if da is None or db is None:
        return 0.0, 0
    m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    if len(m) < 10:
        return 0.0, 0
    src = np.float32([ka[x.queryIdx].pt for x in m])
    dst = np.float32([kb[x.trainIdx].pt for x in m])
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None:
        return 0.0, 0
    warped = cv2.warpPerspective(ga, H, (gb.shape[1], gb.shape[0]))
    valid = cv2.warpPerspective(np.ones_like(ga), H, (gb.shape[1], gb.shape[0]))
    valid = cv2.erode(valid, np.ones((15, 15), np.uint8)) > 0
    if valid.mean() < 0.5:
        return 0.0, int(mask.sum())
    return float(np.corrcoef(_band(warped)[valid], _band(gb)[valid])[0, 1]), int(mask.sum())


def photo_checks(photos: list[dict], campus_coords: dict | None = None) -> tuple[dict, list[dict]]:
    """photos: [{doc, metrics, dhash, image}]"""
    cfg = config.infra_norms()["photo_evidence"]
    max_geo = cfg["max_geo_distance_km"]
    out = []
    for p in photos:
        d, m = p["doc"], p["metrics"]
        if m["blur_var"] < cfg["min_blur_variance"]:
            out.append(_f("INFRA-PHOTO-BLUR", "low", f"Photo too blurry to assess: {d['original_name']}",
                          f"Sharpness score {m['blur_var']:.0f} is below {cfg['min_blur_variance']}. Request a clearer photo.",
                          {"document": d["original_name"], "tag": d.get("tag"), "blur_var": round(m["blur_var"], 1)}, d["id"]))
        if m["brightness"] < cfg["min_brightness"]:
            out.append(_f("INFRA-PHOTO-DARK", "low", f"Photo too dark: {d['original_name']}",
                          f"Mean brightness {m['brightness']:.0f} is below {cfg['min_brightness']}.",
                          {"document": d["original_name"], "brightness": round(m["brightness"], 1)}, d["id"]))

        # GPS / Geo-tag validation
        geo = m.get("geo") or {}
        if geo.get("geo_tagged") and campus_coords and campus_coords.get("latitude") and campus_coords.get("longitude"):
            dist = haversine_km(geo["latitude"], geo["longitude"], float(campus_coords["latitude"]), float(campus_coords["longitude"]))
            if dist > max_geo:
                out.append(_f("INFRA-GEO-MISMATCH", "high", f"Photo GPS outside campus perimeter: {d['original_name']}",
                              f"Photo GPS coordinates ({geo['latitude']:.4f}, {geo['longitude']:.4f}) are {dist:.1f} km away from registered AICTE campus location ({campus_coords['latitude']}, {campus_coords['longitude']}). Max allowable is {max_geo} km.",
                              {"document": d["original_name"], "photo_coords": f"{geo['latitude']}, {geo['longitude']}",
                               "campus_coords": f"{campus_coords['latitude']}, {campus_coords['longitude']}",
                               "distance_km": round(dist, 2), "max_allowed_km": max_geo,
                               "recommendation": "Physical inspection or re-submission with verified on-campus coordinates"}, d["id"]))
        elif not geo.get("geo_tagged"):
            out.append(_f("INFRA-GEO-MISSING", "low", f"Photo lacks verifiable GPS geo-tag: {d['original_name']}",
                          "Image file does not contain EXIF GPS metadata. Physical inspection or geo-tagged camera submission recommended.",
                          {"document": d["original_name"], "recommendation": "Verify on site during physical inspection"}, d["id"]))
    assessable = [p for p in photos if p["metrics"]["blur_var"] >= cfg["min_blur_variance"]]
    for i, a in enumerate(assessable):
        for b in assessable[i + 1:]:
            if a["doc"].get("tag") == b["doc"].get("tag"):
                continue
            dist = hamming(a["dhash"], b["dhash"])
            if dist == 0:
                corr, inliers = 1.0, -1
            else:
                corr, inliers = reuse_score(a["image"], b["image"])
            if corr >= cfg["reuse_texture_corr_min"]:
                out.append(_f("INFRA-PHOTO-DUP", "high", "Same photo submitted for different rooms",
                              f"'{a['doc']['original_name']}' ({a['doc'].get('tag')}) and '{b['doc']['original_name']}' "
                              f"({b['doc'].get('tag')}) align geometrically and share {corr:.1%} of fine image texture — "
                              f"the same photograph, cropped or re-edited.",
                              {"photo_a": a["doc"]["original_name"], "photo_b": b["doc"]["original_name"],
                               "photo_a_id": a["doc"]["id"], "photo_b_id": b["doc"]["id"],
                               "tag_a": a["doc"].get("tag"), "tag_b": b["doc"].get("tag"),
                               "texture_correlation": round(corr, 4), "ransac_inliers": inliers, "dhash_distance": dist,
                               "recommendation": "Physical inspection or fresh geo-tagged photos"}, b["doc"]["id"]))
    tags = {(p["doc"].get("tag") or "").split("-")[0].lower() for p in photos}
    missing = [t for t in cfg["require_tag_per_room_type"] if t not in tags]
    if photos and missing:
        out.append(_f("INFRA-PHOTO-COVER", "medium", "Photo evidence missing for some room types",
                      f"No photo tagged as: {', '.join(missing)}.", {"missing_room_types": missing}))
    summary = {"photos": len(photos), "room_types": sorted(t for t in tags if t)}
    return summary, out


def compute_inspection_risk_score(findings: list[dict], verifications: list[dict], infra_summary: dict | None = None) -> dict:
    """Calculates overall physical inspection risk score (0-100) recommending EVC vs Virtual Scrutiny."""
    score = 0.0
    factors = []

    highs = [f for f in findings if f.get("severity") == "high"]
    meds = [f for f in findings if f.get("severity") == "medium"]

    if highs:
        add = min(len(highs) * 25.0, 50.0)
        score += add
        factors.append(f"{len(highs)} critical/high-severity anomaly flag(s) (+{add:.0f} pts)")
    if meds:
        add = min(len(meds) * 10.0, 30.0)
        score += add
        factors.append(f"{len(meds)} medium-severity discrepancy flag(s) (+{add:.0f} pts)")

    mismatches = [v for v in verifications if v.get("status") in ("MISMATCH", "MISMATCH_DETECTED")]
    unavail = [v for v in verifications if v.get("status") in ("SOURCE_UNAVAILABLE", "MANUAL_REVIEW", "MANUAL_REVIEW_REQUIRED")]
    if mismatches:
        score += 35.0
        factors.append("Direct issuing authority registry mismatch detected (+35 pts)")
    elif unavail:
        score += 15.0
        factors.append("Issuing authority registry unavailable / manual review pending (+15 pts)")

    if infra_summary:
        decl = infra_summary.get("declared", {})
        req = infra_summary.get("required", {})
        for k in ("classrooms", "labs", "built_up_area_sqm"):
            if decl.get(k) is not None and req.get(k) is not None and decl[k] < req[k]:
                score += 15.0
                factors.append(f"Shortfall in declared {k.replace('_', ' ')} below norm (+15 pts)")
                break

    score = min(max(round(score, 1), 0.0), 100.0)
    recommendation = "EVC_PHYSICAL_VISIT" if score >= 40.0 else "VIRTUAL_SCRUTINY_ELIGIBLE"
    return {
        "risk_score": score,
        "recommendation": recommendation,
        "recommendation_label": "Expert Visiting Committee (EVC) Physical Visit Recommended" if score >= 40.0 else "Eligible for Virtual Approval",
        "risk_factors": factors,
    }
