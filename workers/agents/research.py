"""Company research agent.

For a given company we:
  1. Fetch the company website's homepage HTML (best-effort).
  2. Ask Claude to extract: industry, size hint, what they sell, signals
     of automation/AI investment, recent news mentions visible on-page.
  3. Score fit (0-100) for the user's offer (custom AI software / consulting).
  4. Persist research_json + research_summary + fit_score on the company row.
  5. Append a process_steps row (visible to recruiter) summarizing what we found.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..db import db
from ..process import log_step
from .claude import complete

SYSTEM = """You are a research analyst preparing context for a personalised outreach.
You will receive raw text scraped from a company's homepage.
Reply with ONLY a JSON object matching this schema (no prose, no markdown):
{
  "industry": string,
  "what_they_do": string,        // 1-2 sentences
  "size_hint": string,            // e.g. "~50 people", "Series B", "public"
  "ai_investment_signals": string[], // 0-5 short bullets
  "automation_pain_signals": string[], // 0-5 short bullets
  "recent_news": string[],        // 0-3 short bullets
  "fit_score": integer,           // 0-100, how well they fit a custom AI software / consulting pitch
  "fit_reasoning": string         // 1-2 sentences justifying the score
}"""


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
def _fetch_homepage(website: str) -> str:
    with httpx.Client(
        timeout=20, follow_redirects=True,
        headers={"User-Agent": "autojob/1.0"},
    ) as c:
        r = c.get(website)
        r.raise_for_status()
        text = re.sub(r"<script[\s\S]*?</script>", " ", r.text)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:8000]


def research_company(company_id: str, *, outreach_id: str | None = None) -> dict[str, Any]:
    started = time.time()
    company = db().table("companies").select("*").eq("id", company_id).single().execute().data
    website = company.get("website") or company.get("domain")
    if website and not website.startswith("http"):
        website = "https://" + website

    homepage_text = ""
    fetch_error = None
    if website:
        try:
            homepage_text = _fetch_homepage(website)
        except Exception as e:  # noqa: BLE001
            fetch_error = str(e)

    user_msg = (
        f"Company name: {company['name']}\n"
        f"Website: {website or '(none)'}\n\n"
        f"Homepage text (truncated):\n{homepage_text or '(unavailable)'}"
    )
    result = complete(system=SYSTEM, user=user_msg)
    try:
        parsed = json.loads(result["text"])
    except Exception:
        # If Claude wrapped it in code fences, try to recover.
        m = re.search(r"\{[\s\S]+\}", result["text"])
        parsed = json.loads(m.group(0)) if m else {}

    fit = int(parsed.get("fit_score") or 0)
    summary = parsed.get("what_they_do") or ""

    db().table("companies").update({
        "research_json": parsed,
        "research_summary": summary,
        "fit_score": fit,
        "last_researched_at": "now()",
    }).eq("id", company_id).execute()

    if outreach_id:
        log_step(
            outreach_id,
            kind="company_researched",
            title=f"Researched {company['name']}",
            summary=(
                f"**What they do:** {parsed.get('what_they_do', '—')}\n\n"
                f"**Industry:** {parsed.get('industry', '—')}\n\n"
                f"**Size:** {parsed.get('size_hint', '—')}\n\n"
                f"**Fit score:** {fit}/100 — {parsed.get('fit_reasoning', '')}"
            ),
            inputs={"website": website, "homepage_chars": len(homepage_text), "fetch_error": fetch_error},
            outputs=parsed,
            model=result["model"],
            tokens_used=result["tokens_in"] + result["tokens_out"],
            duration_ms=int((time.time() - started) * 1000),
        )

    return parsed
