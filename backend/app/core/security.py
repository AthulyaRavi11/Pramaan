"""Authentication (JWT) and role-based access control, encryption at rest, and PII masking."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import random
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import JWT_SECRET, JWT_TTL_MIN
from .db import row, tx

_bearer = HTTPBearer(auto_error=False)

# Enterprise role aliases
ROLE_ALIASES = {
    "INSTITUTION_USER": "institution",
    "SCRUTINY_OFFICER": "officer",
    "AICTE_ADMIN": "admin",
    "REGIONAL_OFFICER": "regional_officer",
    "AUDITOR": "auditor",
}

# Role permissions
PERMISSIONS = {
    "institution": {"app:create", "app:read_own", "doc:upload_own", "app:submit_own"},
    "officer": {"app:read_all", "finding:review", "app:decide", "verify:recheck", "alert:ack", "audit:read",
                "records:read", "doc:read_all", "doc:unmask"},
    "regional_officer": {"app:read_all", "finding:review", "app:decide", "app:final_decision", "verify:recheck",
                         "alert:ack", "audit:read", "records:read", "doc:read_all", "doc:unmask"},
    "admin": {"app:read_all", "audit:read", "rules:read", "rules:reload", "records:read", "doc:read_all",
              "alert:ack", "metrics:read", "retention:manage", "app:decide", "app:final_decision", "doc:unmask"},
    "auditor": {"app:read_all", "audit:read", "records:read", "doc:read_all"},
}

# Encryption-at-rest key derived from JWT_SECRET
_FERNET_KEY = base64.urlsafe_b64encode(hashlib.sha256(JWT_SECRET.encode()).digest())
_cipher = Fernet(_FERNET_KEY)


def encrypt_file_bytes(data: bytes) -> bytes:
    """AES-256 (CBC/HMAC via Fernet) encryption at rest."""
    return _cipher.encrypt(data)


def decrypt_file_bytes(data: bytes) -> bytes:
    """Decrypt file data at rest; gracefully returns unencrypted bytes if already plaintext."""
    try:
        return _cipher.decrypt(data)
    except Exception:
        return data


# PII Regex patterns
AADHAAR_REGEX = re.compile(r"\b([2-9]\d{3})[ -]?(\d{4})[ -]?(\d{4})\b")
PAN_REGEX = re.compile(r"\b([A-Z]{5})(\d{4})([A-Z])\b")
BANK_REGEX = re.compile(r"\b([0-9]{5,14})([0-9]{4})\b")


def mask_pii_string(val: str) -> str:
    if not isinstance(val, str) or not val:
        return val
    # Mask Aadhaar: e.g. XXXX-XXXX-1234
    val = AADHAAR_REGEX.sub(r"XXXX-XXXX-\3", val)
    # Mask PAN: e.g. XXXXX1234F
    val = PAN_REGEX.sub(r"XXXXX\2\3", val)
    return val


def mask_pii_dict(obj):
    """Recursively mask PII fields across extraction structures."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("aadhaar_no", "aadhaar_number", "pan", "pan_number", "bank_account"):
                if isinstance(v, dict) and "value" in v:
                    v_copy = dict(v)
                    v_copy["value"] = mask_pii_string(str(v["value"]))
                    if "normalized" in v_copy and v_copy["normalized"]:
                        v_copy["normalized"] = mask_pii_string(str(v_copy["normalized"]))
                    out[k] = v_copy
                elif isinstance(v, str):
                    out[k] = mask_pii_string(v)
                else:
                    out[k] = v
            else:
                out[k] = mask_pii_dict(v)
        return out
    elif isinstance(obj, list):
        return [mask_pii_dict(item) for item in obj]
    elif isinstance(obj, str):
        return mask_pii_string(obj)
    return obj


# ------------------------------------------------------------------ Rate Limiting & Threat Protection

class RateLimiter:
    """Sliding-window thread-safe rate limiter, account lockout, and token blacklist guard."""
    def __init__(self):
        self._lock = threading.Lock()
        self._requests: dict[str, list[float]] = {}
        self._failed_logins: dict[str, list[float]] = {}
        self._used_captchas: dict[str, float] = {}
        self._revoked_tokens: dict[str, float] = {}

    def is_rate_limited(self, key: str, max_requests: int = 150, window_seconds: int = 60) -> bool:
        now = time.time()
        with self._lock:
            history = self._requests.setdefault(key, [])
            cutoff = now - window_seconds
            history = [t for t in history if t > cutoff]
            if len(history) >= max_requests:
                self._requests[key] = history
                return True
            history.append(now)
            self._requests[key] = history
            return False

    def record_failed_login(self, key: str) -> int:
        now = time.time()
        with self._lock:
            history = self._failed_logins.setdefault(key, [])
            history = [t for t in history if t > now - 180]  # 3 minute rolling window
            history.append(now)
            self._failed_logins[key] = history
            return len(history)

    def is_login_locked(self, key: str, max_fails: int = 5) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            history = self._failed_logins.get(key, [])
            cutoff = now - 180
            history = [t for t in history if t > cutoff]
            self._failed_logins[key] = history
            if len(history) >= max_fails:
                remaining = int(180 - (now - history[0]))
                return True, max(remaining, 1)
            return False, 0

    def reset_failed_login(self, key: str):
        with self._lock:
            self._failed_logins.pop(key, None)

    def mark_captcha_used(self, sig: str, expiry: float) -> bool:
        """Mark a CAPTCHA signature as used. Returns False if already used (replay prevention)."""
        now = time.time()
        with self._lock:
            self._used_captchas = {k: exp for k, exp in self._used_captchas.items() if exp > now}
            if sig in self._used_captchas:
                return False
            self._used_captchas[sig] = expiry
            return True

    def revoke_token(self, token: str, expiry: float):
        now = time.time()
        with self._lock:
            self._revoked_tokens = {k: exp for k, exp in self._revoked_tokens.items() if exp > now}
            self._revoked_tokens[token] = expiry

    def is_token_revoked(self, token: str) -> bool:
        now = time.time()
        with self._lock:
            exp = self._revoked_tokens.get(token)
            if exp and exp > now:
                return True
            return False

security_guard = RateLimiter()


# ------------------------------------------------------------------ File Upload Hardening

DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".bash", ".ps1", ".vbs", ".js", ".ts", ".html",
    ".htm", ".xhtml", ".php", ".phtml", ".py", ".pyc", ".dll", ".so", ".jar", ".msi",
    ".scr", ".hta", ".cpl", ".reg", ".wsf", ".svg", ".xml"
}

DANGEROUS_PATTERNS = [
    b"<?php",
    b"<script",
    b"javascript:",
    b"/bin/sh",
    b"/bin/bash",
    b"cmd.exe",
    b"powershell",
    b"MZ\x90\x00",
    b"\x7fELF",
]


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent directory traversal and null byte injections."""
    if not filename:
        return "upload.bin"
    name = Path(filename).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"\.\.+[/\\;]", "", name)
    name = name.strip()
    return name or "upload.bin"


def inspect_file_security(raw: bytes, filename: str) -> None:
    """Deep security inspection for malware signatures, double extensions, and dangerous bytes."""
    sanitized = sanitize_filename(filename).lower()
    ext = Path(sanitized).suffix.lower()

    if ext in DANGEROUS_EXTENSIONS or any(sanitized.endswith(bad_ext) for bad_ext in DANGEROUS_EXTENSIONS):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            f"Prohibited file format detected for '{filename}'. Executable or script files are strictly blocked.")

    parts = sanitized.split(".")
    if len(parts) > 2:
        for middle_ext in parts[1:-1]:
            if f".{middle_ext}" in DANGEROUS_EXTENSIONS:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"Security violation: dangerous double extension '.{middle_ext}' detected in '{filename}'.")

    header_sample = raw[:4096]
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in header_sample.lower():
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                                f"Security inspection alert: prohibited content signature detected in file '{filename}'.")


def sniff_and_validate_file(raw: bytes, filename: str) -> str:
    """Sniff magic bytes to ensure file matches approved MIME types and size."""
    inspect_file_security(raw, filename)
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds maximum 25 MB limit")
    if raw.startswith(b"%PDF"):
        return "application/pdf"
    if raw.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"II*\x00") or raw.startswith(b"MM\x00*"):
        return "image/tiff"
    raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        f"Unsupported or dangerous file signature for '{filename}'. Allowed: PDF, JPEG, PNG, TIFF.")


def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return salt.hex() + "$" + dk.hex()


def check_password(pw: str, stored: str) -> bool:
    salt_hex, dk_hex = stored.split("$")
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), 200_000)
    return hmac.compare_digest(dk.hex(), dk_hex)


def issue_token(user: dict) -> str:
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "inst": user.get("institution_id"),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_TTL_MIN),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    token = creds.credentials if creds else request.query_params.get("token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if security_guard.is_token_revoked(token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session token has been revoked upon logout. Please sign in again.")
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    with tx() as c:
        u = row(c.execute("SELECT id,username,full_name,role,institution_id FROM users WHERE username=?",
                          (data["sub"],)).fetchone())
    if not u:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return u


def require(permission: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if permission not in PERMISSIONS.get(user["role"], set()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Role '{user['role']}' lacks '{permission}'")
        return user
    return dep


def can_read_application(user: dict, app: dict) -> bool:
    if "app:read_all" in PERMISSIONS.get(user["role"], set()):
        # Local vault drafts that have never been frozen/submitted are kept strictly in the institution's private local cloud
        if app.get("storage_tier") == "LOCAL_INSTITUTE_VAULT" and not app.get("is_frozen") and app.get("status") == "DRAFT":
            return False
        return True
    return user["role"] == "institution" and user["institution_id"] == app["institution_id"]


def generate_captcha() -> dict:
    """Generate a cryptographic HMAC-signed alphanumeric CAPTCHA challenge with noise-distorted SVG."""
    chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(random.choices(chars, k=5))
    expiry = int(time.time()) + 300  # 5 minutes validity
    sig = hmac.new(JWT_SECRET.encode(), f"{code}:{expiry}".encode(), hashlib.sha256).hexdigest()
    captcha_id = f"{expiry}:{sig}"

    colors = ["#1F6B52", "#2563EB", "#B45309", "#4338CA", "#047857", "#7C3AED", "#C2410C"]
    elements = []
    # Subtle curved noise lines
    for _ in range(4):
        x1, y1 = random.randint(4, 30), random.randint(5, 38)
        x2, y2 = random.randint(110, 136), random.randint(5, 38)
        cx, cy = random.randint(40, 95), random.randint(5, 38)
        lc = random.choice(colors)
        elements.append(f'<path d="M {x1} {y1} Q {cx} {cy} {x2} {y2}" stroke="{lc}" stroke-width="1.6" fill="none" opacity="0.35"/>')
    # Random noise dots
    for _ in range(22):
        rx, ry = random.randint(5, 135), random.randint(4, 38)
        elements.append(f'<circle cx="{rx}" cy="{ry}" r="1.3" fill="{random.choice(colors)}" opacity="0.32"/>')
    # Characters with rotation and jitter
    for i, ch in enumerate(code):
        x = 18 + i * 25
        y = random.randint(28, 33)
        angle = random.randint(-16, 16)
        color = colors[i % len(colors)]
        elements.append(
            f'<text x="{x}" y="{y}" fill="{color}" font-size="22" font-weight="bold" '
            f'font-family="system-ui, -apple-system, Segoe UI, Roboto, monospace" '
            f'transform="rotate({angle} {x} {y})" text-anchor="middle">{ch}</text>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="140" height="42" viewBox="0 0 140 42" '
        f'style="background:#F3F4F6; border:1px solid #E5E7EB; border-radius:6px; display:block; user-select:none;">'
        + "".join(elements) +
        f'</svg>'
    )
    return {"captcha_id": captcha_id, "captcha_svg": svg}


def verify_captcha(captcha_id: str | None, captcha_code: str | None) -> tuple[bool, str]:
    """Verify submitted CAPTCHA code against HMAC-signed token."""
    if not captcha_id or not captcha_code or not captcha_code.strip():
        return False, "Please enter the CAPTCHA security code."
    parts = captcha_id.split(":", 1)
    if len(parts) != 2:
        return False, "Malformed CAPTCHA challenge."
    ts_str, sig = parts
    try:
        ts = int(ts_str)
    except ValueError:
        return False, "Invalid CAPTCHA token format."
    if ts < int(time.time()):
        return False, "CAPTCHA code has expired. Please click refresh to get a new code."
    if not security_guard.mark_captcha_used(sig, float(ts)):
        return False, "This CAPTCHA code has already been used. Please click refresh to get a new code."
    expected_sig = hmac.new(JWT_SECRET.encode(), f"{captcha_code.strip().upper()}:{ts_str}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return False, "Incorrect CAPTCHA code. Please check the characters and try again."
    return True, ""
