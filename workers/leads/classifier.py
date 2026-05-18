"""Haiku-powered consulting-buyer classifier.

Given a raw lead (URL + title + excerpt + raw_json hints like tool name
and country), decide whether the source company is a viable consulting
prospect for AiAppGenius's $1-2.5k/mo retainer offer.

Output:
  - classification: 'prospect' | 'consultant_seeking_work' | 'unrelated' | 'unknown'
  - fit_score: 0-100
  - install_size_guess: '10-50' | '50-200' | '200+' | 'unknown'
  - company_name: best-guess
  - reasoning: 1 short sentence

Buyer-fit criteria (what makes a "prospect"):
  - Company is IDENTIFIABLE (name, domain, or strong attribution clues)
  - Runs an automation-relevant stack (call-centre, CRM, ops tool, e-comm,
    or admits AI/ops gap by hiring "Head of AI" / "ops manager" etc.)
  - Decision-maker plausibly reachable (SMB 10-500 seats, not Fortune 50)
  - Budget plausibly $1-2.5k/mo (mid-market SMBs, not solo / not enterprise)

Cost: Haiku at ~$0.0008/call.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..agents.claude import complete

MODEL = "claude-haiku-4-5"

SYSTEM = """You are a B2B lead qualifier for AiAppGenius — a solo AI/automation
consulting practice based in Spain. Offer: $1k-$2.5k/month retainers to SMBs
(10-500 employees) for one of:
  - Custom analytics dashboard on top of an existing ops tool
  - AI workflow / agent embedded in their existing stack
  - Workflow automation glue (no-code/low-code + Claude API)

For each lead I show you, decide whether the SOURCE COMPANY is a viable
consulting prospect:

- "prospect" = the company is identifiable (named or strongly attributable),
  runs an automation-relevant stack OR explicitly admits an AI/automation gap
  (hiring Head of AI / fractional CTO / ops manager / automation lead),
  is SMB-sized (10-500 employees), and a decision-maker is plausibly reachable
  through normal cold-outreach channels.
- "consultant_seeking_work" = an individual freelancer or consulting shop
  pitching services. NOT a buyer.
- "unrelated" = the lead is noise (unrelated topic, a how-to article,
  software vendor itself, no buyer signal).
- "unknown" = looks consulting-relevant but no usable buyer signal
  (anonymous post, no company, no industry, no pain hint).

Reply with ONLY a JSON object — no prose, no markdown, no code fences:
{
  "classification": "prospect" | "consultant_seeking_work" | "unrelated" | "unknown",
  "fit_score": integer 0-100,
  "install_size_guess": "10-50" | "50-200" | "200+" | "unknown",
  "company_name": string or null (best-guess; null if not extractable),
  "signal_kind": "hiring" | "customer_mention" | "support_request" | "job_post" | "review" | "unknown",
  "reasoning": short string (one sentence, plain English)
}

Scoring guide:
- 80-100: explicit company + automation-relevant stack + clear pain or buying signal
          (e.g. company named, hiring Head of AI, hiring ops automation manager,
           review explicitly mentions tool gaps)
- 60-79: identifiable company + relevant stack, no urgent pain signal
- 40-59: anonymous but clearly a real install / ops team
- 20-39: weak signal, hard to identify
- 0-19: noise, individual consultant, vendor-themselves, or unrelated

Be skeptical. Default to "unknown" or low score when ambiguous. SMB target =
10-500 employees. Fortune 500 / mega-corp = score lower (they have in-house
teams and procurement makes them unreachable). Solo freelancers offering
services = NOT a prospect."""


def classify_lead(*, source_url: str, title: str | None, excerpt: str | None) -> dict[str, Any]:
    user = (
        f"URL: {source_url}\n"
        f"TITLE: {title or '(none)'}\n"
        f"EXCERPT: {(excerpt or '(none)')[:1500]}\n"
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

    return {
        "classification": parsed.get("classification") or "unknown",
        "fit_score": int(parsed.get("fit_score") or 0),
        "install_size_guess": parsed.get("install_size_guess") or "unknown",
        "company_name": parsed.get("company_name"),
        "signal_kind": parsed.get("signal_kind") or "unknown",
        "reasoning": (parsed.get("reasoning") or "")[:500],
    }
