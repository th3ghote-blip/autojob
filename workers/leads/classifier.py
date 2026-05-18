"""Haiku-powered lead classifier.

Given a raw lead (URL, title, excerpt), decide:
  - classification: 'prospect' | 'consultant_seeking_work' | 'unrelated' | 'unknown'
  - fit_score: 0-100 (how strongly it indicates an active Vicidial install
                     at a company that could buy our analytics dashboard)
  - install_size_guess: '10-50' | '50-200' | '200+' | 'unknown'
  - company_name: best guess
  - reasoning: 1 short sentence

Cost: Haiku at ~$0.0008/call. 500 leads ≈ $0.40.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..agents.claude import complete

MODEL = "claude-haiku-4-5"

SYSTEM = """You are a B2B lead qualifier for an analytics product targeted at
companies running Vicidial (open-source call-centre software).

For each lead I show you (a URL + title + excerpt from a forum post, search
result, or social post), decide whether the source COMPANY is a viable prospect:

- "prospect" = the company actively runs Vicidial in production (10+ seats),
  and there is a name / domain / decision-maker hint somewhere in the text.
- "consultant_seeking_work" = an individual freelancer or consulting shop
  pitching their Vicidial services. NOT a buyer.
- "unrelated" = mentions Vicidial only in passing (job board listing the
  word as a skill, a how-to article, etc).
- "unknown" = looks Vicidial-related but no usable buyer signal.

Reply with ONLY a JSON object — no prose, no markdown, no code fences:
{
  "classification": "prospect" | "consultant_seeking_work" | "unrelated" | "unknown",
  "fit_score": integer 0-100,
  "install_size_guess": "10-50" | "50-200" | "200+" | "unknown",
  "company_name": string or null (best-guess; null if not extractable),
  "signal_kind": "hiring" | "customer_mention" | "forum_post" | "support_request" | "job_post" | "unknown",
  "reasoning": short string (one sentence, plain English)
}

Scoring guide:
- 80-100: explicit company name + running Vicidial at scale + buying-signal (frustration, hiring, upgrade)
- 60-79: company identifiable, install confirmed, no urgent buying signal
- 40-59: anonymous forum post but clearly an admin at a real install
- 20-39: weak signal, hard to identify company
- 0-19: noise, individual consultant, or unrelated

Be skeptical. Default to "unknown" or low score when ambiguous. Companies
hiring "Vicidial admin" full-time = strong signal. Solo consultants
offering "Vicidial setup services" = NOT a prospect."""


def classify_lead(*, source_url: str, title: str | None, excerpt: str | None) -> dict[str, Any]:
    user = (
        f"URL: {source_url}\n"
        f"TITLE: {title or '(none)'}\n"
        f"EXCERPT: {(excerpt or '(none)')[:1200]}\n"
    )
    try:
        res = complete(system=SYSTEM, user=user, model=MODEL, max_tokens=400)
    except Exception as e:
        return {
            "classification": "unknown",
            "fit_score": 0,
            "install_size_guess": "unknown",
            "company_name": None,
            "signal_kind": "unknown",
            "reasoning": f"classifier_error: {e}",
        }

    text = res["text"].strip()
    # Strip optional code fences just in case.
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {
            "classification": "unknown",
            "fit_score": 0,
            "install_size_guess": "unknown",
            "company_name": None,
            "signal_kind": "unknown",
            "reasoning": f"parse_error: {text[:200]}",
        }

    # Defensive defaults.
    return {
        "classification": parsed.get("classification") or "unknown",
        "fit_score": int(parsed.get("fit_score") or 0),
        "install_size_guess": parsed.get("install_size_guess") or "unknown",
        "company_name": parsed.get("company_name"),
        "signal_kind": parsed.get("signal_kind") or "unknown",
        "reasoning": (parsed.get("reasoning") or "")[:500],
    }
