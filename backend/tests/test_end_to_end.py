"""End-to-end tests on the three demo applications.

    cd backend && python -m pytest -q

Uses a throw-away database and storage folder, so it never touches your demo data.
Needs the synthetic data (python scripts/generate_synthetic.py) and Tesseract installed.
"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_tmp = tempfile.mkdtemp(prefix="pramaan-test-")
os.environ["PRAMAAN_STORAGE_DIR"] = _tmp
os.environ["PRAMAAN_DB"] = str(Path(_tmp) / "test.db")
os.environ["PRAMAAN_TODAY"] = "2026-10-21"
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import init_db, tx  # noqa: E402
from app.core.security import hash_password  # noqa: E402
import app.main as api  # noqa: E402
from app.main import app  # noqa: E402

# The tests log in many times through the real API. The CAPTCHA and per-IP rate limits are for
# people at a browser, so they are switched off here; test_login_requires_captcha checks the
# real login path separately.
_real_verify_captcha = api.verify_captcha
api.verify_captcha = lambda *a, **k: (True, "")
api.security_guard.is_rate_limited = lambda *a, **k: False

PW = "demo1234"
DEMO = json.loads((ROOT / "data" / "demo_manifest.json").read_text())


@pytest.fixture(scope="module")
def client():
    init_db()
    with tx() as c:
        c.execute("INSERT INTO users(username,full_name,pw_hash,role) VALUES ('officer','Officer',?,'officer')", (hash_password(PW),))
        c.execute("INSERT INTO users(username,full_name,pw_hash,role) VALUES ('admin','Admin',?,'admin')", (hash_password(PW),))
        for m in DEMO:
            c.execute("INSERT INTO users(username,full_name,pw_hash,role,institution_id) VALUES (?,?,?,?,?)",
                      (m["user"], m["form"]["institution_name"], hash_password(PW), "institution", m["institution_id"]))
    with TestClient(app) as cl:
        cl.app_ids = {}
        for m in DEMO:                      # Coromandel first: Ganga Valley re-uses its NBA certificate
            h = auth(cl, m["user"])
            app_id = cl.post("/api/applications", json={"category": m["category"], **m["form"]}, headers=h).json()["id"]
            for d in m["documents"]:
                p = ROOT / m["dir"] / d["file"]
                mime = "application/pdf" if p.suffix == ".pdf" else "image/jpeg"
                data = {"declared_type": d["declared_type"], **({"tag": d["tag"]} if d.get("tag") else {})}
                r = cl.post(f"/api/applications/{app_id}/documents", data=data, files={"file": (d["file"], p.read_bytes(), mime)}, headers=h)
                assert r.status_code == 200, r.text
            assert cl.post(f"/api/applications/{app_id}/submit", headers=h).status_code == 200
            cl.app_ids[m["user"]] = app_id
        yield cl


def auth(cl, user):
    return {"Authorization": f"Bearer {cl.post('/api/auth/login', json={'username': user, 'password': PW}).json()['token']}"}


def findings(cl, user):
    r = cl.get(f"/api/applications/{cl.app_ids[user]}", headers=auth(cl, "officer")).json()
    return r, {f["rule_id"] for f in r["findings"]}


def test_clean_application_has_no_high_or_medium_flags(client):
    r, _ = findings(client, "coromandel")
    bad = [f["title"] for f in r["findings"] if f["severity"] in ("high", "medium")]
    assert bad == []


def test_deficiencies_are_found(client):
    _, rules = findings(client, "sahyadri")
    for rid in ["EOA-VAL-01", "EOA-VAL-04", "DOC-CLASS", "EOA-REC-06", "EOA-REC-03", "EOA-REC-04", "EOA-CON-03",
                "INFRA-FACULTY", "INFRA-PHOTO-BLUR", "INFRA-PHOTO-COVER"]:
        assert rid in rules, rid


def test_manipulation_indicators_are_found(client):
    r, rules = findings(client, "gangavalley")
    for rid in ["ANOM-FONT", "ANOM-META", "VER-MISMATCH", "ANOM-DUP", "EOA-CON-02", "INFRA-PHOTO-DUP"]:
        assert rid in rules, rid
    font = next(f for f in r["findings"] if f["rule_id"] == "ANOM-FONT")
    assert font["evidence"]["field"] == "valid_until" and len(font["evidence"]["bbox"]) == 4
    qr = next(v for v in r["verifications"] if v["method"] == "qr_signed" and v["status"] == "MISMATCH")
    assert any(not c["match"] and c["field"] == "valid_until" for c in qr["comparison"])


def test_every_finding_carries_evidence(client):
    for user in client.app_ids:
        r, _ = findings(client, user)
        for f in r["findings"]:
            assert f["reason"] and f["evidence"] is not None, f


def test_institution_cannot_see_others_or_forensic_flags(client):
    h = auth(client, "gangavalley")
    assert client.get(f"/api/applications/{client.app_ids['coromandel']}", headers=h).status_code == 403
    own = client.get(f"/api/applications/{client.app_ids['gangavalley']}", headers=h).json()
    assert {f["module"] for f in own["findings"]} <= {"rules", "extraction"}
    assert own["verifications"] == []


def test_institution_memo_and_alerts_hide_forensic_flags(client):
    h = auth(client, "gangavalley")
    memo = client.get(f"/api/applications/{client.app_ids['gangavalley']}/deficiency-memo", headers=h).json()
    assert not any(i["rule_id"].startswith(("ANOM", "VER", "INFRA")) for i in memo["deficiency_items"])
    officer_memo = client.get(f"/api/applications/{client.app_ids['gangavalley']}/deficiency-memo",
                              headers=auth(client, "officer")).json()
    assert any(i["rule_id"].startswith("ANOM") for i in officer_memo["deficiency_items"])
    # references come from the configured rule set, never invented clause numbers
    assert not any("Clause" in i["handbook_reference"] for i in officer_memo["deficiency_items"])
    alerts = client.get("/api/alerts", headers=h).json()
    assert not any(a["kind"] == "SUSPECTED_ANOMALY" for a in alerts)


def test_fresh_database_has_every_column():
    """A database created from scratch must have the columns the API writes (freeze workflow etc.)."""
    import sqlite3
    db = sqlite3.connect(os.environ["PRAMAAN_DB"])
    cols = {r[1] for r in db.execute("PRAGMA table_info(applications)")} | {r[1] for r in db.execute("PRAGMA table_info(documents)")}
    db.close()
    assert {"is_frozen", "storage_tier", "frozen_at", "unfreeze_requested", "unfreeze_remarks"} <= cols


def test_institution_cannot_review(client):
    r, _ = findings(client, "gangavalley")
    fid = r["findings"][0]["id"]
    assert client.post(f"/api/findings/{fid}/review", json={"status": "DISMISSED", "remark": "not me"},
                       headers=auth(client, "gangavalley")).status_code == 403


def test_approval_blocked_until_high_flags_reviewed(client):
    app_id = client.app_ids["gangavalley"]
    h = auth(client, "officer")
    r = client.post(f"/api/applications/{app_id}/decision", json={"decision": "RECOMMEND_FOR_APPROVAL", "remark": "all good here"}, headers=h)
    assert r.status_code == 409
    r = client.post(f"/api/applications/{app_id}/decision", json={"decision": "REFER_FOR_INSPECTION", "remark": "fire NOC and photos"}, headers=h)
    assert r.status_code == 200


def test_rejects_non_document_upload(client):
    h = auth(client, "coromandel")
    app_id = client.post("/api/applications", json={**DEMO[0]["form"], "category": "EOA"}, headers=h).json()["id"]
    r = client.post(f"/api/applications/{app_id}/documents", data={"declared_type": "affidavit"},
                    files={"file": ("x.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")}, headers=h)
    assert r.status_code == 415


def test_signed_letter_and_repository_copy(client):
    good, _ = findings(client, "coromandel")
    v = {(x["method"], x["status"]) for x in good["verifications"]}
    assert ("pdf_signature", "VERIFIED") in v and ("repository", "VERIFIED") in v
    bad, rules = findings(client, "gangavalley")
    assert {"VER-SIGNATURE", "VER-REPOSITORY"} <= rules
    sig = next(x for x in bad["verifications"] if x["method"] == "pdf_signature")
    assert "after it was digitally signed" in sig["response"]["message"]


def test_faculty_checked_against_records(client):
    _, rules = findings(client, "sahyadri")
    assert "EOA-REC-07" in rules
    _, clean = findings(client, "coromandel")
    assert "EOA-REC-07" not in clean


def test_pdf_report(client):
    h = auth(client, "officer")
    r = client.get(f"/api/applications/{client.app_ids['gangavalley']}/report.pdf", headers=h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and len(r.content) > 5000
    r = client.get(f"/api/applications/{client.app_ids['gangavalley']}/report.pdf", headers=auth(client, "gangavalley"))
    assert r.status_code == 200


def test_notifications_queued_without_smtp(client):
    out = client.get("/api/notifications", headers=auth(client, "sahyadri")).json()
    assert out and all(n["status"] == "QUEUED" for n in out) and all(n["recipient"] == "sahyadri" for n in out)


def test_retention_purges_files_but_keeps_decision(client):
    h = auth(client, "admin")
    app_id = client.app_ids["gangavalley"]          # recommendation was recorded in an earlier test
    pv = client.get("/api/admin/retention?days=0", headers=h).json()
    assert any(a["id"] == app_id for a in pv["eligible"])
    res = client.post("/api/admin/retention/run", json={"days": 0, "confirm": True}, headers=h).json()
    assert res["purged_documents"] > 0
    o = auth(client, "officer")
    d = client.get(f"/api/applications/{app_id}", headers=o).json()
    assert d["findings"] and all(x["purged"] for x in d["documents"])
    assert client.get(f"/api/documents/{d['documents'][0]['id']}/file", headers=o).status_code == 410
    assert client.post(f"/api/applications/{app_id}/validate", headers=o).status_code == 409


def test_audit_chain_detects_tampering(client):
    h = auth(client, "officer")
    assert client.get("/api/audit/verify", headers=h).json()["intact"] is True
    db = sqlite3.connect(os.environ["PRAMAAN_DB"])
    db.execute("UPDATE audit_log SET detail_json='{}' WHERE id=5")
    db.commit()
    db.close()
    v = client.get("/api/audit/verify", headers=h).json()
    assert v["intact"] is False and v["broken_at_id"] == 5


def test_login_requires_captcha(client):
    api.verify_captcha = _real_verify_captcha
    try:
        r = client.post("/api/auth/login", json={"username": "officer", "password": PW})
        assert r.status_code == 400 and "CAPTCHA" in r.json()["detail"]
        r = client.post("/api/auth/login", json={"username": "officer", "password": PW,
                                                 "captcha_id": "9999999999:bad", "captcha_code": "ABCDE"})
        assert r.status_code == 400
    finally:
        api.verify_captcha = lambda *a, **k: (True, "")


def test_submission_gate_blocks_missing_documents(client):
    h = auth(client, "coromandel")
    app_id = client.post("/api/applications", json={**DEMO[0]["form"], "category": "EOA"}, headers=h).json()["id"]
    r = client.post(f"/api/applications/{app_id}/submit", headers=h)
    assert r.status_code == 400 and "Mandatory document" in r.json()["detail"]
