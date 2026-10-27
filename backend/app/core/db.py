"""SQLite persistence. Swap for PostgreSQL in production (same schema)."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH, STORAGE_DIR

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT,
    pw_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('institution','officer','admin')),
    institution_id TEXT,
    email TEXT
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    ref TEXT UNIQUE NOT NULL,
    institution_id TEXT NOT NULL,
    category TEXT NOT NULL,
    form_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    system_status TEXT,
    report_json TEXT,
    submitted_at TEXT,
    validated_at TEXT,
    decision TEXT,
    decision_by TEXT,
    decision_remark TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    declared_type TEXT NOT NULL,
    detected_type TEXT,
    classification_conf REAL,
    tag TEXT,
    original_name TEXT NOT NULL,
    mime TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    dhash TEXT,
    stored_path TEXT NOT NULL,
    extraction_json TEXT,
    text TEXT,
    ocr_used INTEGER DEFAULT 0,
    version INTEGER DEFAULT 1,
    superseded INTEGER DEFAULT 0,
    purged INTEGER DEFAULT 0,
    uploaded_by TEXT,
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    document_id INTEGER,
    module TEXT NOT NULL,
    rule_id TEXT,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT,
    ref TEXT,
    review_status TEXT NOT NULL DEFAULT 'OPEN',
    reviewer TEXT,
    review_remark TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    document_id INTEGER,
    source TEXT,
    method TEXT,
    status TEXT NOT NULL,
    comparison_json TEXT,
    response_json TEXT,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL,
    finding_id INTEGER,
    severity TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    audience TEXT NOT NULL,
    created_at TEXT NOT NULL,
    acknowledged_by TEXT,
    acknowledged_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    application_id INTEGER,
    detail_json TEXT,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verification_jobs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    reference TEXT NOT NULL,
    polls INTEGER DEFAULT 0,
    UNIQUE(source, reference)
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    application_id INTEGER,
    recipient TEXT NOT NULL,
    email TEXT,
    subject TEXT NOT NULL,
    body TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_app ON documents(application_id);
CREATE INDEX IF NOT EXISTS idx_docs_sha ON documents(sha256);
CREATE INDEX IF NOT EXISTS idx_find_app ON findings(application_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def tx():
    with _lock:
        conn = connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


MIGRATIONS = [
    ("users", "email", "TEXT"),
    ("applications", "decided_at", "TEXT"),
    ("documents", "purged", "INTEGER DEFAULT 0"),
    ("applications", "rectification_deadline", "TEXT"),
    ("applications", "risk_score", "REAL DEFAULT 0.0"),
    ("applications", "inspection_recommendation", "TEXT DEFAULT 'VIRTUAL_SCRUTINY_ELIGIBLE'"),
    ("applications", "second_tier_status", "TEXT"),
    ("applications", "second_tier_reviewer", "TEXT"),
    ("applications", "second_tier_remark", "TEXT"),
    ("documents", "phash", "TEXT"),
    ("documents", "encryption_status", "TEXT DEFAULT 'AES256'"),
    ("audit_log", "actor_ip", "TEXT DEFAULT '127.0.0.1'"),
    # data freeze / sync to AICTE central storage, and the unfreeze-request workflow
    ("applications", "is_frozen", "INTEGER DEFAULT 0"),
    ("applications", "storage_tier", "TEXT DEFAULT 'LOCAL_INSTITUTE_VAULT'"),
    ("applications", "frozen_at", "TEXT"),
    ("applications", "frozen_by", "TEXT"),
    ("applications", "unfreeze_requested", "INTEGER DEFAULT 0"),
    ("applications", "unfreeze_request_reason", "TEXT"),
    ("applications", "unfreeze_requested_at", "TEXT"),
    ("applications", "unfrozen_at", "TEXT"),
    ("applications", "unfrozen_by", "TEXT"),
    ("applications", "unfreeze_remarks", "TEXT"),
    ("documents", "storage_tier", "TEXT DEFAULT 'LOCAL_INSTITUTE_VAULT'"),
]


def init_db() -> None:
    with tx() as c:
        c.executescript(SCHEMA)
        for table, col, decl in MIGRATIONS:   # upgrade databases created by earlier versions
            if col not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def file_path(stored: str) -> str:
    """Uploaded files live in <storage>/files/<sha256>.<ext>. Only the file name is trusted, so the
    project keeps working after it is moved, unzipped elsewhere or copied between Windows and Linux."""
    return str(STORAGE_DIR / "files" / re.split(r"[\\/]", stored)[-1])


def row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    if d.get("stored_path"):
        d["stored_path"] = file_path(d["stored_path"])
    for k in list(d):
        if k.endswith("_json") and d[k]:
            d[k[:-5]] = json.loads(d.pop(k))
        elif k.endswith("_json"):
            d[k[:-5]] = None
            d.pop(k)
    return d


def rows(rs) -> list[dict]:
    return [row(r) for r in rs]
