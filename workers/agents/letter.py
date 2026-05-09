"""Cover letter / consulting pitch generator.

Uses the company's research_json + the job's description + the user's
fixed identity (AiAppGenius founder, full-stack solo) to produce a
short, hand-crafted-feeling email plus a one-line subject.

Two angles, picked based on outreach.pitch_angle:
  - "job_application": pitch for the role, lean on building the very
    automation that surfaced this letter.
  - "consulting": pitch a brief paid engagement instead, since the company
    is clearly already trying to hire for the problem.

The body always ends with a CTA that links to the recruiter share page.
The share-link URL is materialised by the sender, not here — we leave
the placeholder {{SHARE_LINK}} in the markdown body.
"""
from __future__ import annotations

import json
import time
from typing import Any

from ..db import db
from ..process import log_step
from .claude import complete

SYSTEM_JOB = """You are writing a brief, sharp outreach email from a solo founder/engineer
applying for a role. Tone: confident but not boastful, specific to the company's situation,
zero generic LinkedIn-speak. 90-180 words MAX. Close with a CTA pointing to {{SHARE_LINK}},
which is a page that demonstrates the AI agent that found and personalised this email.

Reply with ONLY a JSON object matching this schema:
{
  "subject": string,        // <= 70 chars, no clickbait
  "body_md": string         // markdown, must contain the literal token {{SHARE_LINK}} on a CTA line
}"""

SYSTEM_CONSULT = """You are writing a brief, sharp outreach email from a solo founder of AiAppGenius
proposing a small paid engagement INSTEAD of full-time hire — because the company is currently
hiring for the same kind of problem he ships fast. Tone: confident, respectful of their hiring
process, framed as an alternative not a replacement. 90-180 words MAX. Close with a CTA pointing
to {{SHARE_LINK}}, which is a page that demonstrates the AI agent that found and personalised this email.

Reply with ONLY a JSON object matching this schema:
{
  "subject": string,        // <= 70 chars
  "body_md": string         // markdown, must contain the literal token {{SHARE_LINK}}
}"""


def draft_letter(outreach_id: str) -> dict[str, Any]:
    started = time.time()
    o = db().table("outreach").select("*, jobs(*), companies(*)").eq("id", outreach_id).single().execute().data
    job = o["jobs"]
    company = o["companies"]
    settings = db().table("settings").select("*").eq("id", 1).single().execute().data
    angle = o.get("pitch_angle") or settings.get("pitch_default") or "consulting"

    user_msg = (
        f"COMPANY: {company['name']}\n"
        f"WEBSITE: {company.get('website') or company.get('domain') or '(unknown)'}\n"
        f"INDUSTRY: {company.get('research_json', {}).get('industry') or '—'}\n"
        f"WHAT THEY DO: {company.get('research_summary') or '—'}\n"
        f"FIT SIGNALS: {json.dumps(company.get('research_json', {}).get('automation_pain_signals') or [])}\n"
        f"AI SIGNALS: {json.dumps(company.get('research_json', {}).get('ai_investment_signals') or [])}\n\n"
        f"ROLE: {job['title']}\n"
        f"ROLE DESCRIPTION (truncated):\n{(job.get('description') or '')[:2500]}\n\n"
        f"SENDER: {settings.get('sender_name')}, {settings.get('sender_title')} of AiAppGenius\n"
        f"SENDER STRENGTH: solo full-stack engineer who ships AI-powered internal tools and "
        f"outreach/automation systems quickly (Next.js + Supabase + Python + Claude).\n"
        f"REPLY-TO: {settings.get('from_email')}"
    )

    sys_prompt = SYSTEM_JOB if angle == "job_application" else SYSTEM_CONSULT
    result = complete(system=sys_prompt, user=user_msg, max_tokens=900)

    try:
        parsed = json.loads(result["text"])
    except Exception:
        import re
        m = re.search(r"\{[\s\S]+\}", result["text"])
        parsed = json.loads(m.group(0)) if m else {}

    subject = parsed.get("subject") or f"Re: {job['title']}"
    body_md = parsed.get("body_md") or result["text"]

    # Bump version.
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
        title=f"Drafted {angle.replace('_', ' ')} letter v{version}",
        summary=f"**Subject:** {subject}\n\n{body_md}",
        inputs={"angle": angle, "company": company['name'], "role": job['title']},
        outputs={"subject": subject, "version": version},
        model=result["model"],
        tokens_used=result["tokens_in"] + result["tokens_out"],
        duration_ms=int((time.time() - started) * 1000),
    )

    return letter
