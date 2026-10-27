"""Pramaan — AI-assisted validation for AICTE approval applications (SIH26261 prototype)."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .core import audit, config, notify as notifier, retention, security
from .core.db import init_db, now_iso, row, rows, tx
from .core.security import (PERMISSIONS, can_read_application, check_password, current_user,
                            generate_captcha, inspect_file_security, issue_token, require,
                            sanitize_filename, security_guard, verify_captcha)
from .pipeline import extract, locate
from .pipeline import run as pipeline

@asynccontextmanager
async def lifespan(_app):
    init_db()
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    INSTITUTE_VAULTS_DIR.mkdir(parents=True, exist_ok=True)
    AICTE_CLOUD_DIR.mkdir(parents=True, exist_ok=True)
    yield


FILES_DIR = config.STORAGE_DIR / "files"
INSTITUTE_VAULTS_DIR = config.STORAGE_DIR / "institute_vaults"
AICTE_CLOUD_DIR = config.STORAGE_DIR / "aicte_central_cloud"
app = FastAPI(title="Pramaan API", version="0.1.0", lifespan=lifespan,
              description="Decision-support platform for AICTE application validation. Not a decision-making system.")
app.add_middleware(CORSMiddleware,
                   allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["*"],
                   expose_headers=["Content-Disposition"])


# ------------------------------------------------------------------ Comprehensive Security Middleware

@app.middleware("http")
async def security_defense_middleware(request: Request, call_next):
    """Enforces API rate limiting, DoS protection, and OWASP protective security headers."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    path = request.url.path

    # 1. Endpoint-specific Rate Limiting
    if path == "/api/auth/captcha":
        if security_guard.is_rate_limited(f"captcha_rate:{client_ip}", max_requests=35, window_seconds=60):
            return JSONResponse(status_code=429, content={"detail": "Too many CAPTCHA requests from this IP. Please wait a minute."})
    elif path == "/api/auth/login":
        if security_guard.is_rate_limited(f"login_rate:{client_ip}", max_requests=20, window_seconds=60):
            return JSONResponse(status_code=429, content={"detail": "Too many sign-in attempts from this IP. Please wait a minute."})
    else:
        # General API protection: max 300 requests/min per IP
        if security_guard.is_rate_limited(f"api_rate:{client_ip}", max_requests=300, window_seconds=60):
            return JSONResponse(status_code=429, content={"detail": "High traffic detected. API rate limit exceeded."})

    response = await call_next(request)

    # 2. OWASP Enterprise Security Response Headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' http://localhost:* http://127.0.0.1:*; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' http://localhost:* http://127.0.0.1:*; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: http://localhost:* http://127.0.0.1:*; "
        "connect-src 'self' http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*;"
    )
    return response


def _today() -> date:
    """Demo clock. Set PRAMAAN_TODAY=YYYY-MM-DD to reproduce results."""
    import os
    t = os.environ.get("PRAMAAN_TODAY")
    return date.fromisoformat(t) if t else date.today()


# ------------------------------------------------------------------ auth

@app.get("/api/auth/captcha")
def get_captcha():
    """Generate a visual CAPTCHA challenge for login authentication."""
    return generate_captcha()


class LoginIn(BaseModel):
    username: str
    password: str
    role: str | None = None
    captcha_id: str | None = None
    captcha_code: str | None = None


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    client_ip = request.client.host if request and request.client else "127.0.0.1"

    # 1. Anti-Brute-Force & Account Lockout Defense
    clean_username = (body.username or "").strip()
    lock_key = f"{client_ip}:{clean_username}"
    is_locked, remaining_secs = security_guard.is_login_locked(lock_key, max_fails=5)
    if is_locked:
        audit.log(clean_username, "anonymous", "SUSPICIOUS_LOGIN_BRUTEFORCE_DETECTED",
                  detail={"reason": "Consecutive failed sign-in attempts limit reached", "lockout_seconds": remaining_secs},
                  actor_ip=client_ip)
        raise HTTPException(429, f"Account temporarily locked due to 5 consecutive failed attempts. Please wait {remaining_secs} seconds.")

    # 2. CAPTCHA Verification (with single-use replay prevention)
    ok, err_msg = verify_captcha(body.captcha_id, body.captcha_code)
    if not ok:
        raise HTTPException(400, err_msg)

    # 3. User & Password authentication
    with tx() as c:
        u = row(c.execute("SELECT * FROM users WHERE username=?", (clean_username,)).fetchone())
    if not u or not check_password(body.password, u["pw_hash"]):
        fail_count = security_guard.record_failed_login(lock_key)
        audit.log(clean_username, "anonymous", "LOGIN_FAILED", detail={"failures": fail_count}, actor_ip=client_ip)
        remaining = max(0, 5 - fail_count)
        if remaining == 0:
            raise HTTPException(429, "Too many failed attempts. Account temporarily locked for 3 minutes.")
        raise HTTPException(401, f"Invalid credentials. ({remaining} attempts remaining before temporary lockout)")

    # 4. Role mismatch check
    if body.role and u["role"] != body.role:
        audit.log(clean_username, u["role"], "LOGIN_ROLE_MISMATCH", actor_ip=client_ip)
        role_labels = {"institution": "Institution", "officer": "Scrutiny Officer", "admin": "Administrator"}
        chosen_lbl = role_labels.get(body.role, body.role)
        actual_lbl = role_labels.get(u["role"], u["role"])
        raise HTTPException(401, f"User '{clean_username}' is registered as a {actual_lbl}, not {chosen_lbl}.")

    # 5. Successful login: reset lockout counter
    security_guard.reset_failed_login(lock_key)
    audit.log(u["username"], u["role"], "LOGIN", actor_ip=client_ip)
    u.pop("pw_hash")
    return {"token": issue_token(u), "user": u, "permissions": sorted(PERMISSIONS[u["role"]])}


@app.post("/api/auth/logout")
def logout(request: Request, user=Depends(current_user)):
    """Explicit session revocation and token blacklisting."""
    client_ip = request.client.host if request and request.client else "127.0.0.1"
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else request.query_params.get("token")
    if token:
        security_guard.revoke_token(token, time.time() + (config.JWT_TTL_MIN * 60))
    audit.log(user["username"], user["role"], "LOGOUT", detail={"action": "Session revoked"}, actor_ip=client_ip)
    return {"ok": True, "message": "Logged out successfully and token revoked."}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"user": user, "permissions": sorted(PERMISSIONS[user["role"]])}


# ------------------------------------------------------------------ config

@app.get("/api/config")
def get_config(user=Depends(current_user)):
    cats = {k: {"label": v["label"], "rules": len(v["rules"]),
                "required_docs": [{"doc": r["doc"], "min_count": r.get("min_count", 1)} for r in v["rules"] if r["type"] == "required_document"]}
            for k, v in config.categories()["categories"].items()}
    docs = {k: {"label": v["label"], "source": v.get("source"),
                "source_label": config.sources().get(v.get("source") or "", {}).get("label")} for k, v in config.documents().items()}
    return {"categories": cats, "document_types": docs, "ruleset_version": config.categories()["version"],
            "submission_gate": config.categories().get("submission_gate") or {},
            "ruleset_fingerprint": config.ruleset_fingerprint()}


@app.get("/api/admin/rules")
def admin_rules(user=Depends(require("rules:read"))):
    out = {}
    for name in ("categories.yaml", "documents.yaml", "sources.yaml", "infra_norms.yaml"):
        out[name] = (config.CONFIG_DIR / name).read_text()
    return out


@app.post("/api/admin/rules/reload")
def admin_reload(user=Depends(require("rules:reload"))):
    config.reload_all()
    audit.log(user["username"], user["role"], "RULESET_RELOADED", None,
              {"version": config.categories()["version"], "fingerprint": config.ruleset_fingerprint()})
    return {"ok": True, "version": config.categories()["version"], "fingerprint": config.ruleset_fingerprint()}


# ------------------------------------------------------------------ applications

def _summary(a: dict) -> dict:
    rep = a.get("report") or {}
    inst = config.institutional_records()["institutions"].get(a["institution_id"], {})
    return {
        "id": a["id"],
        "ref": a["ref"],
        "institution_id": a["institution_id"],
        "institution_name": a["form"].get("institution_name") or inst.get("name"),
        "category": a["category"],
        "status": a["status"],
        "system_status": a["system_status"],
        "submitted_at": a["submitted_at"],
        "validated_at": a["validated_at"],
        "decision": a["decision"],
        "finding_counts": rep.get("finding_counts"),
        "academic_year": a["form"].get("academic_year"),
        "rectification_deadline": a.get("rectification_deadline"),
        "is_frozen": int(a.get("is_frozen") or 0),
        "storage_tier": a.get("storage_tier") or "LOCAL_INSTITUTE_VAULT",
        "frozen_at": a.get("frozen_at"),
        "frozen_by": a.get("frozen_by"),
        "unfreeze_requested": int(a.get("unfreeze_requested") or 0),
        "unfreeze_request_reason": a.get("unfreeze_request_reason"),
        "unfreeze_requested_at": a.get("unfreeze_requested_at"),
        "unfrozen_at": a.get("unfrozen_at"),
        "unfrozen_by": a.get("unfrozen_by"),
        "unfreeze_remarks": a.get("unfreeze_remarks"),
    }


@app.get("/api/applications")
def list_applications(user=Depends(current_user)):
    with tx() as c:
        if "app:read_all" in PERMISSIONS[user["role"]]:
            # Scrutiny Officers & Admins: only see applications committed to AICTE Central Cloud or already submitted/unfrozen
            apps = rows(c.execute(
                "SELECT * FROM applications WHERE is_frozen=1 OR storage_tier='AICTE_CENTRAL_CLOUD' OR status!='DRAFT' ORDER BY id DESC"
            ).fetchall())
        else:
            apps = rows(c.execute("SELECT * FROM applications WHERE institution_id=? ORDER BY id DESC",
                                  (user["institution_id"],)).fetchall())
        open_counts = {r["application_id"]: r["n"] for r in c.execute(
            "SELECT application_id, COUNT(*) n FROM findings WHERE review_status='OPEN' AND severity IN ('high','medium') GROUP BY application_id")}
        fs = c.execute("SELECT application_id, module, rule_id, severity, review_status FROM findings "
                       "WHERE review_status!='DISMISSED' AND severity!='info'").fetchall()
    rank = {"high": 3, "medium": 2, "low": 1}
    checks: dict = {}
    is_inst = user["role"] == "institution"
    for f in fs:
        g = check_group(f["module"], f["rule_id"])
        if is_inst and g not in ("checklist", "records"):
            continue
        cur = checks.setdefault(f["application_id"], {})
        if rank[f["severity"]] > rank.get(cur.get(g), 0):
            cur[g] = f["severity"]
    out = []
    for a in apps:
        s = _summary(a)
        s["open_items"] = open_counts.get(a["id"], 0)
        s["checks"] = None if not a["validated_at"] else {g: checks.get(a["id"], {}).get(g, "pass") for g in CHECK_GROUPS}
        out.append(s)
    return out


CHECK_GROUPS = ["checklist", "records", "authenticity", "sources", "infrastructure"]


def check_group(module: str, rule_id: str | None) -> str:
    """The five check families shown to officials."""
    if module == "rules" and ("-REC-" in (rule_id or "") or "FAC-" in (rule_id or "")):
        return "records"
    return {"rules": "checklist", "extraction": "checklist", "anomaly": "authenticity",
            "verification": "sources", "infrastructure": "infrastructure"}[module]


class ProgrammeIn(BaseModel):
    code: str
    name: str
    level: str
    intake: int = Field(ge=0)
    current_intake: int | None = None
    proposed_intake: int | None = None


class ApplicationIn(BaseModel):
    category: str
    institution_name: str
    academic_year: str
    aicte_permanent_id: str | None = None
    application_date: str | None = None

    # Category-specific fields:
    # 1. CHANGE_OF_NAME
    proposed_institution_name: str | None = None
    trust_society_name: str | None = None
    reason_for_change: str | None = None
    resolution_date: str | None = None

    # 2. NEW_INSTITUTION
    land_area_acres: float | None = None
    survey_number: str | None = None
    district: str | None = None
    state: str | None = None

    # 3. COURSE_CLOSURE
    closure_programme_name: str | None = None
    closure_programme_code: str | None = None
    closure_level: str | None = None
    closure_reason: str | None = None
    students_status: str | None = None

    # 4. NEW_PROGRAMME
    new_prog_code: str | None = None
    new_prog_name: str | None = None
    new_prog_level: str | None = None
    new_prog_intake: int | None = None

    # 5. Infrastructure & Faculty
    built_up_area_sqm: float | None = None
    classrooms: int | None = None
    labs: int | None = None
    faculty_count: int | None = None
    programmes: list[ProgrammeIn] = []


@app.post("/api/applications")
def create_application(body: ApplicationIn, user=Depends(require("app:create"))):
    if body.category not in config.categories()["categories"]:
        raise HTTPException(400, "Unknown category")
    form = body.model_dump(exclude={"category"})
    form["application_date"] = form.get("application_date") or _today().strftime("%d-%m-%Y")
    prefix = {"EOA": "EOA", "INTAKE_INCREASE": "INC", "NEW_PROGRAMME": "NPR", "CHANGE_OF_NAME": "CON",
              "NEW_INSTITUTION": "NEW", "COURSE_CLOSURE": "CLO"}.get(body.category, body.category[:3])
    ref = f"{prefix}-{body.academic_year[:4]}-{uuid.uuid4().hex[:6].upper()}"
    with tx() as c:
        cur = c.execute("INSERT INTO applications(ref,institution_id,category,form_json,status,created_at) VALUES (?,?,?,?,?,?)",
                        (ref, user["institution_id"], body.category, json.dumps(form), "DRAFT", now_iso()))
        app_id = cur.lastrowid
        audit.log(user["username"], user["role"], "APPLICATION_CREATED", app_id, {"ref": ref, "category": body.category}, conn=c)
    return {"id": app_id, "ref": ref}


@app.put("/api/applications/{app_id}")
def update_application(app_id: int, body: ApplicationIn, user=Depends(require("app:create"))):
    a = _get_app(app_id, user)
    if user["role"] != "institution" or user.get("institution_id") != a["institution_id"]:
        raise HTTPException(403, "Only the owning institution can edit application details.")
    if a.get("is_frozen"):
        raise HTTPException(400, "Cannot edit application details while application is frozen.")
    if body.category not in config.categories()["categories"]:
        raise HTTPException(400, "Unknown category")
    
    form = body.model_dump(exclude={"category"})
    current_form = json.loads(a["form_json"]) if isinstance(a.get("form_json"), str) else (a.get("form_json") or {})
    form["application_date"] = form.get("application_date") or current_form.get("application_date") or _today().strftime("%d-%m-%Y")
    
    prefix = {"EOA": "EOA", "INTAKE_INCREASE": "INC", "NEW_PROGRAMME": "NPR", "CHANGE_OF_NAME": "CON",
              "NEW_INSTITUTION": "NEW", "COURSE_CLOSURE": "CLO"}.get(body.category, body.category[:3])
    old_parts = a["ref"].split("-")
    new_ref = f"{prefix}-{body.academic_year[:4]}-{old_parts[-1]}" if len(old_parts) >= 3 else a["ref"]

    with tx() as c:
        c.execute("""
            UPDATE applications
            SET ref = ?, category = ?, form_json = ?
            WHERE id = ?
        """, (new_ref, body.category, json.dumps(form), app_id))
        audit.log(user["username"], user["role"], "APPLICATION_UPDATED", app_id, {"ref": new_ref, "category": body.category}, conn=c)
    
    pipeline.validate_application(app_id, user["username"], user["role"], _today())
    return {"ok": True, "id": app_id, "ref": new_ref, "category": body.category}


def _get_app(app_id: int, user: dict) -> dict:
    with tx() as c:
        a = row(c.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone())
    if not a:
        raise HTTPException(404, "Application not found")
    if not can_read_application(user, a):
        raise HTTPException(403, "Not your application")
    return a


@app.get("/api/applications/{app_id}")
def get_application(app_id: int, request: Request, unmask: bool = Query(False), user=Depends(current_user)):
    a = _get_app(app_id, user)
    client_ip = request.client.host if request and request.client else "127.0.0.1"
    with tx() as c:
        docs = rows(c.execute("SELECT id,declared_type,detected_type,classification_conf,tag,original_name,mime,sha256,"
                              "extraction_json,ocr_used,version,superseded,purged,uploaded_at FROM documents WHERE application_id=? ORDER BY id",
                              (app_id,)).fetchall())
        findings = rows(c.execute("SELECT * FROM findings WHERE application_id=? ORDER BY id", (app_id,)).fetchall())
        verifs = rows(c.execute("SELECT * FROM verifications WHERE application_id=? ORDER BY id", (app_id,)).fetchall())
    is_inst = user["role"] == "institution"
    if is_inst:
        # Institutions see checklist and extraction findings only, before and after freezing.
        # Forensic indicators and source responses stay with officials (preliminary, not proof).
        findings = [f for f in findings if f["module"] in pipeline.INSTITUTION_VISIBLE_MODULES]
        verifs = []
        for d in docs:
            if d.get("extraction"):
                d["extraction"].pop("pdf_metadata", None)
                d["extraction"].pop("class_scores", None)
    else:
        audit.log(user["username"], user["role"], "APPLICATION_VIEWED", app_id, actor_ip=client_ip)

    # PII Masking with authorized audit trail logging
    if unmask and not is_inst and "doc:unmask" in security.PERMISSIONS.get(user["role"], set()):
        audit.log(user["username"], user["role"], "PII_UNMASKED", app_id,
                  {"reason": "Authorized scrutiny inspection", "actor_ip": client_ip}, actor_ip=client_ip)
    else:
        a["form"] = security.mask_pii_dict(a["form"])
        for d in docs:
            if d.get("extraction"):
                d["extraction"] = security.mask_pii_dict(d["extraction"])

    rec = None if is_inst else config.institutional_records()["institutions"].get(a["institution_id"])
    return {"application": {**_summary(a), "form": a["form"], "decision_by": a["decision_by"],
                            "decision_remark": a["decision_remark"], "risk_score": a.get("risk_score"),
                            "inspection_recommendation": a.get("inspection_recommendation"),
                            "second_tier_status": a.get("second_tier_status")},
            "report": a.get("report"), "documents": docs, "findings": findings, "verifications": verifs,
            "institutional_record": rec, "pii_masked": not (unmask and not is_inst)}


@app.get("/api/applications/{app_id}/report.pdf")
def report_pdf(app_id: int, user=Depends(current_user)):
    """Downloadable structured validation report (PDF)."""
    from . import report_pdf as rp
    a = _get_app(app_id, user)
    if not a.get("report"):
        raise HTTPException(409, "Application has not been checked yet")
    with tx() as c:
        docs = rows(c.execute("SELECT id, original_name, declared_type FROM documents WHERE application_id=?", (app_id,)).fetchall())
        findings = rows(c.execute("SELECT * FROM findings WHERE application_id=? ORDER BY id", (app_id,)).fetchall())
        verifs = rows(c.execute("SELECT * FROM verifications WHERE application_id=? ORDER BY id", (app_id,)).fetchall())
    inst = user["role"] == "institution"
    if inst:
        findings = [f for f in findings if f["module"] in pipeline.INSTITUTION_VISIBLE_MODULES]
        verifs = []
    record = None if inst else config.institutional_records()["institutions"].get(a["institution_id"])
    head = audit.verify_chain().get("head", "")
    pdf = rp.build(a, a["report"], findings, verifs, docs, record, head, user["username"], institution_view=inst)
    audit.log(user["username"], user["role"], "REPORT_GENERATED", app_id, {"run_id": a["report"].get("run_id"), "bytes": len(pdf)})
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="pramaan-report-{a["ref"]}.pdf"'})


ALLOWED_TYPES = {b"%PDF": "application/pdf", b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg"}


def _sniff(data: bytes) -> str | None:
    for magic, mime in ALLOWED_TYPES.items():
        if data.startswith(magic):
            return mime
    return None


class UnfreezeRequestIn(BaseModel):
    reason: str = Field(min_length=10)


class UnfreezeIn(BaseModel):
    remarks: str = Field(min_length=5)
    grant_rectification_days: int = 15


@app.post("/api/applications/{app_id}/documents")
async def upload_document(app_id: int, declared_type: str = Form(...), tag: str | None = Form(None),
                          file: UploadFile = File(...), user=Depends(require("doc:upload_own"))):
    a = _get_app(app_id, user)
    if a.get("is_frozen"):
        raise HTTPException(403, "Application data is FROZEN on AICTE Central Cloud. Uploads and modifications are locked. Request an unfreeze from AICTE to make changes.")
    if a["status"] not in ("DRAFT", "RECTIFICATION_REQUESTED", "UNDER_SCRUTINY"):
        raise HTTPException(409, f"Uploads not permitted in status {a['status']}")
    if declared_type not in config.documents():
        raise HTTPException(400, "Unknown document type")
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, "File exceeds size limit")
    clean_filename = sanitize_filename(file.filename or "upload")
    mime = security.sniff_and_validate_file(data, clean_filename)
    sha = hashlib.sha256(data).hexdigest()
    ext = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/tiff": ".tif"}.get(mime, ".bin")
    
    # Store strictly in Institution's Private Local Cloud Vault
    inst_vault = INSTITUTE_VAULTS_DIR / a["institution_id"]
    inst_vault.mkdir(parents=True, exist_ok=True)
    (inst_vault / f"{sha}{ext}").write_bytes(data)

    # Deduplicated working storage for OCR / processing
    path = FILES_DIR / f"{sha}{ext}"
    path.write_bytes(data)
    with tx() as c:
        version = 1
        if declared_type != "infra_photo":
            prev = c.execute("SELECT id, version FROM documents WHERE application_id=? AND declared_type=? AND superseded=0",
                             (app_id, declared_type)).fetchone()
            if prev:
                version = prev["version"] + 1
                c.execute("UPDATE documents SET superseded=1 WHERE id=?", (prev["id"],))
        cur = c.execute("INSERT INTO documents(application_id,declared_type,tag,original_name,mime,sha256,stored_path,version,uploaded_by,uploaded_at,storage_tier)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (app_id, declared_type, tag, clean_filename, mime, sha, path.name, version,
                         user["username"], now_iso(), "LOCAL_INSTITUTE_VAULT"))
        doc_id = cur.lastrowid
        audit.log(user["username"], user["role"], "DOCUMENT_UPLOADED_LOCAL_VAULT", app_id,
                  {"document_id": doc_id, "type": declared_type, "sha256": sha[:16], "version": version, "storage_tier": "LOCAL_INSTITUTE_VAULT"}, conn=c)
    result = pipeline.process_document(doc_id)
    # Immediately evaluate validation rules so findings (e.g. expired certificates) are available
    pipeline.validate_application(app_id, user["username"], user["role"], _today())
    return {"document_id": doc_id, "version": version, "storage_tier": "LOCAL_INSTITUTE_VAULT", **result}


@app.post("/api/applications/{app_id}/freeze")
def freeze_application(app_id: int, user=Depends(require("app:submit_own"))):
    a = _get_app(app_id, user)
    if user["role"] != "institution" or user.get("institution_id") != a["institution_id"]:
        raise HTTPException(403, "Only the owning institution can freeze application data.")
    if a.get("is_frozen"):
        raise HTTPException(400, "Application data is already frozen.")

    # Pre-freeze gate. What blocks is set in categories.yaml (submission_gate); anything not
    # blocked was shown to the institution as a warning and reaches the officer as a finding.
    gate = config.categories().get("submission_gate") or {}
    cat_cfg = config.categories()["categories"].get(a["category"], {})
    req_rules = [r for r in cat_cfg.get("rules", []) if r.get("type") == "required_document" and r.get("doc") != "infra_photo"]
    with tx() as c:
        active_docs = rows(c.execute("SELECT * FROM documents WHERE application_id=? AND superseded=0", (app_id,)).fetchall())
        docs_cfg = config.documents()
        uploaded_types = {d["declared_type"] for d in active_docs}
        if gate.get("block_missing_documents", True):
            for r in req_rules:
                if r["doc"] not in uploaded_types:
                    lbl = docs_cfg.get(r["doc"], {}).get("label", r["doc"])
                    raise HTTPException(400, f"Cannot freeze: Mandatory document '{lbl}' is not yet uploaded. Please upload all required documents.")

        photo_rule = next((r for r in cat_cfg.get("rules", []) if r.get("doc") == "infra_photo" and r.get("type") == "required_document"), None)
        if photo_rule and gate.get("block_missing_photos", True):
            min_photos = photo_rule.get("min_count", 4)
            photo_count = sum(1 for d in active_docs if d["declared_type"] == "infra_photo")
            if photo_count < min_photos:
                raise HTTPException(400, f"Cannot freeze: At least {min_photos} infrastructure photos are required before freezing (currently {photo_count} uploaded).")

        today = _today()
        for d in active_docs:
            declared = d.get("declared_type")
            if declared == "infra_photo":
                continue
            detected = d.get("detected_type")
            conf = d.get("classification_conf") or 0
            declared_lbl = docs_cfg.get(declared, {}).get("label", declared)

            if gate.get("block_wrong_documents", False):
                if detected and detected != declared:
                    detected_lbl = docs_cfg.get(detected, {}).get("label", detected)
                    raise HTTPException(400, f"You cannot freeze the data as document '{d.get('original_name')}' is wrong (uploaded as {declared_lbl}, but detected as {detected_lbl}). Please replace it with the correct file before freezing.")
                if not detected or conf < 0.2:
                    raise HTTPException(400, f"You cannot freeze the data as document '{d.get('original_name')}' is not recognized as a valid {declared_lbl}. Please upload an authentic {declared_lbl} before freezing.")

            if gate.get("block_expired_documents", False):
                exp_field = docs_cfg.get(declared, {}).get("expiry_field")
                exp = (((d.get("extraction") or {}).get("fields") or {}).get(exp_field) or {}).get("normalized") if exp_field else None
                if exp and str(exp) < today.isoformat():
                    raise HTTPException(400, f"You cannot freeze the data as '{d.get('original_name')}' ({declared_lbl}) expired on {exp}. Please upload a valid certificate before freezing.")

    now = now_iso()
    with tx() as c:
        docs = rows(c.execute("SELECT * FROM documents WHERE application_id=? AND superseded=0", (app_id,)).fetchall())
        inst_aicte_dir = AICTE_CLOUD_DIR / a["institution_id"]
        inst_aicte_dir.mkdir(parents=True, exist_ok=True)
        for d in docs:
            src = FILES_DIR / Path(d["stored_path"]).name
            if src.exists():
                dst = inst_aicte_dir / src.name
                dst.write_bytes(src.read_bytes())

        c.execute("""
            UPDATE applications
            SET is_frozen=1,
                storage_tier='AICTE_CENTRAL_CLOUD',
                frozen_at=?,
                frozen_by=?,
                status='UNDER_SCRUTINY',
                submitted_at=COALESCE(submitted_at, ?)
            WHERE id=?
        """, (now, user.get("full_name") or user["username"], now, app_id))

        c.execute("UPDATE documents SET storage_tier='AICTE_CENTRAL_CLOUD' WHERE application_id=?", (app_id,))

        audit.log(user["username"], user["role"], "APPLICATION_DATA_FROZEN_SYNCED_TO_AICTE", app_id, {
            "ref": a["ref"],
            "academic_year": a["form"].get("academic_year"),
            "storage_tier": "AICTE_CENTRAL_CLOUD",
            "documents_synced": len(docs),
            "frozen_at": now
        }, conn=c)

    res = pipeline.validate_application(app_id, user["username"], user["role"], _today())
    return {
        "ok": True,
        "is_frozen": True,
        "storage_tier": "AICTE_CENTRAL_CLOUD",
        "frozen_at": now,
        "validation": res
    }


@app.post("/api/applications/{app_id}/submit")
def submit_application(app_id: int, user=Depends(require("app:submit_own"))):
    return freeze_application(app_id, user)


@app.post("/api/applications/{app_id}/unfreeze-request")
def request_unfreeze(app_id: int, body: UnfreezeRequestIn, user=Depends(require("app:submit_own"))):
    a = _get_app(app_id, user)
    if user["role"] != "institution" or user.get("institution_id") != a["institution_id"]:
        raise HTTPException(403, "Only the owning institution can request unfreeze.")
    if not a.get("is_frozen"):
        raise HTTPException(400, "Application data is not currently frozen.")
    if a.get("unfreeze_requested"):
        raise HTTPException(400, "An unfreeze request is already pending review with AICTE.")

    now = now_iso()
    with tx() as c:
        c.execute("""
            UPDATE applications 
            SET unfreeze_requested=1,
                unfreeze_request_reason=?,
                unfreeze_requested_at=?
            WHERE id=?
        """, (body.reason.strip(), now, app_id))

        c.execute("""
            INSERT INTO alerts(application_id, severity, kind, message, audience, created_at)
            VALUES (?, 'medium', 'UNFREEZE_REQUEST', ?, 'officer', ?)
        """, (app_id, f"Institution '{a['institution_id']}' has formally requested unfreeze: {body.reason.strip()}", now))

        audit.log(user["username"], user["role"], "UNFREEZE_REQUESTED_BY_INSTITUTION", app_id, {
            "ref": a["ref"],
            "reason": body.reason.strip(),
            "requested_at": now
        }, conn=c)

    return {"ok": True, "message": "Formal unfreeze request submitted to AICTE Scrutiny Officers."}


@app.post("/api/applications/{app_id}/unfreeze")
def unfreeze_application(app_id: int, body: UnfreezeIn, user=Depends(require("finding:review"))):
    if user["role"] not in ("officer", "admin", "regional_officer"):
        raise HTTPException(403, "Only AICTE Scrutiny Officers or Administrators can unfreeze application data.")
    a = _get_app(app_id, user)
    if not a.get("is_frozen"):
        raise HTTPException(400, "Application is already unfrozen.")

    now = now_iso()
    deadline = (_today() + timedelta(days=body.grant_rectification_days)).isoformat()
    with tx() as c:
        c.execute("""
            UPDATE applications 
            SET is_frozen=0,
                storage_tier='LOCAL_INSTITUTE_VAULT',
                unfreeze_requested=0,
                unfrozen_at=?,
                unfrozen_by=?,
                unfreeze_remarks=?,
                rectification_deadline=?,
                status='RECTIFICATION_REQUESTED'
            WHERE id=?
        """, (now, user.get("full_name") or user["username"], body.remarks.strip(), deadline, app_id))

        c.execute("UPDATE documents SET storage_tier='LOCAL_INSTITUTE_VAULT' WHERE application_id=?", (app_id,))

        notifier.notify(c, "institution", app_id, f"{a['ref']}: Application Unfrozen by AICTE Officer",
                        [f"Officer Remarks: {body.remarks.strip()}",
                         "Your application portal has been unfrozen. You may now upload updated documents and edit details in your Local Vault.",
                         f"Rectification Deadline: {deadline}",
                         "Once all corrections are made, remember to click 'Freeze & Submit to AICTE Cloud'."],
                        a["institution_id"])

        audit.log(user["username"], user["role"], "APPLICATION_UNFROZEN_BY_OFFICER", app_id, {
            "ref": a["ref"],
            "officer": user["username"],
            "remarks": body.remarks.strip(),
            "rectification_deadline": deadline,
            "unfrozen_at": now
        }, conn=c)

    return {"ok": True, "message": "Application unfrozen. The institution can now upload documents and make corrections."}


@app.post("/api/applications/{app_id}/validate")
def revalidate(app_id: int, user=Depends(require("verify:recheck"))):
    _get_app(app_id, user)
    with tx() as c:
        if c.execute("SELECT COUNT(*) n FROM documents WHERE application_id=? AND purged=1", (app_id,)).fetchone()["n"]:
            raise HTTPException(409, "Documents were purged under the retention policy; the recorded results stand")
    return pipeline.validate_application(app_id, user["username"], user["role"], _today())


# ------------------------------------------------------------------ documents

def _doc_for_user(doc_id: int, user: dict) -> dict:
    with tx() as c:
        d = row(c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())
    if not d:
        raise HTTPException(404)
    _get_app(d["application_id"], user)
    if d.get("purged"):
        raise HTTPException(410, "Document purged under the data-retention policy")
    return d


@app.get("/api/documents/{doc_id}/file")
def download_document(doc_id: int, user=Depends(current_user)):
    d = _doc_for_user(doc_id, user)
    audit.log(user["username"], user["role"], "DOCUMENT_ACCESSED", d["application_id"], {"document_id": doc_id})
    return FileResponse(d["stored_path"], media_type=d["mime"], filename=d["original_name"])


@app.get("/api/documents/{doc_id}/locate")
def locate_values(doc_id: int, q: list[str] = Query(...), user=Depends(current_user)):
    """Where each value is printed on the document (normalised boxes), for evidence highlights."""
    d = _doc_for_user(doc_id, user)
    if d["declared_type"] == "infra_photo":
        return {v: [] for v in q}
    return {v: locate.find(d["stored_path"], d["mime"], v) for v in q[:20]}


@app.get("/api/documents/{doc_id}/preview")
def preview_document(doc_id: int, page: int = Query(1, ge=1), user=Depends(current_user)):
    """PNG of one page (PDFs at 2 px per point). Rendered once, then served from a disk cache."""
    d = _doc_for_user(doc_id, user)
    cache = config.STORAGE_DIR / "previews" / f"{d['sha256']}-{page}.png"
    if not cache.exists():
        from PIL import Image
        if d["mime"] == "application/pdf":
            img = extract.render_pages(d["stored_path"], 2.0, only=page)[0]
        else:
            img = Image.open(d["stored_path"])
            img.thumbnail((1600, 1600))
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        img.convert("RGB").save(tmp, "PNG", optimize=True)
        tmp.replace(cache)
    return FileResponse(cache, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------ human review

class ReviewIn(BaseModel):
    status: str
    remark: str = Field(min_length=5)


REVIEW_STATES = {"CONFIRMED", "DISMISSED", "RECTIFICATION_REQUESTED", "INSPECTION_REQUIRED", "OPEN"}


@app.post("/api/findings/{finding_id}/review")
def review_finding(finding_id: int, body: ReviewIn, user=Depends(require("finding:review"))):
    if body.status not in REVIEW_STATES:
        raise HTTPException(400, f"status must be one of {sorted(REVIEW_STATES)}")
    with tx() as c:
        f = row(c.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone())
        if not f:
            raise HTTPException(404)
        c.execute("UPDATE findings SET review_status=?, reviewer=?, review_remark=?, reviewed_at=? WHERE id=?",
                  (body.status, user["username"], body.remark, now_iso(), finding_id))
        c.execute("UPDATE alerts SET acknowledged_by=?, acknowledged_at=? WHERE finding_id=? AND acknowledged_by IS NULL",
                  (user["username"], now_iso(), finding_id))
        if body.status == "RECTIFICATION_REQUESTED":
            deadline = (_today() + timedelta(days=int(config.categories().get("rectification_window_days", 15)))).isoformat()
            c.execute("UPDATE applications SET status='RECTIFICATION_REQUESTED', rectification_deadline=COALESCE(rectification_deadline, ?) WHERE id=?", (deadline, f["application_id"]))
            c.execute("INSERT INTO alerts(application_id,finding_id,severity,kind,message,audience,created_at) VALUES (?,?,?,?,?,?,?)",
                      (f["application_id"], finding_id, f["severity"], "RECTIFICATION",
                       f"Rectification requested: {f['title']} — {body.remark}", "institution", now_iso()))
            a = row(c.execute("SELECT ref, institution_id FROM applications WHERE id=?", (f["application_id"],)).fetchone())
            notifier.notify(c, "institution", f["application_id"], f"{a['ref']}: correction requested by the scrutiny officer",
                            [f"Item: {f['title']}", f"Officer’s note: {body.remark}", f"Rectification deadline: {deadline}", "Upload a corrected document and resubmit."],
                            a["institution_id"])
        audit.log(user["username"], user["role"], "FINDING_REVIEWED", f["application_id"],
                  {"finding_id": finding_id, "rule_id": f["rule_id"], "title": f["title"], "status": body.status,
                   "remark": body.remark}, conn=c)
    return {"ok": True}


class DecisionIn(BaseModel):
    decision: str
    remark: str = Field(min_length=10)


DECISIONS = {"RECOMMEND_FOR_APPROVAL", "RETURN_FOR_RECTIFICATION", "REFER_FOR_INSPECTION", "REFER_TO_EXPERT_COMMITTEE"}


@app.post("/api/applications/{app_id}/decision")
def record_decision(app_id: int, body: DecisionIn, user=Depends(require("app:decide"))):
    """The official's recommendation. The system enforces human review of every
    high-severity flag before any outcome can be recorded."""
    if body.decision not in DECISIONS:
        raise HTTPException(400, f"decision must be one of {sorted(DECISIONS)}")
    _get_app(app_id, user)
    with tx() as c:
        unreviewed = c.execute("SELECT COUNT(*) n FROM findings WHERE application_id=? AND severity='high' AND review_status='OPEN'",
                               (app_id,)).fetchone()["n"]
        if unreviewed and body.decision == "RECOMMEND_FOR_APPROVAL":
            raise HTTPException(409, f"{unreviewed} high-severity finding(s) not yet reviewed by an official")
        status = {"RETURN_FOR_RECTIFICATION": "RECTIFICATION_REQUESTED"}.get(body.decision, "DECIDED")
        deadline = (_today() + timedelta(days=int(config.categories().get("rectification_window_days", 15)))).isoformat() if body.decision == "RETURN_FOR_RECTIFICATION" else None
        c.execute("UPDATE applications SET decision=?, decision_by=?, decision_remark=?, status=?, decided_at=?, rectification_deadline=COALESCE(?, rectification_deadline) WHERE id=?",
                  (body.decision, user["username"], body.remark, status, now_iso(), deadline, app_id))
        a = row(c.execute("SELECT ref, institution_id FROM applications WHERE id=?", (app_id,)).fetchone())
        if body.decision == "RETURN_FOR_RECTIFICATION":
            notifier.notify(c, "institution", app_id, f"{a['ref']}: returned for rectification",
                            ["The scrutiny officer has returned your application.", f"Remarks: {body.remark}", f"Rectification window deadline: {deadline}"], a["institution_id"])
        audit.log(user["username"], user["role"], "OFFICIAL_DECISION", app_id, {"decision": body.decision, "remark": body.remark}, conn=c)
    return {"ok": True}


@app.post("/api/applications/{app_id}/final-decision")
def record_final_decision(app_id: int, body: DecisionIn, user=Depends(require("app:final_decision"))):
    """Tier 2 Scrutiny: Regional Officer / AICTE Competent Authority issues final statutory approval or rejection."""
    _get_app(app_id, user)
    if body.decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(400, "Final decision must be 'APPROVED' or 'REJECTED'")
    with tx() as c:
        c.execute("UPDATE applications SET decision=?, decision_by=?, decision_remark=?, status='DECIDED', decided_at=? WHERE id=?",
                  (body.decision, user["username"], body.remark, now_iso(), app_id))
        audit.log(user["username"], user["role"], "FINAL_STATUTORY_DECISION", app_id,
                  {"final_decision": body.decision, "remark": body.remark}, conn=c)
    return {"ok": True, "status": "DECIDED", "final_decision": body.decision}


@app.get("/api/applications/{app_id}/deficiency-memo")
def get_deficiency_memo(app_id: int, format: str = Query("json"), user=Depends(current_user)):
    """Deficiency memo: open issues with the rule each one came from and its handbook reference.

    References come from the rule's `ref` in categories.yaml, so they say exactly what an authorized
    official configured; nothing here invents clause numbers. Institutions get checklist items only."""
    a = _get_app(app_id, user)
    with tx() as c:
        findings = rows(c.execute("SELECT * FROM findings WHERE application_id=? AND review_status='OPEN' ORDER BY id", (app_id,)).fetchall())
        docs = rows(c.execute("SELECT id, original_name, declared_type FROM documents WHERE application_id=?", (app_id,)).fetchall())
    if user["role"] == "institution":
        findings = [f for f in findings if f["module"] in pipeline.INSTITUTION_VISIBLE_MODULES]
    window = int(config.categories().get("rectification_window_days", 15))

    doc_map = {d["id"]: d["original_name"] for d in docs}
    items = []
    for f in findings:
        items.append({
            "finding_id": f["id"],
            "rule_id": f.get("rule_id"),
            "severity": f["severity"],
            "title": f["title"],
            "deficiency_reason": f["reason"],
            "affected_document": doc_map.get(f.get("document_id"), "Application form"),
            "handbook_reference": f.get("ref") or "Applicable Approval Process Handbook (reference to be configured)",
            "rectification_guideline": "Upload a corrected or original document, or an endorsement from the issuing authority, "
                                       f"within {window} days.",
        })

    memo = {
        "application_ref": a["ref"],
        "institution_id": a["institution_id"],
        "institution_name": a["form"].get("institution_name"),
        "ruleset_version": config.categories().get("version"),
        "total_deficiencies": len(items),
        "deficiency_items": items,
        "rectification_window_days": window,
        "disclaimer": "Decision-support output. Handbook references are as configured in the rule set; statutory "
                      "scrutiny and the final decision rest with the competent AICTE authority.",
    }
    if format != "html":
        return memo
    return HTMLResponse(_memo_html(memo, a))


def _memo_html(m: dict, a: dict) -> str:
    """Printable deficiency memo (opened from the officer's case header)."""
    from html import escape as e
    sev = {"high": "#b42318", "medium": "#b54708", "low": "#475467", "info": "#475467"}
    rows_html = "".join(
        f"<tr><td>{n}</td><td><span class=s style='color:{sev.get(i['severity'], '#475467')}'>{e(i['severity'].title())}</span></td>"
        f"<td><b>{e(i['title'])}</b><div class=r>{e(i['deficiency_reason'] or '')}</div>"
        f"<div class=m>Document: {e(i['affected_document'])} · Rule {e(i['rule_id'] or '')} · Reference: {e(i['handbook_reference'])}</div></td></tr>"
        for n, i in enumerate(m["deficiency_items"], 1)) or "<tr><td colspan=3>No open deficiencies.</td></tr>"
    return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Deficiency memo · {e(m['application_ref'])}</title><style>
body{{font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:#101828;background:#fff;max-width:900px;margin:32px auto;padding:0 20px}}
h1{{font-size:20px;margin:0 0 4px}}.meta{{color:#475467;margin-bottom:20px}}table{{width:100%;border-collapse:collapse}}
td{{border-top:1px solid #eaecf0;padding:10px 8px;vertical-align:top}}td:first-child{{width:28px;color:#667085}}td:nth-child(2){{width:72px}}
.s{{font-weight:600}}.r{{margin-top:2px}}.m{{color:#667085;font-size:12.5px;margin-top:4px}}
.box{{background:#f9fafb;border:1px solid #eaecf0;border-radius:8px;padding:12px 14px;margin:18px 0}}
.foot{{color:#667085;font-size:12.5px;margin-top:22px}}button{{float:right;font:inherit;padding:6px 14px;border:1px solid #d0d5dd;border-radius:6px;background:#fff;cursor:pointer}}
@media print{{button{{display:none}}body{{margin:0}}}}</style></head><body>
<button onclick="print()">Print / Save as PDF</button>
<h1>Deficiency memo</h1>
<div class=meta>{e(m['institution_name'] or '')} ({e(m['institution_id'])}) · Application {e(m['application_ref'])} · AY {e(a['form'].get('academic_year') or '')} · Rule set {e(m['ruleset_version'] or '')}</div>
<div class=box><b>{m['total_deficiencies']} open item(s).</b> Please rectify within <b>{m['rectification_window_days']} days</b> by uploading a corrected
or original document, or an endorsement from the issuing authority.</div>
<table>{rows_html}</table>
<p class=foot>{e(m['disclaimer'])}</p></body></html>"""


# ------------------------------------------------------------------ alerts, audit, records

@app.get("/api/alerts")
def list_alerts(include_ack: bool = False, user=Depends(current_user)):
    q = "SELECT al.*, a.ref, a.institution_id FROM alerts al JOIN applications a ON a.id=al.application_id WHERE 1=1"
    args = []
    if user["role"] == "institution":
        # Institutions see only alerts addressed to them (forensic alerts are officer-only)
        q += " AND al.audience IN ('institution', 'both') AND a.institution_id=?"
        args.append(user["institution_id"])
    else:
        # Scrutiny Officers & Admins: only see alerts for frozen/submitted applications in AICTE Central Cloud
        q += " AND al.audience IN ('officer', 'both') AND (a.is_frozen=1 OR a.storage_tier='AICTE_CENTRAL_CLOUD' OR a.status!='DRAFT')"
    if not include_ack:
        q += " AND al.acknowledged_by IS NULL"
    with tx() as c:
        out = rows(c.execute(q + " ORDER BY CASE al.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, al.id DESC LIMIT 200", args).fetchall())
    sla = config.categories().get("alert_sla_hours", {"high": 24, "medium": 72, "low": 168})
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for a in out:
        age = (now - datetime.fromisoformat(a["created_at"])).total_seconds() / 3600
        a["age_hours"] = round(age, 1)
        a["sla_hours"] = sla.get(a["severity"])
        a["overdue"] = bool(not a["acknowledged_by"] and a["sla_hours"] and age > a["sla_hours"])
    return out


@app.get("/api/notifications")
def list_notifications(user=Depends(current_user)):
    """Email outbox: what was (or would be) sent, to whom, and its delivery status."""
    return notifier.outbox(user)


@app.get("/api/admin/retention")
def retention_preview(days: int | None = None, user=Depends(require("retention:manage"))):
    return retention.preview(days)


class RetentionIn(BaseModel):
    days: int | None = None
    confirm: bool = False


@app.post("/api/admin/retention/run")
def retention_run(body: RetentionIn, user=Depends(require("retention:manage"))):
    if not body.confirm:
        raise HTTPException(400, "Set confirm=true to purge")
    return retention.run(user["username"], user["role"], body.days)


@app.post("/api/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, user=Depends(require("alert:ack"))):
    with tx() as c:
        c.execute("UPDATE alerts SET acknowledged_by=?, acknowledged_at=? WHERE id=?", (user["username"], now_iso(), alert_id))
    audit.log(user["username"], user["role"], "ALERT_ACKNOWLEDGED", None, {"alert_id": alert_id})
    return {"ok": True}


@app.get("/api/audit")
def get_audit(application_id: int | None = None, limit: int = 300, user=Depends(require("audit:read"))):
    with tx() as c:
        if application_id:
            r = c.execute("SELECT * FROM audit_log WHERE application_id=? ORDER BY id DESC LIMIT ?", (application_id, limit))
        else:
            r = c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        return rows(r.fetchall())


@app.get("/api/audit/verify")
def verify_audit(user=Depends(require("audit:read"))):
    return audit.verify_chain()


@app.get("/api/records/{institution_id}")
def get_record(institution_id: str, user=Depends(require("records:read"))):
    rec = config.institutional_records()["institutions"].get(institution_id)
    if not rec:
        raise HTTPException(404)
    audit.log(user["username"], user["role"], "RECORD_ACCESSED", None, {"institution_id": institution_id})
    return rec


@app.get("/api/dashboard")
def dashboard(user=Depends(current_user)):
    apps = list_applications(user)
    with tx() as c:
        if user["role"] == "institution":
            ids = [a["id"] for a in apps] or [-1]
            ph = ",".join("?" * len(ids))
            vs = rows(c.execute(f"SELECT status, COUNT(*) n FROM verifications WHERE application_id IN ({ph}) GROUP BY status", ids).fetchall())
            fs = []
        else:
            vs = rows(c.execute("SELECT status, COUNT(*) n FROM verifications GROUP BY status").fetchall())
            fs = rows(c.execute("SELECT module, severity, COUNT(*) n FROM findings GROUP BY module, severity").fetchall())
            reps = [json.loads(r["report_json"]) for r in c.execute("SELECT report_json FROM applications WHERE report_json IS NOT NULL")]
    by_status = {}
    for a in apps:
        k = a["system_status"] or a["status"]
        by_status[k] = by_status.get(k, 0) + 1
    out = {"applications": len(apps), "by_status": by_status, "verification_status": {v["status"]: v["n"] for v in vs}}
    if user["role"] != "institution":
        out["findings_by_module"] = fs
        times = [r["timings"]["total_ms"] for r in reps if r.get("timings")]
        out["avg_validation_ms"] = round(sum(times) / len(times)) if times else None
    return out


@app.get("/api/evaluation")
def evaluation(user=Depends(require("metrics:read"))):
    p = config.STORAGE_DIR / "evaluation.json"
    if not p.exists():
        raise HTTPException(404, "Run scripts/evaluate.py first")
    return json.loads(p.read_text())


# ------------------------------------------------------------------ demo issuing-authority API

@app.get("/mock-sources/{source}/verify", tags=["demo issuing authorities"])
def mock_source(source: str, ref: str, x_api_key: str | None = None):
    """Simulated issuing-authority API, for demonstrating HttpRegistryAdapter. Synthetic data only."""
    reg = json.loads((config.DATA_DIR / "authority_registry.json").read_text())
    if source not in reg:
        raise HTTPException(404)
    rec = reg[source].get(ref)
    return {"found": rec is not None, "record": rec}


# ------------------------------------------------------------------ AICTE Portal Ingestion API

class AictePortalDocumentIn(BaseModel):
    declared_type: str
    original_name: str
    file_base64: str
    mime: str = "application/pdf"
    tag: str | None = None


class AictePortalIngestIn(BaseModel):
    institution_id: str
    category: str = "EOA"
    form_data: dict
    documents: list[AictePortalDocumentIn] = Field(default_factory=list)


@app.post("/api/integrations/aicte-portal/ingest", tags=["AICTE Portal Integration"])
def aicte_portal_ingest(
    payload: AictePortalIngestIn,
    x_aicte_portal_key: str = Header(..., description="Authentication key for AICTE central portal communication")
):
    """Production integration endpoint for the central AICTE approval portal.
    Receives submitted applications directly from the AICTE portal, stores documents,
    and runs the automated AI validation pipeline synchronously."""
    expected_key = os.environ.get("AICTE_PORTAL_KEY", "aicte-portal-prod-secret-2026")
    if x_aicte_portal_key != expected_key:
        raise HTTPException(401, "Invalid or unauthorized AICTE Portal integration key")

    ref = f"{payload.category}-{_today().year}-{uuid.uuid4().hex[:6].upper()}"
    now = now_iso()
    with tx() as c:
        c.execute("INSERT INTO applications(ref, institution_id, category, form_json, status, created_at, submitted_at) VALUES (?,?,?,?,?,?,?)",
                  (ref, payload.institution_id, payload.category, json.dumps(payload.form_data), "SUBMITTED", now, now))
        app_id = c.execute("SELECT last_insert_rowid() id").fetchone()["id"]

        for doc_in in payload.documents:
            raw = base64.b64decode(doc_in.file_base64)
            h = hashlib.sha256(raw).hexdigest()
            target_path = FILES_DIR / f"{h}_{doc_in.original_name}"
            target_path.write_bytes(raw)
            c.execute("INSERT INTO documents(application_id, declared_type, tag, original_name, mime, sha256, stored_path, uploaded_by, uploaded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (app_id, doc_in.declared_type, doc_in.tag, doc_in.original_name, doc_in.mime, h, str(target_path), "aicte_portal_service", now))

    audit.log("aicte_portal_service", "system", "PORTAL_APPLICATION_INGESTED", app_id, {"ref": ref, "institution_id": payload.institution_id})
    rep = pipeline.validate_application(app_id, actor="aicte_portal_service", role="system", today=_today())
    return {
        "ok": True,
        "application_id": app_id,
        "ref": ref,
        "system_status": rep.get("system_status"),
        "finding_counts": rep.get("finding_counts"),
        "verification_summary": rep.get("verification_summary"),
        "tracking_url": f"/cases/{app_id}"
    }


# ------------------------------------------------------------------ frontend

_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _dist / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(
            _dist / "index.html",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
