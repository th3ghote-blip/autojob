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

═══════════════════════════════════════════════════════════════════════════
HARD HONESTY RULES — VIOLATING THESE GETS THE OPERATOR CAUGHT IN INTERVIEW
═══════════════════════════════════════════════════════════════════════════

1. The operator's PROFILE (provided in the user message) lists his actual stack
   and edges. **NEVER claim a skill, framework, language, or tool that is not
   visible in the profile.** If the company's stack (Django, Rails, Go, .NET,
   Flutter, MongoDB, Kubernetes, Rust, etc.) is not in his profile, DO NOT say
   he uses it, has shipped with it, has it "in scope", or is "fluent in" it.

2. When the operator's stack and the company's stack differ, frame honestly:
     - "I haven't shipped <X> in production but I ramp fast on adjacent tools"
     - "My recent work is <Y>; same shape of problem, different stack"
     - Or just don't mention the mismatched tech at all and pitch on the
       PROBLEM (workflow design, customer engineering, shipping speed).

3. Do NOT invent past projects, customers, geographies (e.g. "LATAM trafficking
   corridors"), revenue, or experience. Use only edges + brand context from the
   profile, plus what the post itself says.

3b. ENGLISH-FIRST — STRICT. The operator is English-native. Spanish and
    Brazilian Portuguese are BONUS languages mentioned ONLY when the post or
    company research EXPLICITLY mentions LATAM, Brazilian, Iberian, Portuguese-
    or Spanish-speaking customers, operations, markets, or hires.

    HARD BAN on speculation:
      - "if you ever get LATAM founders" → REMOVE the whole sentence
      - "useful if X ever has LATAM execs" → REMOVE
      - "opens LATAM markets if that's on your roadmap" → REMOVE
      - any phrasing like "if/when/in case X expands to..." → REMOVE
    The trilingual mention either has direct evidence in the source material
    or it doesn't exist in the letter. No middle ground. Including
    "I'm based in Spain" as a location fact is FINE (not invoking the
    language edge, just stating where you live).

4. If after reading the post you genuinely can't find a defensible bridge from
   the operator's edges to what they need, set body_md = "" and put your
   reasoning in the `skipped_reason` field. The orchestrator will mark this
   outreach as "lost" instead of sending a fabricated letter.

═══════════════════════════════════════════════════════════════════════════
APPLY-INSTRUCTION GATES — OBEY THEM EXACTLY
═══════════════════════════════════════════════════════════════════════════
Recruiters add filters like:
  - "Use this exact subject line: `[CODE-X] HN Application`" → use it verbatim
  - "Include the word 'Atlas' in your first sentence" → include it naturally
  - "Tell us what you would build in your first week" → answer concretely
    (but ONLY in terms of skills the operator actually has — see rule 1)
  - "Emails without X are auto-archived" → take seriously
Missing these gets the email deleted unread.

═══════════════════════════════════════════════════════════════════════════
TONE & STRUCTURE
═══════════════════════════════════════════════════════════════════════════
Confident but not boastful, specific to the company's stated situation, zero
generic LinkedIn-speak. 90-180 words MAX (longer OK only if the post asked
for "first week" content). Do NOT pad. Do NOT use "exciting" or "passionate".
Do NOT list edges as bullets — weave 1-2 into prose where they connect to a
real, stated need.

Close with a CTA pointing to {{SHARE_LINK}} — a page demonstrating the AI agent
that found this role. Phrase it as proof of the work, not a generic link.

Pitch angle for THIS email: {angle_instruction}

═══════════════════════════════════════════════════════════════════════════
OUTPUT — JSON only, no prose, no markdown, no code fences
═══════════════════════════════════════════════════════════════════════════
{{
  "subject": string,
  "body_md": string,                  // MUST contain {{{{SHARE_LINK}}}} on a CTA line. Empty string ("") if you bailed on honesty grounds.
  "instructions_followed": string,    // 1-2 sentences listing application gates you obeyed, or "none found"
  "stack_overlap": string,            // 1 sentence: which of the post's tech the operator actually has, plus what's missing
  "skipped_reason": string            // empty unless body_md is "" — then explain why no honest bridge exists
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

DELIVERY_INSTRUCTIONS = {
    "email": (
        "This will be sent as an email. Open with 'Hi [name],' or 'Hi,' if no name available. "
        "Use natural email cadence (short paragraphs, easy to skim on a phone). The share link "
        "appears on its own line as a CTA. End with — Andrew."
    ),
    "form": (
        "This will be PASTED into an ATS application form's cover-letter textarea (Greenhouse, Lever, "
        "Ashby). Recruiters read it inside their ATS dashboard with no formatting. Therefore:\n"
        "  - NO greeting line ('Hi [name],') — start with the first content sentence directly\n"
        "  - NO signature/sign-off ('Andrew', '— Andrew')\n"
        "  - 80-140 words MAX, single coherent block. Form fields like name/email/LinkedIn are "
        "collected separately, you don't need to introduce yourself by name\n"
        "  - Render the share link as a postscript-style line at the very end, plain URL, "
        "labelled so it's obvious what it is — e.g. exactly:\n"
        "      Built by the agent that found this role: {{SHARE_LINK}}\n"
        "    or:\n"
        "      How this letter was produced: {{SHARE_LINK}}\n"
        "  - Do NOT phrase the share link as a question or imperative — recruiters reading 100 "
        "applications skim, they don't click commands"
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

    # Delivery method: if no contact_email on the job, recruiter will read this
    # inside their ATS form (Greenhouse/Lever/Ashby textarea) — different format.
    delivery = "email" if (job.get("contact_email") or "").strip() else "form"

    angle_instruction = ANGLE_INSTRUCTIONS.get(angle, ANGLE_INSTRUCTIONS["consulting"])
    delivery_instruction = DELIVERY_INSTRUCTIONS[delivery]
    sys_prompt = SYSTEM_TEMPLATE.format(
        name=profile["identity"]["name"],
        angle_instruction=angle_instruction,
    ) + "\n\nDELIVERY METHOD: " + delivery_instruction

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
    body_md = (parsed.get("body_md") or "").strip()
    skipped_reason = (parsed.get("skipped_reason") or "").strip()

    # Bail if Claude couldn't find an honest bridge between operator + role.
    if not body_md and skipped_reason:
        db().table("outreach").update({
            "stage": "lost",
            "lost_reason": f"no honest bridge: {skipped_reason}"[:500],
        }).eq("id", outreach_id).execute()
        log_step(
            outreach_id, kind="letter_drafted",
            title="Letter NOT drafted — no honest bridge",
            summary=f"**Reason:** {skipped_reason}\n\n**Stack overlap:** {parsed.get('stack_overlap', '—')}\n\n_The agent declined to write a letter because it could not connect the operator's actual skills to what the role needs without overclaiming._",
            inputs={"angle": angle},
            outputs=parsed,
            model=result["model"],
            tokens_used=result["tokens_in"] + result["tokens_out"],
            duration_ms=int((time.time() - started) * 1000),
            visible_to_recruiter=False,
        )
        return {"skipped": True, "reason": skipped_reason}

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

    # Only bump stage forward to ready_to_send if it hasn't already progressed.
    # Re-drafting an already-sent letter must NOT yank the card back to the
    # "ready" column.
    SENT_STAGES = {"sent", "opened", "replied", "demo_booked", "won", "lost"}
    cur_stage = (db().table("outreach").select("stage").eq("id", outreach_id).single().execute().data or {}).get("stage")
    if cur_stage not in SENT_STAGES:
        db().table("outreach").update({"stage": "ready_to_send"}).eq("id", outreach_id).execute()

    # Idempotent step logging: if a letter_drafted step already exists for this
    # outreach, update it in place. Re-drafts shouldn't pollute the trail with
    # multiple "Drafted letter vN" rows — recruiters only need to see the
    # latest. The version number in the title still reflects the actual count.
    existing = (
        db().table("process_steps").select("id")
        .eq("outreach_id", outreach_id).eq("kind", "letter_drafted").limit(1).execute()
    ).data
    payload = {
        "title": f"Drafted {angle.replace('_', ' ')} email v{version}",
        "summary": f"**Subject:** {subject}\n\n{body_md}",
        "input_redacted_json": {"angle": angle, "company": company['name'], "role": job['title']},
        "output_redacted_json": {"subject": subject, "version": version},
        "model": result["model"],
        "tokens_used": result["tokens_in"] + result["tokens_out"],
        "duration_ms": int((time.time() - started) * 1000),
        "occurred_at": "now()",
    }
    if existing:
        db().table("process_steps").update(payload).eq("id", existing[0]["id"]).execute()
    else:
        log_step(
            outreach_id,
            kind="letter_drafted",
            title=payload["title"],
            summary=payload["summary"],
            inputs=payload["input_redacted_json"],
            outputs=payload["output_redacted_json"],
            model=payload["model"],
            tokens_used=payload["tokens_used"],
            duration_ms=payload["duration_ms"],
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
