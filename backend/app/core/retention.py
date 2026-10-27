"""Data-retention policy.

Applications whose recommendation was recorded more than PRAMAAN_RETENTION_DAYS ago
have their uploaded files and extracted text purged. What remains is the decision
record: findings, verification outcomes, reviews and the audit trail — enough to
explain the decision, without keeping institutional or personal documents longer
than needed. Every purge is written to the audit trail.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from . import audit, config
from .db import file_path, now_iso, tx


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()


def preview(days: int | None = None) -> dict:
    days = config.RETENTION_DAYS if days is None else days
    cut = _cutoff(days)
    with tx() as c:
        apps = [dict(r) for r in c.execute(
            "SELECT a.id, a.ref, a.institution_id, a.decision, a.decided_at, COUNT(d.id) docs "
            "FROM applications a LEFT JOIN documents d ON d.application_id=a.id AND d.purged=0 "
            "WHERE a.status='DECIDED' AND a.decided_at IS NOT NULL AND a.decided_at <= ? GROUP BY a.id", (cut,)).fetchall()]
        files = c.execute("SELECT COUNT(*) n FROM documents WHERE purged=0").fetchone()["n"]
        purged = c.execute("SELECT COUNT(*) n FROM documents WHERE purged=1").fetchone()["n"]
    return {"retention_days": days, "cutoff": cut, "eligible": apps, "documents_held": files, "documents_purged": purged,
            "kept_after_purge": ["findings and evidence summaries", "verification outcomes", "reviews and recommendation", "audit trail"]}


def run(actor: str, role: str, days: int | None = None) -> dict:
    p = preview(days)
    removed_files, docs = 0, 0
    with tx() as c:
        for a in p["eligible"]:
            rows = c.execute("SELECT id, stored_path, sha256 FROM documents WHERE application_id=? AND purged=0", (a["id"],)).fetchall()
            for d in rows:
                still_used = c.execute("SELECT COUNT(*) n FROM documents WHERE sha256=? AND purged=0 AND application_id!=?",
                                       (d["sha256"], a["id"])).fetchone()["n"]
                path = file_path(d["stored_path"])
                if not still_used and os.path.exists(path):
                    os.remove(path)
                    removed_files += 1
                for prev in (config.STORAGE_DIR / "previews").glob(f"{d['sha256']}-*.png"):
                    prev.unlink(missing_ok=True)
                c.execute("UPDATE documents SET purged=1, text=NULL, extraction_json=NULL WHERE id=?", (d["id"],))
                docs += 1
            audit.log(actor, role, "RETENTION_PURGE", a["id"], {"ref": a["ref"], "documents": len(rows), "policy_days": p["retention_days"],
                                                                "decided_at": a["decided_at"], "at": now_iso()}, conn=c)
    return {**p, "purged_applications": len(p["eligible"]), "purged_documents": docs, "deleted_files": removed_files}
