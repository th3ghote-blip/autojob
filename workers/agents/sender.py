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
    """Wrap rendered markdown in a branded, email-client-safe HTML shell.

    Layout (top to bottom):
      - Outer white card, rounded, subtle border + soft shadow
      - 5px gradient strip (violet → purple → pink), matches share page header
      - Brand row: "AiAppGenius" wordmark + tiny gradient dot
      - Body
    Tables for layout (older-client compat). Inline styles only.
    """
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'font-size:15px;line-height:1.65;color:#1f2937;background:#f3f4f6;padding:12px 0;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" '
        'style="border-collapse:separate;border-radius:14px;overflow:hidden;'
        'border:1px solid #e5e7eb;background:#ffffff;max-width:620px;width:100%;'
        'box-shadow:0 4px 16px rgba(15,23,42,0.06);">'
        # Gradient strip (matches share page hero gradient)
        '<tr><td style="height:5px;line-height:5px;font-size:0;'
        'background:linear-gradient(90deg,#6366f1 0%,#a855f7 50%,#ec4899 100%);'
        'background-color:#6366f1;">&nbsp;</td></tr>'
        # Brand header row
        '<tr><td style="padding:18px 30px 10px 30px;border-bottom:1px solid #f3f4f6;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
        '<tr>'
        '<td style="vertical-align:middle;padding-right:10px;">'
        '<div style="width:8px;height:8px;border-radius:50%;'
        'background:linear-gradient(135deg,#6366f1,#ec4899);'
        'box-shadow:0 0 0 3px rgba(99,102,241,0.15);">&nbsp;</div>'
        '</td>'
        '<td style="vertical-align:middle;font-size:13px;font-weight:600;color:#1f2937;letter-spacing:-0.01em;">'
        'AiAppGenius'
        '</td>'
        '<td style="vertical-align:middle;padding-left:10px;font-size:11px;color:#9ca3af;'
        'letter-spacing:0.08em;text-transform:uppercase;">'
        'sent by an agent'
        '</td>'
        '</tr></table>'
        '</td></tr>'
        # Body cell
        '<tr><td style="padding:24px 30px 18px 30px;color:#1f2937;font-size:15px;line-height:1.65;">'
        + body_html
        + "</td></tr>"
        "</table>"
        "</div>"
    )


def _stylize_share_cta(html: str, *, share_url: str) -> str:
    """Replace the share-link <a> with a dark-themed CTA panel that mirrors
    the share page's visual language (deep navy background, gradient hero
    text, pulsing live dot, gradient button). Idempotent.
    """
    cta_block = (
        # Outer dark card, full width inside email body.
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
        'style="border-collapse:separate;margin:22px 0 22px 0;">'
        '<tr><td style="background:#0f172a;'
        'background-image:linear-gradient(135deg,#1e1b4b 0%,#0f172a 55%,#020617 100%);'
        'background-color:#0f172a;'
        'border-radius:12px;padding:20px 22px;'
        'border:1px solid rgba(99,102,241,0.25);">'
        # Live demo badge row
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
        '<tr>'
        '<td style="vertical-align:middle;padding-right:8px;">'
        '<div style="width:6px;height:6px;border-radius:50%;background:#34d399;'
        'box-shadow:0 0 0 3px rgba(52,211,153,0.2);">&nbsp;</div>'
        '</td>'
        '<td style="vertical-align:middle;font-size:10px;font-weight:600;'
        'letter-spacing:0.16em;text-transform:uppercase;color:#a78bfa;">'
        'Live demo · the AI process'
        '</td>'
        '</tr></table>'
        # Headline
        '<div style="margin:10px 0 4px 0;font-size:16px;line-height:1.4;color:#f1f5f9;'
        'font-weight:600;letter-spacing:-0.01em;">'
        'See how this email reached you'
        '</div>'
        # Subline
        '<div style="font-size:13px;line-height:1.5;color:#94a3b8;margin-bottom:14px;">'
        'Every step the agent took — from finding your post to writing this — laid out in order.'
        '</div>'
        # Button
        f'<a href="{share_url}" '
        'style="display:inline-block;'
        'background:linear-gradient(90deg,#6366f1 0%,#a855f7 55%,#ec4899 100%);'
        'background-color:#6366f1;'
        'color:#ffffff;padding:11px 20px;border-radius:8px;text-decoration:none;'
        'font-weight:600;font-size:14px;letter-spacing:-0.01em;'
        'box-shadow:0 6px 18px rgba(168,85,247,0.4);">'
        'Open the demo page →'
        "</a>"
        "</td></tr></table>"
    )
    pattern = re.compile(
        r'<a[^>]*href="' + re.escape(share_url) + r'"[^>]*>[^<]*</a>',
        re.I,
    )
    if pattern.search(html):
        return pattern.sub(cta_block, html, count=1)
    if share_url in html and '<a' not in html.split(share_url, 1)[0][-30:]:
        return html.replace(share_url, cta_block, 1)
    return html


def _append_signature(html: str, settings: dict[str, Any]) -> str:
    """Append the operator signature with a faint divider + a tiny brand mark."""
    sig_html = settings.get("email_signature_html") or ""
    if not sig_html:
        return html
    divider = (
        '<div style="height:1px;line-height:1px;font-size:0;'
        'background:linear-gradient(90deg,transparent,#e5e7eb 20%,#e5e7eb 80%,transparent);'
        'margin:26px 0 14px 0;">&nbsp;</div>'
    )
    sig_block = (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:collapse;">'
        '<tr>'
        # Tiny gradient bar accent
        '<td style="vertical-align:top;padding-right:12px;">'
        '<div style="width:3px;height:34px;border-radius:2px;'
        'background:linear-gradient(180deg,#6366f1,#ec4899);">&nbsp;</div>'
        '</td>'
        '<td style="vertical-align:top;font-size:13px;color:#6b7280;line-height:1.55;">'
        + sig_html
        + '</td>'
        '</tr></table>'
    )
    return html + divider + sig_block


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
