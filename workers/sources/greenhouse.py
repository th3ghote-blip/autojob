"""Greenhouse Job Boards API (multi-company).

Public endpoint per company board:
  https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

Configure target companies in sources.config_json.companies, e.g.:
  {"companies": ["openai", "anthropic", "scaleai", "coheretech"]}

Each company is fetched once per run; rate-limit-friendly because
Greenhouse permits unauthenticated polling at low frequencies.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import NormalizedJob, RawListing, Source

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
AI_KEYWORDS = ("ai", "ml ", "machine learning", "llm", "applied ai", "research engineer", "ml engineer")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


class GreenhouseSource(Source):
    slug = "greenhouse"
    kind = "ats"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        for company_slug in config.get("companies", []):
            try:
                data = _get(API.format(slug=company_slug))
            except Exception as e:  # noqa: BLE001
                # one bad company shouldn't kill the whole run
                yield RawListing(
                    external_id=f"_error_{company_slug}",
                    payload_json={"_error": str(e), "company_slug": company_slug},
                )
                continue
            for job in data.get("jobs", []):
                yield RawListing(
                    external_id=f"{company_slug}:{job['id']}",
                    payload_json={"company_slug": company_slug, **job},
                )

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        item = raw.payload_json
        if "_error" in item:
            return None
        title = (item.get("title") or "").strip()
        if not title:
            return None
        # Filter to AI-related roles only.
        haystack = (title + " " + (item.get("content") or "")).lower()
        if not any(k in haystack for k in AI_KEYWORDS):
            return None

        company_slug = item.get("company_slug")
        company_name = (item.get("company") or {}).get("name") or _humanize(company_slug)
        location = (item.get("location") or {}).get("name")
        # Greenhouse content is HTML — strip for storage; full HTML lives in job_raw.
        description = re.sub(r"<[^>]+>", " ", item.get("content") or "").strip()

        return NormalizedJob(
            external_id=raw.external_id,
            title=title,
            company_name=company_name,
            company_domain=None,  # let research step resolve
            description=description[:8000],
            location=location,
            remote=("remote" in (location or "").lower()),
            employment_type="full_time",
            url=item.get("absolute_url"),
            posted_at=item.get("updated_at"),
        )


def _humanize(slug: str | None) -> str:
    if not slug:
        return "Unknown"
    return slug.replace("-", " ").replace("_", " ").title()


source = GreenhouseSource()
