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


def send_outreach(outreach_id: str, *, force: bool = False, test_to: str | None = None) -> dict[str, Any]:
    started = time.time()
    o = db().table("outreach").select("*, jobs(*), companies(*)").eq("id", outreach_id).single().execute().data
    if not force and not test_to and o["stage"] != "ready_to_send":
        return {"skipped": True, "reason": f"stage is {o['stage']}"}

    job = o["jobs"]
    company = o["companies"]

    # Test-send: override recipient with the operator's address.
    if test_to:
        to_email = test_to
    else:
        to_email = job.get("contact_email")
        if not to_email:
            return {"skipped": True, "reason": "no contact email on job"}

    settings = db().table("settings").select("*").eq("id", 1).single().execute().data
    # Daily limit doesn't apply to test sends.
    if not test_to and not _within_daily_limit(settings["daily_send_limit"]):
        return {"skipped": True, "reason": "daily send limit reached"}

    letter = (
        db().table("letters").select("*").eq("outreach_id", outreach_id)
        .order("version", desc=True).limit(1).execute()
    ).data
    if not letter:
        return {"skipped": True, "reason": "no letter drafted yet"}
    letter = letter[0]

    # Get-or-create the share link (letter.py already does this at draft time,
    # so most of the time we just look it up).
    existing = (
        db().table("share_links").select("token")
        .eq("outreach_id", outreach_id).limit(1).execute()
    ).data
    if existing:
        share_token = existing[0]["token"]
    else:
        share_token = secrets.token_urlsafe(24)
        db().table("share_links").insert({
            "outreach_id": outreach_id,
            "token": share_token,
        }).execute()
    share_url = f"{settings['app_url'].rstrip('/')}/share/{share_token}"

    body_md = (letter["body_md"] or "").replace("{{SHARE_LINK}}", share_url)
    body_html = md.markdown(body_md, extensions=["extra", "nl2br"])
    body_html = _stylize_share_cta(body_html, share_url=share_url)
    body_html = _append_signature(body_html, settings)
    body_html = _wrap_in_email_shell(body_html, subject=letter["subject"])

    # Reserve a send_logs row early so we can use its id in tracking URLs.
    send_log = db().table("send_logs").insert({
        "letter_id": letter["id"],
        "outreach_id": outreach_id,
        "job_id": job["id"],
        "company_id": company["id"],
        "to_email": to_email,
        "to_name": "TEST SEND" if test_to else job.get("contact_name"),
        "subject": ("[TEST] " if test_to else "") + letter["subject"],
        "status": "sent",
    }).execute().data[0]

    body_html = _wrap_links(body_html, send_log_id=send_log["id"], share_token=share_token, app_url=settings["app_url"])
    body_html += _tracking_pixel(send_log["id"], settings["app_url"])

    msg = _build_message(
        from_name=settings["sender_name"],
        from_email=settings["from_email"],
        reply_to=settings.get("reply_to_email") or settings["from_email"],
        to_email=to_email,
        to_name=None if test_to else job.get("contact_name"),
        subject=("[TEST] " if test_to else "") + letter["subject"],
        html=body_html,
    )

    try:
        _smtp_send(msg, from_email=settings["from_email"])
        if not test_to:
            db().table("letters").update({"sent": True}).eq("id", letter["id"]).execute()
            db().table("outreach").update({"stage": "sent", "sent_at": "now()"}).eq("id", outreach_id).execute()
            # Only the production send is part of the recruiter-visible trail.
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


def _wrap_in_email_shell(body_html: str, *, subject: str | None = None) -> str:
    """Wrap rendered markdown in a clean, email-client-safe HTML shell.

    Inline styles only (Gmail strips <style> blocks). Single-column container,
    comfortable line-height, sans-serif stack.
    """
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'font-size:15px;line-height:1.6;color:#1f2937;max-width:560px;">'
        + body_html
        + "</div>"
    )


def _stylize_share_cta(html: str, *, share_url: str) -> str:
    """Find the share-link <a> and re-render as a centered styled button on its
    own line. Idempotent — safe to call even if URL isn't present.
    """
    button_html = (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:18px 0;"><tr><td>'
        f'<a href="{share_url}" '
        'style="display:inline-block;background:#6366f1;color:#ffffff;'
        'padding:11px 20px;border-radius:8px;text-decoration:none;'
        'font-weight:600;font-size:14px;">'
        '🔍 See how this email reached you →'
        '</a></td></tr></table>'
    )
    # Match any <a href="<share_url>">…anything…</a> and replace with the button.
    pattern = re.compile(
        r'<a[^>]*href="' + re.escape(share_url) + r'"[^>]*>[^<]*</a>',
        re.I,
    )
    if pattern.search(html):
        return pattern.sub(button_html, html, count=1)
    # Also catch the case where {{SHARE_LINK}} is naked text (unlikely now but defensive).
    if share_url in html and '<a' not in html.split(share_url, 1)[0][-30:]:
        return html.replace(share_url, button_html, 1)
    return html


def _append_signature(html: str, settings: dict[str, Any]) -> str:
    """Append the operator signature with a faint divider above."""
    sig_html = settings.get("email_signature_html") or ""
    if not sig_html:
        return html
    divider = (
        '<hr style="border:0;border-top:1px solid #e5e7eb;margin:24px 0 12px 0;">'
    )
    return html + divider + (
        '<div style="font-size:13px;color:#6b7280;line-height:1.5;">'
        + sig_html
        + "</div>"
    )


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
