"""Jobicy — public job feed (RSS-like with JSON option).

https://jobicy.com/api/v3/remote-jobs?count=50&geo=&industry=&tag=AI

Returns a JSON envelope: {"jobs": [...]}. Each job has jobTitle, companyName,
jobDescription, jobGeo, jobIndustry, jobType, annualSalaryMin/Max, etc.
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import quote

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..profile import hard_reject
from .base import NormalizedJob, RawListing, Source

API = "https://jobicy.com/api/v3/remote-jobs?count=50&tag={tag}"

DEFAULT_TAGS = ["AI", "machine-learning", "engineering", "automation"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=20, headers={"User-Agent": "autojob/1.0"}) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


class JobicySource(Source):
    slug = "jobicy"
    kind = "api"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        tags = config.get("tags") or DEFAULT_TAGS
        seen: set[str] = set()
        for tag in tags:
            try:
                data = _get(API.format(tag=quote(tag)))
            except Exception as e:  # noqa: BLE001
                yield RawListing(external_id=f"_error_{tag}", payload_json={"_error": str(e), "tag": tag})
                continue
            for j in data.get("jobs", []):
                jid = str(j.get("id"))
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                yield RawListing(external_id=jid, payload_json=j)

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        j = raw.payload_json
        if "_error" in j:
            return None
        title = (j.get("jobTitle") or "").strip()
        company = (j.get("companyName") or "").strip()
        if not title or not company:
            return None
        desc_html = j.get("jobDescription") or ""
        desc = re.sub(r"<[^>]+>", " ", desc_html)
        desc = re.sub(r"\s+", " ", desc).strip()
        location = (j.get("jobGeo") or "") or None

        if hard_reject(title, desc, location):
            return None

        comp_min = j.get("annualSalaryMin")
        comp_max = j.get("annualSalaryMax")
        try:
            comp_min = int(comp_min) if comp_min else None
            comp_max = int(comp_max) if comp_max else None
        except (TypeError, ValueError):
            comp_min = comp_max = None

        return NormalizedJob(
            external_id=raw.external_id,
            title=title[:120],
            company_name=company[:80],
            description=desc[:8000],
            comp_min=comp_min,
            comp_max=comp_max,
            comp_currency=(j.get("salaryCurrency") or "USD"),
            location=location,
            remote=True,
            employment_type=(j.get("jobType") or "full_time").replace("-", "_").lower(),
            url=j.get("url"),
            posted_at=j.get("pubDate"),
        )


source = JobicySource()
