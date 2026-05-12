"""Remotive — public JSON API.

https://remotive.com/api/remote-jobs?category=software-dev&search=<term>

No auth required, returns JSON with title, company, salary, description,
url, candidate_required_location, etc. Cloud-IP friendly.
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import quote

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..profile import hard_reject
from .base import NormalizedJob, RawListing, Source

API = "https://remotive.com/api/remote-jobs?category=software-dev&search={q}&limit=100"

DEFAULT_QUERIES = ["AI engineer", "applied AI", "founding engineer", "solutions engineer", "automation engineer", "forward deployed"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=20, headers={"User-Agent": "autojob/1.0"}) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


class RemotiveSource(Source):
    slug = "remotive"
    kind = "api"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        queries = config.get("queries") or DEFAULT_QUERIES
        seen: set[str] = set()
        for q in queries:
            try:
                data = _get(API.format(q=quote(q)))
            except Exception as e:  # noqa: BLE001
                yield RawListing(external_id=f"_error_{q}", payload_json={"_error": str(e), "query": q})
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
        title = (j.get("title") or "").strip()
        company = (j.get("company_name") or "").strip()
        if not title or not company:
            return None
        location = j.get("candidate_required_location") or None
        desc = j.get("description") or ""
        desc = re.sub(r"<[^>]+>", " ", desc)
        if hard_reject(title, desc, location):
            return None
        salary = j.get("salary") or ""
        comp_min = comp_max = None
        m = re.search(r"\$?\s?(\d{2,3})[,Kk]?\s?(?:[-–]\s?\$?\s?(\d{2,3})[,Kk]?)?", salary)
        if m:
            comp_min = int(m.group(1)) * 1000
            comp_max = int(m.group(2)) * 1000 if m.group(2) else None
        return NormalizedJob(
            external_id=raw.external_id,
            title=title[:120],
            company_name=company[:80],
            description=desc[:8000].strip(),
            comp_min=comp_min,
            comp_max=comp_max,
            location=location,
            remote=True,  # Remotive is remote-only
            employment_type=(j.get("job_type") or "full_time").replace("-", "_"),
            url=j.get("url"),
            posted_at=j.get("publication_date"),
        )


source = RemotiveSource()
