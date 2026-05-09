"""ai-jobs.net — static-rendered listings page.

Uses a simple HTTP+BeautifulSoup pull. The site exposes structured
listing cards on /jobs and the full posting on /job/<id>-<slug>.

We pull the index page only — full descriptions can be enriched
on-demand later by fetch_one() during the research stage.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import NormalizedJob, RawListing, Source

INDEX = "https://ai-jobs.net/"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get(url: str) -> str:
    with httpx.Client(
        timeout=30, follow_redirects=True,
        headers={"User-Agent": "autojob/1.0 (+https://github.com/th3ghote-blip/autojob)"},
    ) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


class AiJobsSource(Source):
    slug = "ai_jobs"
    kind = "html"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        base = config.get("base", "https://ai-jobs.net").rstrip("/")
        html = _get(base + "/")
        soup = BeautifulSoup(html, "lxml")
        for li in soup.select("li.list-group-item"):
            link = li.select_one("a[href*='/job/']")
            if not link:
                continue
            href = link.get("href", "")
            if not href:
                continue
            full_url = href if href.startswith("http") else base + href
            external_id = re.sub(r"^.*/job/", "", href).split("?", 1)[0]
            title = (link.get_text(strip=True) or "").strip()
            company = ""
            company_el = li.select_one("h4, h5, .text-muted")
            if company_el:
                company = company_el.get_text(strip=True)
            location = ""
            loc_el = li.select_one(".badge-location, [class*='location']")
            if loc_el:
                location = loc_el.get_text(strip=True)
            yield RawListing(
                external_id=external_id,
                payload_json={
                    "url": full_url,
                    "title": title,
                    "company": company,
                    "location": location,
                },
                payload_html=str(li),
            )

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        item = raw.payload_json
        title = (item.get("title") or "").strip()
        company = (item.get("company") or "").strip()
        if not title or not company:
            return None
        location = item.get("location") or None
        return NormalizedJob(
            external_id=raw.external_id,
            title=title,
            company_name=company,
            description=None,  # enrich later from /job/<id> page
            location=location,
            remote=("remote" in (location or "").lower()),
            employment_type="full_time",
            url=item.get("url"),
        )


source = AiJobsSource()
