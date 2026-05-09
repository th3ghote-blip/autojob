"""Lever postings API (multi-company).

Public endpoint per company:
  https://api.lever.co/v0/postings/{slug}?mode=json

Configure companies in sources.config_json.companies, e.g.:
  {"companies": ["mistral", "perplexity", "rampnetwork"]}
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import NormalizedJob, RawListing, Source

API = "https://api.lever.co/v0/postings/{slug}?mode=json"
AI_KEYWORDS = ("ai", "ml ", "machine learning", "llm", "applied", "research engineer")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get(url: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


class LeverSource(Source):
    slug = "lever"
    kind = "ats"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        for company_slug in config.get("companies", []):
            try:
                items = _get(API.format(slug=company_slug))
            except Exception as e:  # noqa: BLE001
                yield RawListing(
                    external_id=f"_error_{company_slug}",
                    payload_json={"_error": str(e), "company_slug": company_slug},
                )
                continue
            for item in items:
                yield RawListing(
                    external_id=f"{company_slug}:{item['id']}",
                    payload_json={"company_slug": company_slug, **item},
                )

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        item = raw.payload_json
        if "_error" in item:
            return None
        text = (item.get("text") or "").strip()
        descr_html = " ".join(
            (lst.get("content") or "")
            for lst in (item.get("lists") or [])
        ) + (item.get("descriptionPlain") or "")
        if not text:
            return None
        haystack = (text + " " + descr_html).lower()
        if not any(k in haystack for k in AI_KEYWORDS):
            return None

        cats = item.get("categories") or {}
        location = cats.get("location")
        commitment = (cats.get("commitment") or "").lower()
        employment = "contract" if "contract" in commitment else "full_time"

        return NormalizedJob(
            external_id=raw.external_id,
            title=text,
            company_name=_humanize(item.get("company_slug")),
            description=re.sub(r"<[^>]+>", " ", descr_html)[:8000],
            location=location,
            remote=("remote" in (location or "").lower()),
            employment_type=employment,
            url=item.get("hostedUrl"),
            posted_at=_iso_from_ms(item.get("createdAt")),
        )


def _humanize(slug: str | None) -> str:
    if not slug:
        return "Unknown"
    return slug.replace("-", " ").replace("_", " ").title()


def _iso_from_ms(ms: int | None) -> str | None:
    if not ms:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


source = LeverSource()
