"""Verification through original issuing authorities.

Adapters:
  MockRegistryAdapter  - synthetic registry for the demo (data/authority_registry.json)
  HttpRegistryAdapter  - template for a real, authorized API (base_url + key from env)
  InternalAdapter      - AICTE's own authorized records (payments)
Plus offline methods that need no network:
  QR + Ed25519 signature check against the authority's public key (trust store)
  PDF digital signature (PAdES): integrity, signer chain to a trusted root, and edits after signing
  Digital repository: the issuer's own copy of the file (DigiLocker-style), compared by SHA-256

Statuses: VERIFIED, MISMATCH, EXPIRED, PENDING, SOURCE_UNAVAILABLE, MANUAL_REVIEW
"""
from __future__ import annotations

import base64
import json
import os
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..core import config
from ..core.db import now_iso, tx
from .extract import normalize_name, parse_date

STATUS_ORDER = ["MISMATCH", "EXPIRED", "VERIFIED", "PENDING", "SOURCE_UNAVAILABLE", "MANUAL_REVIEW"]


class SourceUnavailable(Exception):
    pass


# ------------------------------------------------------------------ adapters

class MockRegistryAdapter:
    def __init__(self, source_id: str, spec: dict):
        self.source_id, self.spec = source_id, spec

    def lookup(self, reference: str) -> dict:
        mode = self.spec.get("simulate", "available")
        if mode == "unavailable":
            raise SourceUnavailable(f"{self.spec['label']} did not respond (simulated outage)")
        if mode == "async":
            with tx() as c:
                c.execute("INSERT OR IGNORE INTO verification_jobs(source,reference) VALUES (?,?)", (self.source_id, reference))
                c.execute("UPDATE verification_jobs SET polls=polls+1 WHERE source=? AND reference=?", (self.source_id, reference))
                polls = c.execute("SELECT polls FROM verification_jobs WHERE source=? AND reference=?",
                                  (self.source_id, reference)).fetchone()["polls"]
            if polls < 2:
                return {"pending": True, "message": "Request accepted by authority; response awaited"}
        reg = json.loads((config.DATA_DIR / "authority_registry.json").read_text())
        return {"found": reference in reg.get(self.source_id, {}), "record": reg.get(self.source_id, {}).get(reference)}


class HttpRegistryAdapter:
    """For a real integration once access is formally authorized. Not used in the demo."""
    def __init__(self, source_id: str, spec: dict):
        self.spec = spec
        self.key = os.environ.get(spec.get("credential_env", ""), "")

    def lookup(self, reference: str) -> dict:
        import httpx
        if not self.key:
            raise SourceUnavailable("No authorized credential configured")
        try:
            r = httpx.get(self.spec["base_url"], params={"ref": reference},
                          headers={"Authorization": f"Bearer {self.key}"}, timeout=10)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            raise SourceUnavailable(str(e))


class InternalAdapter:
    def __init__(self, source_id: str, spec: dict):
        self.spec = spec

    def lookup(self, reference: str) -> dict:
        txns = config.institutional_records().get("payment_transactions", {})
        return {"found": reference in txns, "record": txns.get(reference)}


class DigiLockerAdapter(MockRegistryAdapter):
    """DigiLocker / National Academic Depository. Uses the authorized API when DIGILOCKER_API_KEY and a
    base_url are configured; otherwise reads the synthetic demo registry (authority_registry.json)."""
    def lookup(self, reference: str) -> dict:
        if os.environ.get("DIGILOCKER_API_KEY") and self.spec.get("base_url"):
            return HttpRegistryAdapter(self.source_id, {**self.spec, "credential_env": "DIGILOCKER_API_KEY"}).lookup(reference)
        return super().lookup(reference)


class LandRecordsAdapter(MockRegistryAdapter):
    """State land records / urban local body cadastre. Uses the authorized API when LAND_RECORDS_API_KEY and
    a base_url are configured; otherwise reads the synthetic demo registry (authority_registry.json)."""
    def lookup(self, reference: str) -> dict:
        if os.environ.get("LAND_RECORDS_API_KEY") and self.spec.get("base_url"):
            return HttpRegistryAdapter(self.source_id, {**self.spec, "credential_env": "LAND_RECORDS_API_KEY"}).lookup(reference)
        return super().lookup(reference)


ADAPTERS = {
    "mock": MockRegistryAdapter,
    "http": HttpRegistryAdapter,
    "internal": InternalAdapter,
    "digilocker": DigiLockerAdapter,
    "land_records": LandRecordsAdapter,
}


# ------------------------------------------------------------------ QR + signature

_wechat = None


def decode_qr(images) -> list[str]:
    """WeChat's CNN-free QR detector (OpenCV contrib) is far more robust on dense,
    print-sized codes; the standard detector is the fallback."""
    global _wechat
    if _wechat is None and hasattr(cv2, "wechat_qrcode_WeChatQRCode"):
        _wechat = cv2.wechat_qrcode_WeChatQRCode()
    std = cv2.QRCodeDetector()
    found = []
    for img in images:
        arr = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        if _wechat is not None:
            res, _ = _wechat.detectAndDecode(arr)
            if res:
                found.extend(r for r in res if r)
                continue
        txt, _, _ = std.detectAndDecode(arr)
        if txt:
            found.append(txt)
    return found


def canonical(payload: dict) -> bytes:
    return json.dumps({k: payload[k] for k in ("src", "ref", "fields")}, sort_keys=True, separators=(",", ":")).encode()


def verify_signed_qr(text: str) -> tuple[dict | None, str]:
    try:
        p = json.loads(text)
        key_path = config.DATA_DIR / "trust_store" / f"{p['src']}.pub"
        if not key_path.exists():
            return p, "UNTRUSTED_ISSUER"
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_path.read_text().strip()))
        pub.verify(base64.b64decode(p["sig"]), canonical(p))
        return p, "VALID"
    except InvalidSignature:
        return p, "BAD_SIGNATURE"
    except Exception:
        return None, "UNREADABLE"



# ------------------------------------------------------------------ PDF digital signature (PAdES)

def _trust_roots():
    from asn1crypto import pem, x509 as ax
    roots = []
    for p in (config.DATA_DIR / "trust_store").glob("*.pem"):
        for _, _, der in pem.unarmor(p.read_bytes(), multiple=True):
            roots.append(ax.Certificate.load(der))
    return roots


def check_pdf_signature(path: str) -> dict:
    """Validates the first embedded signature. Returns {status, ...detail}."""
    import logging
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
    except ImportError:
        return {"status": "MANUAL_REVIEW", "message": "Signature validation library (pyHanko) not installed — run the installer again"}
    logging.getLogger("pyhanko").setLevel(logging.CRITICAL)
    try:
        with open(path, "rb") as f:
            sigs = PdfFileReader(f, strict=False).embedded_signatures
            if not sigs:
                return {"status": "MANUAL_REVIEW", "message": "The document carries no digital signature"}
            st = validate_pdf_signature(sigs[0], ValidationContext(trust_roots=_trust_roots(), allow_fetching=False))
            detail = {"signer": st.signing_cert.subject.native.get("common_name"), "signed_at": str(st.signer_reported_dt or ""),
                      "intact": st.intact, "valid": st.valid, "trusted": st.trusted, "coverage": st.coverage.name,
                      "changes_after_signing": st.modification_level.name if st.modification_level else None}
    except Exception as e:  # unreadable or malformed signature dictionary
        return {"status": "MANUAL_REVIEW", "message": f"Signature could not be read: {e.__class__.__name__}"}
    if not (st.intact and st.valid):
        return {**detail, "status": "MISMATCH", "message": "Signature does not match the document's content"}
    if not st.trusted:
        return {**detail, "status": "MISMATCH", "message": "Signed with a certificate that does not chain to a trusted authority"}
    if st.coverage.name != "ENTIRE_FILE":
        return {**detail, "status": "MISMATCH", "message": "The document was changed after it was digitally signed"}
    return {**detail, "status": "VERIFIED", "message": "Signature valid, signer trusted, no changes after signing"}


# ------------------------------------------------------------------ digital repository (issuer's copy)

def check_repository(source_id: str, spec: dict, reference: str | None, sha256: str) -> dict:
    if spec.get("adapter") == "mock" and spec.get("simulate") == "unavailable":
        return {"status": "SOURCE_UNAVAILABLE", "message": "Repository did not respond (simulated outage)"}
    if not reference:
        return {"status": "MANUAL_REVIEW", "message": "No reference number to fetch the issued copy"}
    reg = json.loads((config.DATA_DIR / "authority_registry.json").read_text())
    rec = reg.get(source_id, {}).get(reference)
    issued = ([rec["file_sha256"]] if rec and rec.get("file_sha256") else []) + list((rec or {}).get("valid_sha256s", []))
    if not issued:
        return {"status": "MANUAL_REVIEW", "message": f"No issued copy of {reference} in the repository"}
    if sha256 in issued:
        return {"status": "VERIFIED", "message": "Byte-for-byte identical to the copy issued into the repository", "issued_sha256": sha256[:16]}
    return {"status": "MISMATCH", "message": "The uploaded file differs from the copy the issuer deposited in the repository",
            "issued_sha256": issued[0][:16], "uploaded_sha256": sha256[:16]}


# ------------------------------------------------------------------ comparison

def _cmp(field: str, doc_val, src_val) -> bool:
    if doc_val is None or src_val is None:
        return False
    if field == "institution_name":
        return SequenceMatcher(None, normalize_name(str(doc_val)), normalize_name(str(src_val))).ratio() >= 0.88
    if field in ("valid_until", "issue_date"):
        d1 = date.fromisoformat(doc_val) if isinstance(doc_val, str) and "-" in doc_val[:5] else parse_date(str(doc_val))
        d2 = date.fromisoformat(src_val) if isinstance(src_val, str) and len(src_val) == 10 and src_val[4] == "-" else parse_date(str(src_val))
        return d1 == d2
    return str(doc_val).strip().upper() == str(src_val).strip().upper()


def compare(fields: dict, src_fields: dict, compare_fields: list[str]) -> list[dict]:
    rows = []
    for f in compare_fields:
        dv = (fields.get(f) or {}).get("normalized")
        sv = src_fields.get(f)
        if sv is None:
            continue
        rows.append({"field": f, "document": (fields.get(f) or {}).get("value"), "source": sv, "match": _cmp(f, dv, sv)})
    return rows


def _expired(src_fields: dict, today: date) -> bool:
    if str(src_fields.get("status", "")).upper() in ("EXPIRED", "REVOKED", "CANCELLED"):
        return True
    vu = src_fields.get("valid_until")
    return bool(vu) and date.fromisoformat(vu) < today


# ------------------------------------------------------------------ main entry

def verify_document(doc: dict, read_images, today: date) -> list[dict]:
    """Returns one verification record per method tried."""
    spec_doc = config.documents().get(doc["declared_type"], {})
    source_id = spec_doc.get("source")
    fields = (doc.get("extraction") or {}).get("fields") or {}
    results = []
    if not source_id:
        return results
    src = config.sources().get(source_id, {})
    ref_field = spec_doc.get("reference_field") or "certificate_no"
    reference = (fields.get(ref_field) or {}).get("normalized")

    # 1) Signed QR (offline, cryptographic)
    if "qr_signed" in src.get("methods", []):
        qrs = decode_qr(read_images) if read_images else []
        if not qrs:
            results.append({"source": source_id, "method": "qr_signed", "status": "MANUAL_REVIEW",
                            "comparison": [], "response": {"message": "No QR code found on document"}})
        for q in qrs[:1]:
            payload, sig = verify_signed_qr(q)
            if sig != "VALID":
                results.append({"source": source_id, "method": "qr_signed",
                                "status": "MISMATCH" if sig == "BAD_SIGNATURE" else "MANUAL_REVIEW",
                                "comparison": [], "response": {"signature": sig}})
                continue
            cmp_rows = compare(fields, payload["fields"], src.get("compare_fields", []))
            status = "MISMATCH" if any(not r["match"] for r in cmp_rows) else \
                "EXPIRED" if _expired(payload["fields"], today) else "VERIFIED"
            results.append({"source": source_id, "method": "qr_signed", "status": status, "comparison": cmp_rows,
                            "response": {"signature": "VALID (Ed25519, issuer key in trust store)", "qr_payload": payload["fields"],
                                         "reference": payload["ref"]}})

    # 2) Registry / API lookup
    if "api" in src.get("methods", []):
        adapter_cls = ADAPTERS.get(src.get("adapter"))
        if adapter_cls is None:
            results.append({"source": source_id, "method": "api", "status": "MANUAL_REVIEW", "comparison": [],
                            "response": {"message": "No authorized automated source configured"}})
        elif not reference:
            results.append({"source": source_id, "method": "api", "status": "MANUAL_REVIEW", "comparison": [],
                            "response": {"message": f"Reference number ({ref_field}) not readable from document"}})
        else:
            try:
                resp = adapter_cls(source_id, src).lookup(reference)
                if resp.get("pending"):
                    results.append({"source": source_id, "method": "api", "status": "PENDING", "comparison": [],
                                    "response": resp})
                elif not resp.get("found"):
                    results.append({"source": source_id, "method": "api", "status": "MISMATCH", "comparison": [],
                                    "response": {"message": f"Reference {reference} not found at issuing authority"}})
                else:
                    rec = resp["record"]
                    cmp_rows = compare(fields, rec, src.get("compare_fields", []))
                    status = "MISMATCH" if any(not r["match"] for r in cmp_rows) else \
                        "EXPIRED" if _expired(rec, today) else "VERIFIED"
                    results.append({"source": source_id, "method": "api", "status": status, "comparison": cmp_rows,
                                    "response": {"record": rec, "reference": reference}})
            except SourceUnavailable as e:
                results.append({"source": source_id, "method": "api", "status": "SOURCE_UNAVAILABLE", "comparison": [],
                                "response": {"message": str(e), "routed_to": "manual confirmation"}})
    # 3) PDF digital signature
    if "pdf_signature" in src.get("methods", []) and doc.get("mime") == "application/pdf":
        r = check_pdf_signature(doc["stored_path"])
        results.append({"source": source_id, "method": "pdf_signature", "status": r["status"], "comparison": [],
                        "response": {k: v for k, v in r.items() if k != "status"}})

    # 4) Issuer's copy in a digital repository
    if "repository" in src.get("methods", []):
        r = check_repository(source_id, src, reference, doc.get("sha256", ""))
        results.append({"source": source_id, "method": "repository", "status": r["status"], "comparison": [],
                        "response": {k: v for k, v in r.items() if k != "status"}})

    if src.get("adapter") == "none":
        results.append({"source": source_id, "method": "manual", "status": "MANUAL_REVIEW", "comparison": [],
                        "response": {"message": f"{src.get('label')}: no automated source; confirm with issuing authority"}})

    for r in results:
        r["checked_at"] = now_iso()
        r["source_label"] = src.get("label", source_id)
    return results


def overall_status(results: list[dict]) -> str:
    sts = {r["status"] for r in results}
    for s in STATUS_ORDER:
        if s in sts:
            return s
    return "NOT_APPLICABLE"


def findings_from_verification(doc: dict, results: list[dict]) -> list[dict]:
    out = []
    label = config.documents()[doc["declared_type"]]["label"]
    has_verified = any(r["status"] == "VERIFIED" for r in results)
    for r in results:
        # If an authoritative source (e.g. API lookup) already fully VERIFIED the record,
        # don't trigger redundant MANUAL_REVIEW advisories for missing secondary QR codes.
        if has_verified and r["status"] == "MANUAL_REVIEW":
            continue
        base = {"module": "verification", "document_id": doc["id"], "ref": r["source_label"],
                "evidence": {"document": doc["original_name"], "source": r["source_label"], "method": r["method"],
                             "comparison": r["comparison"], "response": r["response"], "checked_at": r["checked_at"]}}
        if r["status"] == "MISMATCH":
            bad = [c["field"] for c in r["comparison"] if not c["match"]]
            reason = (f"Issuing-authority data differs on: {', '.join(f.replace('_', ' ') for f in bad)}." if bad else
                      r["response"].get("message") or f"Signature check: {r['response'].get('signature')}.")
            title = ("Printed details differ from the authority’s signed QR code" if r["method"] == "qr_signed" and bad else
                     "QR code signature is not valid" if r["method"] == "qr_signed" else
                     "Digital signature check failed" if r["method"] == "pdf_signature" else
                     "File differs from the issuer’s copy in the repository" if r["method"] == "repository" else
                     "Differs from the issuing authority’s record" if bad else "Not found at the issuing authority")
            rid = {"pdf_signature": "VER-SIGNATURE", "repository": "VER-REPOSITORY"}.get(r["method"], "VER-MISMATCH")
            out.append(dict(base, rule_id=rid, severity="high", title=f"{label}: {title}", reason=reason))
        elif r["status"] == "EXPIRED":
            out.append(dict(base, rule_id="VER-EXPIRED", severity="medium",
                            title=f"{label}: expired according to the issuing authority" + (" (signed QR)" if r["method"] == "qr_signed" else ""),
                            reason="The authority's record shows this document is no longer valid."))
        elif r["status"] == "SOURCE_UNAVAILABLE":
            out.append(dict(base, rule_id="VER-UNAVAILABLE", severity="low", title=f"{label}: issuing authority unavailable — confirm manually",
                            reason=r["response"].get("message", "")))
        elif r["status"] == "MANUAL_REVIEW":
            out.append(dict(base, rule_id="VER-MANUAL", severity="low", title=f"{label}: confirm with the issuing authority manually",
                            reason=r["response"].get("message", "Automated verification was inconclusive.")))
        elif r["status"] == "PENDING":
            out.append(dict(base, rule_id="VER-PENDING", severity="info", title=f"{label}: waiting for the issuing authority",
                            reason="Awaiting response from issuing authority. Re-check later."))
    return out
