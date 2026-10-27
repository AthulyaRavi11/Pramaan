"""Email notifications for alerts.

Every notification is written to an outbox table (so officials can see what was
sent and when). If SMTP settings are present it is also delivered; otherwise it
stays queued with a clear status — the prototype never pretends to have sent mail.

    PRAMAAN_SMTP_HOST, PRAMAAN_SMTP_PORT (587), PRAMAAN_SMTP_USER, PRAMAAN_SMTP_PASSWORD, PRAMAAN_SMTP_FROM
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from .db import now_iso, tx


def _send(to: str, subject: str, body: str) -> str:
    host = os.environ.get("PRAMAAN_SMTP_HOST")
    if not host:
        return "QUEUED"                     # no mail server configured: kept in the outbox
    msg = EmailMessage()
    msg["From"] = os.environ.get("PRAMAAN_SMTP_FROM", "pramaan@localhost")
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.environ.get("PRAMAAN_SMTP_PORT", "587")), timeout=10) as s:
            s.starttls()
            if os.environ.get("PRAMAAN_SMTP_USER"):
                s.login(os.environ["PRAMAAN_SMTP_USER"], os.environ.get("PRAMAAN_SMTP_PASSWORD", ""))
            s.send_message(msg)
        return "SENT"
    except Exception as e:  # never break the workflow because mail failed
        return f"FAILED: {e.__class__.__name__}"


def notify(conn, audience: str, application_id: int, subject: str, lines: list[str], institution_id: str | None = None):
    """Queue (and, if configured, send) one email per recipient in the audience."""
    if audience == "institution":
        users = conn.execute("SELECT username, email FROM users WHERE role='institution' AND institution_id=?", (institution_id,)).fetchall()
    else:
        users = conn.execute("SELECT username, email FROM users WHERE role='officer'").fetchall()
    body = "\n".join(lines + ["", "Open Pramaan to see the evidence for each item.",
                              "This is an automated message from a prototype using synthetic data."])
    for u in users:
        to = u["email"] or f"{u['username']}@example.invalid"
        status = _send(to, subject, body)
        conn.execute("INSERT INTO notifications(application_id,recipient,email,subject,body,status,created_at) VALUES (?,?,?,?,?,?,?)",
                     (application_id, u["username"], to, subject, body, status, now_iso()))


def outbox(user: dict, limit: int = 200) -> list[dict]:
    with tx() as c:
        if user["role"] == "institution":
            rs = c.execute("SELECT n.*, a.ref FROM notifications n JOIN applications a ON a.id=n.application_id "
                           "WHERE n.recipient=? ORDER BY n.id DESC LIMIT ?", (user["username"], limit))
        else:
            rs = c.execute("SELECT n.*, a.ref FROM notifications n JOIN applications a ON a.id=n.application_id ORDER BY n.id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rs.fetchall()]
