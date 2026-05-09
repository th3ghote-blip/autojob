"""Gmail sender + tracking + share-link materialisation.

Mirrors aiappgenius-outreach/lib/gmail.js conceptually, in Python:
  - SMTP via Gmail App Password (GMAIL_USER / GMAIL_APP_PASSWORD)
  - tracking pixel URL injected at end of HTML body
  - all <a href> rewritten through /api/track/click/<send_log_id>?u=<dest>
    (Next.js handles the redirect + records a click_event)
  - the share link {{SHARE_LINK}} placeholder is replaced with the per-recruiter
    URL after a share_links row is created. share-link clicks set
    send_logs.share_link_clicked separately so we know if THE demo was opened.

Honors settings.daily_send_limit. Does NOT send anything when stage != ready_to_send
unless force=True.
"""
from __future__ import annotations

import os
import re
import secrets
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
from urllib.parse import quote

import markdown as md

from ..db import db
from ..process import log_step


def send_outreach(outreach_id: str, *, force: bool = False) -> dict[str, Any]:
    started = time.time()
    o = db().table("outreach").select("*, jobs(*), companies(*)").eq("id", outreach_id).single().execute().data
    if not force and o["stage"] != "ready_to_send":
        return {"skipped": True, "reason": f"stage is {o['stage']}"}

    job = o["jobs"]
    company = o["companies"]
    to_email = job.get("contact_email")
    if not to_email:
        return {"skipped": True, "reason": "no contact email on job"}

    settings = db().table("settings").select("*").eq("id", 1).single().execute().data
    if not _within_daily_limit(settings["daily_send_limit"]):
        return {"skipped": True, "reason": "daily send limit reached"}

    letter = (
        db().table("letters").select("*").eq("outreach_id", outreach_id)
        .order("version", desc=True).limit(1).execute()
    ).data
    if not letter:
        return {"skipped": True, "reason": "no letter drafted yet"}
    letter = letter[0]

    share_token = secrets.token_urlsafe(24)
    share_url = f"{settings['app_url'].rstrip('/')}/share/{share_token}"
    db().table("share_links").insert({
        "outreach_id": outreach_id,
        "token": share_token,
    }).execute()

    body_md = (letter["body_md"] or "").replace("{{SHARE_LINK}}", share_url)
    body_html = md.markdown(body_md, extensions=["extra", "nl2br"])

    # Reserve a send_logs row early so we can use its id in tracking URLs.
    send_log = db().table("send_logs").insert({
        "letter_id": letter["id"],
        "outreach_id": outreach_id,
        "job_id": job["id"],
        "company_id": company["id"],
        "to_email": to_email,
        "to_name": job.get("contact_name"),
        "subject": letter["subject"],
        "status": "sent",
    }).execute().data[0]

    body_html = _wrap_links(body_html, send_log_id=send_log["id"], share_token=share_token, app_url=settings["app_url"])
    body_html += _tracking_pixel(send_log["id"], settings["app_url"])
    body_html += "\n<br><br>" + (settings.get("email_signature_html") or "")

    msg = _build_message(
        from_name=settings["sender_name"],
        from_email=settings["from_email"],
        reply_to=settings.get("reply_to_email") or settings["from_email"],
        to_email=to_email,
        to_name=job.get("contact_name"),
        subject=letter["subject"],
        html=body_html,
    )

    try:
        _smtp_send(msg, from_email=settings["from_email"])
        db().table("letters").update({"sent": True}).eq("id", letter["id"]).execute()
        db().table("outreach").update({"stage": "sent", "sent_at": "now()"}).eq("id", outreach_id).execute()
        log_step(
            outreach_id,
            kind="sent",
            title=f"Sent to {to_email}",
            summary=f"Email delivered via Gmail SMTP. Tracking pixel + share link active.\n\nShare link: {share_url}",
            inputs={"to": to_email, "subject": letter["subject"]},
            outputs={"send_log_id": send_log["id"], "share_token": share_token},
            duration_ms=int((time.time() - started) * 1000),
        )
        return {"ok": True, "send_log_id": send_log["id"], "share_url": share_url}
    except Exception as e:  # noqa: BLE001
        db().table("send_logs").update({
            "status": "failed",
            "bounce_reason": str(e),
        }).eq("id", send_log["id"]).execute()
        return {"ok": False, "error": str(e)}


def _within_daily_limit(limit: int) -> bool:
    today = datetime.now(timezone.utc).date().isoformat()
    res = (
        db().table("send_logs").select("id", count="exact")
        .gte("sent_at", today).eq("status", "sent").execute()
    )
    sent_today = res.count or 0
    return sent_today < limit


def _build_message(*, from_name: str, from_email: str, reply_to: str, to_email: str,
                   to_name: str | None, subject: str, html: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
    msg["Subject"] = subject
    msg["Reply-To"] = reply_to
    plain = re.sub(r"<[^>]+>", "", html)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def _smtp_send(msg: MIMEMultipart, *, from_email: str) -> None:
    user = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg, from_addr=from_email)


def _tracking_pixel(send_log_id: str, app_url: str) -> str:
    pixel = f"{app_url.rstrip('/')}/api/track/open/{send_log_id}.gif"
    return f'<img src="{pixel}" alt="" width="1" height="1" style="display:none">'


_HREF_RE = re.compile(r'href="([^"]+)"', re.I)


def _wrap_links(html: str, *, send_log_id: str, share_token: str, app_url: str) -> str:
    base = app_url.rstrip("/")

    def _sub(match: re.Match) -> str:
        url = match.group(1)
        if url.startswith("mailto:") or url.startswith("#"):
            return f'href="{url}"'
        is_share = f"/share/{share_token}" in url
        flag = "1" if is_share else "0"
        wrapped = f"{base}/api/track/click/{send_log_id}?u={quote(url, safe='')}&s={flag}"
        return f'href="{wrapped}"'

    return _HREF_RE.sub(_sub, html)
