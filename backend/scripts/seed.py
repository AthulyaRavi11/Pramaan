"""Reset the database and load the synthetic applications through the real API.

    python scripts/seed.py              # 3 demo applications
    python scripts/seed.py --with-eval  # + the random evaluation batch

Demo logins (password for all: demo1234):
    officer      scrutiny officer
    admin        administrator
    coromandel   institution (clean application)
    sahyadri     institution (deficiencies)
    gangavalley  institution (suspected manipulation)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PRAMAAN_TODAY", "2026-10-21")
PASSWORD = "demo1234"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-eval", action="store_true")
    args = ap.parse_args()

    from app.core import config
    shutil.rmtree(config.STORAGE_DIR, ignore_errors=True)
    config.STORAGE_DIR.mkdir(parents=True)

    from fastapi.testclient import TestClient
    from app.core.db import init_db, tx
    from app.core.security import hash_password
    import app.main as api
    from app.pipeline import run as pipeline
    from app.main import app

    # Seeding logs in through the real API, in-process. The login CAPTCHA and the per-IP rate
    # limits are meant for people at a browser, so they are switched off for this process only;
    # the running server still enforces both.
    api.verify_captcha = lambda *a, **k: (True, "")
    api.security_guard.is_rate_limited = lambda *a, **k: False

    init_db()
    demo = json.loads((config.DATA_DIR / "demo_manifest.json").read_text())
    batch = json.loads((config.DATA_DIR / "eval_manifest.json").read_text()) if args.with_eval else []

    with tx() as c:
        c.execute("INSERT INTO users(username,full_name,pw_hash,role,email) VALUES (?,?,?,?,?)",
                  ("officer", "R. Meenakshi (Scrutiny Officer)", hash_password(PASSWORD), "officer", "scrutiny.officer@example.org"))
        c.execute("INSERT INTO users(username,full_name,pw_hash,role,email) VALUES (?,?,?,?,?)",
                  ("admin", "Platform Administrator", hash_password(PASSWORD), "admin", "platform.admin@example.org"))
        for m in demo + batch:
            c.execute("INSERT INTO users(username,full_name,pw_hash,role,institution_id,email) VALUES (?,?,?,?,?,?)",
                      (m["user"], m["form"]["institution_name"], hash_password(PASSWORD), "institution", m["institution_id"],
                       f"principal@{m['user']}.example.org"))

    results = []
    with TestClient(app) as client:
        for m in demo + batch:
            tok = client.post("/api/auth/login", json={"username": m["user"], "password": PASSWORD}).json()["token"]
            h = {"Authorization": f"Bearer {tok}"}
            r = client.post("/api/applications", json={"category": m["category"], **m["form"]}, headers=h)
            r.raise_for_status()
            app_id = r.json()["id"]
            for d in m["documents"]:
                p = ROOT / m["dir"] / d["file"]
                mime = "application/pdf" if p.suffix == ".pdf" else "image/jpeg"
                data = {"declared_type": d["declared_type"]}
                if d.get("tag"):
                    data["tag"] = d["tag"]
                up = client.post(f"/api/applications/{app_id}/documents", data=data,
                                 files={"file": (d["file"], p.read_bytes(), mime)}, headers=h)
                up.raise_for_status()
            rep = client.post(f"/api/applications/{app_id}/submit", headers=h)
            blocked = None
            if rep.status_code == 400 and m not in demo:
                # The submission gate (categories.yaml) stopped an incomplete evaluation application. It stays
                # a draft, which officers cannot open, so run the same validation pipeline directly; the
                # evaluation then still measures what would have been found.
                blocked = rep.json()["detail"]
                rep = pipeline.validate_application(app_id, "seed-evaluation", "system", api._today())
            else:
                rep.raise_for_status()
                rep = rep.json()
                rep = rep.get("validation", rep)      # submit (freeze) wraps the validation result
            results.append({"app_id": app_id, "institution_id": m["institution_id"], "faults": m["faults"],
                            **({"blocked_at_submission": blocked} if blocked else {})})
            if m in demo:
                print(f"  {m['form']['institution_name']:40} -> {rep['system_status']:22} "
                      f"findings={rep['finding_counts']}  {rep['timings']['total_ms']} ms")
        if batch:
            print(f"  + {len(batch)} evaluation applications loaded")
    (config.STORAGE_DIR / "seed_results.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
