"""LLM-based job qualifier.

Given a job + the profile, returns:
  - qualifies: bool
  - realism_tier: 'tier_1_apply' | 'tier_2_consulting' | 'retainer' | 'reject'
  - pitch_angle: 'job_application' | 'consulting' | 'retainer'
  - fit_score: 0-100
  - fit_reasoning: short explanation
  - skip_reason: set when qualifies=false

Uses Haiku for cost — at ~500 jobs we want this cheap. The deeper company
research + letter draft uses the bigger models.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from ..db import db
from ..process import log_step
from ..profile import profile_for_prompt
from .claude import complete

QUALIFY_MODEL = "claude-haiku-4-5"

SYSTEM = """You are a hiring-fit screener for a solo AI engineer/founder. Decide whether a posted job
is worth pursuing for this specific operator, and how. You will see the operator's PROFILE first
(base, languages, edges, comp floors, tier-1/tier-2/reject role lists), then a JOB POSTING.

Reply with ONLY a JSON object — no prose, no markdown, no code fences:
{
  "qualifies": boolean,                                 // false if obvious skip
  "realism_tier": "tier_1_apply" | "tier_2_consulting" | "retainer" | "reject",
  "pitch_angle": "job_application" | "consulting" | "retainer",
  "fit_score": integer (0-100),
  "fit_reasoning": string (1-2 sentences, plain English),
  "skip_reason": string                                 // set ONLY when qualifies=false
}

Rules:
1. Match the role TITLE + RESPONSIBILITIES against the operator's tier-1, tier-2, and reject lists.
   - If it falls into REJECT (junior, ML research, MLOps infra, pure DS, on-site outside Spain/Gibraltar, etc.)
     -> qualifies=false, realism_tier="reject".
2. Tier 1 candidate = role description matches forward-deployed / applied / customer engineering /
   solutions / automation / internal-tools / founder's-associate / Base44 / LATAM-Brazilian patterns.
   -> realism_tier="tier_1_apply", pitch_angle="job_application".
3. Tier 2 candidate = role would be a stretch as a hire (founding eng at well-funded YC co, senior FS
   at growth-stage, AI eng at mid-size co), but the company has clear automation pain.
   -> realism_tier="tier_2_consulting", pitch_angle="consulting".
4. If comp clearly < $100k/yr full-time AND role is otherwise a fit -> realism_tier="retainer",
   pitch_angle="retainer" (frame it as small add-on engagement to the AiAppGenius book).
5. fit_score: 80+ = strong tier-1; 60-79 = decent tier-2; 40-59 = retainer-only; <40 = skip.
6. Be skeptical. The cost of a bad pursued lead is wasted recruiter trust; the cost of a missed
   one is small (we see hundreds). Default to skip when ambiguous. Better quiet than spammy."""


def qualify_job(job_id: str, *, outreach_id: str | None = None, log_to_process: bool = True) -> dict[str, Any]:
    """Score one job against the profile. Returns the JSON the model produced."""
    started = time.time()
    job = db().table("jobs").select("*, companies(name, domain, website)").eq("id", job_id).single().execute().data
    company = job.get("companies") or {}

    user_msg = (
        "PROFILE:\n" + profile_for_prompt() + "\n\n"
        "JOB POSTING:\n"
        f"Title: {job['title']}\n"
        f"Company: {company.get('name') or '(unknown)'}\n"
        f"Website: {company.get('website') or company.get('domain') or '(unknown)'}\n"
        f"Location: {job.get('location') or '(not stated)'} | Remote: {job.get('remote')}\n"
        f"Comp range: {_fmt_comp(job.get('comp_min'), job.get('comp_max'), job.get('comp_currency'))}\n"
        f"Employment type: {job.get('employment_type') or '(not stated)'}\n"
        f"Source URL: {job.get('url') or '—'}\n"
        f"Description (truncated):\n{(job.get('description') or '')[:3500]}"
    )

    result = complete(system=SYSTEM, user=user_msg, model=QUALIFY_MODEL, max_tokens=600)
    parsed = _parse_json(result["text"])

    duration_ms = int((time.time() - started) * 1000)

    if log_to_process and outreach_id:
        log_step(
            outreach_id,
            kind="fit_scored",
            title=f"Qualified: {parsed.get('realism_tier', '?')} (fit {parsed.get('fit_score', 0)})",
            summary=(
                f"**Decision:** {'pursue' if parsed.get('qualifies') else 'skip'}\n\n"
                f"**Tier:** {parsed.get('realism_tier', '?')}\n\n"
                f"**Pitch angle:** {parsed.get('pitch_angle', '?')}\n\n"
                f"**Fit score:** {parsed.get('fit_score', 0)}/100\n\n"
                f"**Reasoning:** {parsed.get('fit_reasoning', '—')}"
                + (f"\n\n**Skip reason:** {parsed['skip_reason']}" if not parsed.get('qualifies') else "")
            ),
            inputs={"profile_version": "v1", "title": job['title'], "company": company.get('name')},
            outputs=parsed,
            model=result["model"],
            tokens_used=result["tokens_in"] + result["tokens_out"],
            duration_ms=duration_ms,
            visible_to_recruiter=False,  # internal screening — don't show recruiters our scoring
        )

    return parsed


def _fmt_comp(lo: int | None, hi: int | None, cur: str | None) -> str:
    if not lo and not hi:
        return "(not stated)"
    cur = cur or "USD"
    if lo and hi:
        return f"{cur} {lo:,} – {hi:,}"
    return f"{cur} {(lo or hi):,}"


def _parse_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]+\}", text)
        return json.loads(m.group(0)) if m else {}
