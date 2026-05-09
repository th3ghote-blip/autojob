"""RemoteOK — public JSON feed.

Cleanest integration in the whole pipeline. Single GET, filter by tags.
Endpoint: https://remoteok.com/api  (first item is metadata; skip it)
"""
from __future__ import annotations

from typing import Any, Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import NormalizedJob, RawListing, Source


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _fetch(url: str) -> list[dict[str, Any]]:
    with httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "autojob/1.0 (+https://github.com/th3ghote-blip/autojob)"},
    ) as c:
        r = c.get(url)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []


class RemoteOKSource(Source):
    slug = "remoteok"
    kind = "api"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        feed_url = config.get("feed", "https://remoteok.com/api")
        wanted_tags = {t.lower() for t in config.get("tags", ["ai", "ml"])}
        items = _fetch(feed_url)
        for item in items:
            # First item is feed metadata.
            if "id" not in item:
                continue
            tags = {str(t).lower() for t in item.get("tags", [])}
            if wanted_tags and not (tags & wanted_tags):
                continue
            yield RawListing(
                external_id=str(item["id"]),
                payload_json=item,
            )

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        item = raw.payload_json
        company = (item.get("company") or "").strip()
        position = (item.get("position") or "").strip()
        if not company or not position:
            return None

        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")

        return NormalizedJob(
            external_id=raw.external_id,
            title=position,
            company_name=company,
            company_domain=_domain(item.get("company_logo") or item.get("apply_url") or ""),
            company_website=item.get("apply_url"),
            description=item.get("description"),
            comp_min=int(salary_min) if salary_min else None,
            comp_max=int(salary_max) if salary_max else None,
            location=item.get("location"),
            remote=True,
            employment_type="full_time",
            url=item.get("url") or f"https://remoteok.com/remote-jobs/{raw.external_id}",
            posted_at=item.get("date"),
        )


def _domain(url: str) -> str | None:
    import re
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "", re.I)
    return m.group(1).lower() if m else None


source = RemoteOKSource()
