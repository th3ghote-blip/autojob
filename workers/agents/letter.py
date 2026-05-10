"""Cover letter / consulting pitch / retainer pitch generator.

Three angles, picked by outreach.pitch_angle (set by the qualifier):
  - "job_application": Andrew is applying for the role. Lean on edges that
    match the role description; close with the share-link demo CTA.
  - "consulting": pitch a paid AiAppGenius engagement instead of a hire,
    framed as "you're hiring 3+ for this — let me ship the first version
    in 6 weeks, you keep hiring for the rest".
  - "retainer": pitch a small add-on engagement to AiAppGenius's existing
    studio book ($2.5k+/mo) for sub-$100k roles that are otherwise a fit.

The body always ends with a CTA that links to {{SHARE_LINK}} — the sender
materialises the per-recruiter share URL at send time.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from typing import Any

from ..db import db
from ..process import log_step
from ..profile import load_profile, profile_for_prompt
from .claude import complete


SYSTEM_TEMPLATE = """You are writing a brief, sharp outreach email from {name}, a solo full-stack
engineer / founder of AiAppGenius. The recipient is a recruiter or hiring manager at the company below.

CRITICAL: BEFORE writing, read the job description carefully and OBEY any explicit application
instructions you find. Recruiters often add gates like:
  - "Use this exact subject line: `[CODE-X] HN Application`" → use it verbatim
  - "Include the word 'Atlas' in your first sentence" → include it naturally
  - "Send your resume to X" → mention attaching/sharing it
  - "Tell us what you would build in your first week" → answer concretely
  - "Emails without X are auto-archived" → take seriously, the gate is real
If you find such instructions, follow them PRECISELY. Missing them gets the email deleted unread.

Tone: confident but not boastful, specific to the company's situation, zero generic LinkedIn-speak.
90-180 words MAX (longer is OK if the post explicitly asked for "what you'd build first week" type
content, but stay sharp). Do NOT pad. Do NOT use "exciting" or "passionate". Do NOT list edges as
bullets — weave 1-2 of them into prose where they connect to the company's actual stated need.

Close with a CTA that points to {{SHARE_LINK}} — a page that demonstrates the AI agent that found
this role and personalised this email. Phrase it as proof of the work, not as a generic link.

Pitch angle for THIS email: {angle_instruction}

Reply with ONLY a JSON object — no prose, no markdown, no code fences:
{{
  "subject": string,        // <= 90 chars, EXACT match if the post mandated a subject line
  "body_md": string,        // markdown, MUST contain the literal token {{{{SHARE_LINK}}}} in a CTA line
  "instructions_followed": string  // 1-2 sentences listing the application requirements you obeyed (or "none found")
}}"""


ANGLE_INSTRUCTIONS = {
    "job_application": (
        "Andrew is applying for THIS role. The role is a strong genuine fit — write as a candidate, "
        "not a vendor. Reference one specific thing in the job description and connect it to one of "
        "Andrew's edges. Avoid 'I built X' resume-listing; instead show alignment with what they need."
    ),
    "consulting": (
        "Andrew is NOT applying for the role — he's offering to ship the same outcome as a paid "
        "AiAppGenius engagement, faster and cheaper than the hire. Frame it as an alternative path, "
        "respectful of the recruiter's process. If the company is hiring multiple similar roles, "
        "lean into 'let me deliver V1 in 6 weeks while you keep hiring for the rest'."
    ),
    "retainer": (
        "The role is a fit but the budget is below $100k/yr — too small for full-time. Pitch a small "
        "add-on engagement to AiAppGenius's existing studio book ($2.5k+/mo retainer or fixed-scope "
        "project), so they get the work done without committing to a hire. Frame as low-friction, "
        "month-to-month, easy to start and stop."
    ),
}


def draft_letter(outreach_id: str) -> dict[str, Any]:
    started = time.time()
    o = db().table("outreach").select("*, jobs(*), companies(*)").eq("id", outreach_id).single().execute().data
    job = o["jobs"]
    company = o["companies"]
    settings = db().table("settings").select("*").eq("id", 1).single().execute().data
    profile = load_profile()
    angle = o.get("pitch_angle") or settings.get("pitch_default") or "consulting"

    angle_instruction = ANGLE_INSTRUCTIONS.get(angle, ANGLE_INSTRUCTIONS["consulting"])
    sys_prompt = SYSTEM_TEMPLATE.format(
        name=profile["identity"]["name"],
        angle_instruction=angle_instruction,
    )

    user_msg = (
        "OPERATOR PROFILE:\n" + profile_for_prompt() + "\n\n"
        "TARGET COMPANY:\n"
        f"Name: {company['name']}\n"
        f"Website: {company.get('website') or company.get('domain') or '(unknown)'}\n"
        f"Industry: {(company.get('research_json') or {}).get('industry') or '—'}\n"
        f"What they do: {company.get('research_summary') or '—'}\n"
        f"Automation pain signals: {json.dumps((company.get('research_json') or {}).get('automation_pain_signals') or [])}\n"
        f"AI investment signals: {json.dumps((company.get('research_json') or {}).get('ai_investment_signals') or [])}\n\n"
        "TARGET ROLE:\n"
        f"Title: {job['title']}\n"
        # Send the FULL description — Claude needs to scan for application requirements
        # which often live near the bottom of the post.
        f"Full description:\n{(job.get('description') or '')[:6000]}\n\n"
        f"REPLY-TO (Andrew's email): {settings.get('from_email')}"
    )

    result = complete(system=sys_prompt, user=user_msg, max_tokens=900)
    parsed = _parse_json(result["text"])

    subject = parsed.get("subject") or f"Re: {job['title']}"
    body_md = parsed.get("body_md") or result["text"]

    # Materialise the share link AT DRAFT TIME so the dashboard preview shows
    # the real URL (and a test send uses the same link as the production one).
    share_token = _ensure_share_link(outreach_id)
    share_url = f"{settings['app_url'].rstrip('/')}/share/{share_token}"
    body_md = body_md.replace("{{SHARE_LINK}}", share_url)

    last = (
        db().table("letters").select("version")
        .eq("outreach_id", outreach_id).order("version", desc=True).limit(1).execute()
    ).data
    version = (last[0]["version"] + 1) if last else 1

    letter = db().table("letters").insert({
        "outreach_id": outreach_id,
        "version": version,
        "subject": subject,
        "body_md": body_md,
        "model": result["model"],
        "tokens_in": result["tokens_in"],
        "tokens_out": result["tokens_out"],
    }).execute().data[0]

    db().table("outreach").update({"stage": "ready_to_send"}).eq("id", outreach_id).execute()

    log_step(
        outreach_id,
        kind="letter_drafted",
        title=f"Drafted {angle.replace('_', ' ')} email v{version}",
        summary=f"**Subject:** {subject}\n\n{body_md}",
        inputs={"angle": angle, "company": company['name'], "role": job['title']},
        outputs={"subject": subject, "version": version},
        model=result["model"],
        tokens_used=result["tokens_in"] + result["tokens_out"],
        duration_ms=int((time.time() - started) * 1000),
    )

    return letter


def _parse_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]+\}", text)
        return json.loads(m.group(0)) if m else {}


def _ensure_share_link(outreach_id: str) -> str:
    """Get-or-create a share link token for this outreach. Idempotent."""
    existing = (
        db().table("share_links").select("token")
        .eq("outreach_id", outreach_id).limit(1).execute()
    ).data
    if existing:
        return existing[0]["token"]
    token = secrets.token_urlsafe(24)
    db().table("share_links").insert({
        "outreach_id": outreach_id,
        "token": token,
    }).execute()
    return token
