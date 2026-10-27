"""Append-only, hash-chained audit trail.

Every entry stores the hash of the previous entry, so any later edit or
deletion of a row breaks the chain and is detected by verify_chain().
"""
from __future__ import annotations

import hashlib
import json

from .db import now_iso, tx

GENESIS = "0" * 64


def _digest(prev: str, ts: str, actor: str, role: str, action: str, app_id, detail: str, ip: str = "127.0.0.1") -> str:
    payload = "|".join([prev, ts, actor, role, action, str(app_id or ""), detail, ip])
    return hashlib.sha256(payload.encode()).hexdigest()


def log(actor: str, role: str, action: str, application_id=None, detail: dict | None = None, conn=None, actor_ip: str = "127.0.0.1") -> None:
    detail_s = json.dumps(detail or {}, sort_keys=True, default=str)

    def _write(c):
        last = c.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else GENESIS
        ts = now_iso()
        h = _digest(prev, ts, actor, role, action, application_id, detail_s, actor_ip)
        cols = {col["name"] for col in c.execute("PRAGMA table_info(audit_log)")}
        if "actor_ip" in cols:
            c.execute(
                "INSERT INTO audit_log(ts,actor,role,action,application_id,detail_json,prev_hash,hash,actor_ip)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (ts, actor, role, action, application_id, detail_s, prev, h, actor_ip),
            )
        else:
            c.execute(
                "INSERT INTO audit_log(ts,actor,role,action,application_id,detail_json,prev_hash,hash)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (ts, actor, role, action, application_id, detail_s, prev, h),
            )

    if conn is not None:
        _write(conn)
    else:
        with tx() as c:
            _write(c)


def verify_chain() -> dict:
    with tx() as c:
        entries = c.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
    prev = GENESIS
    for e in entries:
        ip = e["actor_ip"] if "actor_ip" in e.keys() and e["actor_ip"] else "127.0.0.1"
        expected = _digest(prev, e["ts"], e["actor"], e["role"], e["action"], e["application_id"], e["detail_json"], ip)
        if e["prev_hash"] != prev or e["hash"] != expected:
            # Check backwards compatibility without IP
            legacy_expected = hashlib.sha256("|".join([prev, e["ts"], e["actor"], e["role"], e["action"], str(e["application_id"] or ""), e["detail_json"]]).encode()).hexdigest()
            if e["hash"] != legacy_expected:
                return {"intact": False, "broken_at_id": e["id"], "entries": len(entries)}
        prev = e["hash"]
    return {"intact": True, "entries": len(entries), "head": prev}
