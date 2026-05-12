"""LinkedIn — public (guest) jobs search, no login required.

Uses the unauthenticated `/jobs-guest/jobs/api/seeMoreJobPostings/search`
endpoint which returns HTML chunks of job cards visible to logged-out
visitors. Lower volume than authenticated search but zero ban risk on
the operator's personal LinkedIn account.

config_json:
  {
    "queries": [
      {"keywords": "AI engineer", "location": "European Union", "f_TPR": "r604800"},
      {"keywords": "Forward Deployed Engineer", "location": "Worldwide", "f_TPR": "r604800"},
      ...
    ],
    "pages_per_query": 2     # 25 jobs/page
  }

`f_TPR=r604800` = posted in the last 7 days (LinkedIn's own filter).
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterable
from urllib.parse import quote, urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from ..profile import hard_reject
from .base import NormalizedJob, RawListing, Source

GUEST_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

# Realistic browser headers — LinkedIn challenges generic clients.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.linkedin.com/jobs/",
}

DEFAULT_QUERIES = [
    # English-language remote / EU bias matching the operator's geography.
    {"keywords": "AI engineer", "location": "European Union", "f_TPR": "r604800"},
    {"keywords": "Forward Deployed Engineer", "location": "Worldwide", "f_TPR": "r604800"},
    {"keywords": "Applied AI engineer", "location": "Worldwide", "f_TPR": "r604800"},
    {"keywords": "Solutions Engineer AI", "location": "European Union", "f_TPR": "r604800"},
    {"keywords": "Founding engineer", "location": "European Union", "f_TPR": "r604800"},
    {"keywords": "Automation engineer", "location": "European Union", "f_TPR": "r604800"},
]


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
def _fetch_page(query: dict[str, Any], start: int) -> str:
    params = {
        "keywords": query.get("keywords", ""),
        "location": query.get("location", "Worldwide"),
        "f_TPR": query.get("f_TPR", "r604800"),
        "start": str(start),
    }
    url = (
        GUEST_SEARCH
        + "?"
        + "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    )
    with httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True) as c:
        r = c.get(url)
        if r.status_code == 429:
            # Backoff signal — caller will retry the wider loop.
            raise RuntimeError("linkedin_rate_limited")
        if r.status_code >= 400:
            # 404/451 sometimes returned mid-walk; treat as end-of-results.
            return ""
        return r.text


class LinkedinSource(Source):
    slug = "linkedin"
    kind = "html"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        queries = config.get("queries") or DEFAULT_QUERIES
        pages_per_query = int(config.get("pages_per_query", 2))
        seen: set[str] = set()

        for query in queries:
            for page in range(pages_per_query):
                try:
                    html = _fetch_page(query, start=page * 25)
                except Exception as e:  # noqa: BLE001
                    yield RawListing(
                        external_id=f"_error_{query.get('keywords','?')}_{page}",
                        payload_json={"_error": str(e), "query": query},
                    )
                    break

                if not html.strip():
                    break

                soup = BeautifulSoup(html, "lxml")
                cards = soup.select("li > div[data-entity-urn], li > div.base-card, li.jobs-search__results-list-item")
                if not cards:
                    # Fallback: find any <a href="/jobs/view/...">
                    cards = soup.select("a[href*='/jobs/view/']")
                    cards = [c for c in cards if c.find_parent("li") or True]

                for card in cards:
                    # Try to find the job ID + apply link.
                    link = card.select_one("a[href*='/jobs/view/']") if hasattr(card, "select_one") else card
                    href = (link.get("href") if link else "") or ""
                    m = re.search(r"/jobs/view/(\d+)", href)
                    if not m:
                        continue
                    job_id = m.group(1)
                    if job_id in seen:
                        continue
                    seen.add(job_id)

                    title_el = card.select_one("h3, .base-search-card__title")
                    company_el = card.select_one("h4, .base-search-card__subtitle, a.hidden-nested-link")
                    loc_el = card.select_one(".job-search-card__location, span.job-search-card__location")
                    time_el = card.select_one("time")

                    title = (title_el.get_text(strip=True) if title_el else "").strip()
                    company = (company_el.get_text(strip=True) if company_el else "").strip()
                    location = (loc_el.get_text(strip=True) if loc_el else "").strip()
                    posted = time_el.get("datetime") if time_el else None

                    yield RawListing(
                        external_id=job_id,
                        payload_json={
                            "id": job_id,
                            "title": title,
                            "company": company,
                            "location": location,
                            "posted_at": posted,
                            "url": f"https://www.linkedin.com/jobs/view/{job_id}",
                            "query": query,
                        },
                    )
                time.sleep(1.2)  # gentle pacing

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        item = raw.payload_json
        if "_error" in item:
            return None
        title = (item.get("title") or "").strip()
        company = (item.get("company") or "").strip()
        if not title or not company:
            return None
        location = item.get("location") or None
        if hard_reject(title, None, location):
            return None
        return NormalizedJob(
            external_id=raw.external_id,
            title=title[:120],
            company_name=company[:80],
            company_domain=None,  # research step / GitHub finder will resolve
            description=None,
            location=location,
            remote=bool(location and re.search(r"\bremote\b|\banywhere\b", location, re.I)),
            employment_type="full_time",
            url=item.get("url"),
            posted_at=item.get("posted_at"),
        )


source = LinkedinSource()
