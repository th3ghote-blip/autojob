"""Ashby Job Board API (multi-company).

Public endpoint per company:
  https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true

Configure companies in sources.config_json.companies.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..profile import hard_reject
from .base import NormalizedJob, RawListing, Source

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


class AshbySource(Source):
    slug = "ashby"
    kind = "ats"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        for company_slug in config.get("companies", []):
            try:
                data = _get(API.format(slug=company_slug))
            except Exception as e:  # noqa: BLE001
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
        if hard_reject(title, item.get("descriptionPlain"), item.get("locationName")):
            return None

        comp = item.get("compensation") or {}
        comp_min = comp_max = None
        for tier in (comp.get("compensationTierSummary") or []):
            if tier.get("currencyCode") == "USD":
                comp_min = tier.get("minValue")
                comp_max = tier.get("maxValue")
                break

        return NormalizedJob(
            external_id=raw.external_id,
            title=title,
            company_name=_humanize(item.get("company_slug")),
            description=(item.get("descriptionPlain") or "")[:8000],
            comp_min=int(comp_min) if comp_min else None,
            comp_max=int(comp_max) if comp_max else None,
            location=item.get("locationName"),
            remote=bool(item.get("isRemote")),
            employment_type=(item.get("employmentType") or "full_time").lower().replace(" ", "_"),
            url=item.get("jobUrl"),
            posted_at=item.get("publishedAt"),
        )


def _humanize(slug: str | None) -> str:
    if not slug:
        return "Unknown"
    return slug.replace("-", " ").replace("_", " ").title()


source = AshbySource()
