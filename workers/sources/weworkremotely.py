"""WeWorkRemotely — public RSS feed.

https://weworkremotely.com/categories/remote-programming-jobs.rss

Returns an RSS XML feed of recent listings. We parse the <item> elements.
Each item has <title>, <description>, <link>, <pubDate>, <region>, <company_name>.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from ..profile import hard_reject
from .base import NormalizedJob, RawListing, Source

FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/all-other-remote-jobs.rss",
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get(url: str) -> str:
    with httpx.Client(timeout=20, headers={"User-Agent": "autojob/1.0"}) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


class WeWorkRemotelySource(Source):
    slug = "weworkremotely"
    kind = "rss"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        feeds = config.get("feeds") or FEEDS
        for feed in feeds:
            try:
                xml = _get(feed)
            except Exception as e:  # noqa: BLE001
                yield RawListing(external_id=f"_error_{feed}", payload_json={"_error": str(e), "feed": feed})
                continue
            soup = BeautifulSoup(xml, "lxml-xml")
            for item in soup.find_all("item"):
                link_tag = item.find("link")
                link = link_tag.get_text(strip=True) if link_tag else ""
                m = re.search(r"/remote-jobs/([\w\-]+)", link)
                if not m:
                    continue
                external_id = m.group(1)
                title_tag = item.find("title")
                desc_tag = item.find("description")
                pub_tag = item.find("pubDate")
                region_tag = item.find("region")
                yield RawListing(
                    external_id=external_id,
                    payload_json={
                        "title_raw": title_tag.get_text(strip=True) if title_tag else "",
                        "description_html": desc_tag.get_text(strip=True) if desc_tag else "",
                        "link": link,
                        "pub_date": pub_tag.get_text(strip=True) if pub_tag else None,
                        "region": region_tag.get_text(strip=True) if region_tag else None,
                    },
                )

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        item = raw.payload_json
        if "_error" in item:
            return None
        # WWR title format: "Company Name: Job Title".
        title_raw = (item.get("title_raw") or "").strip()
        if not title_raw:
            return None
        if ":" in title_raw:
            company, title = title_raw.split(":", 1)
            company, title = company.strip(), title.strip()
        else:
            company, title = "Unknown", title_raw

        desc_html = item.get("description_html") or ""
        desc = re.sub(r"<[^>]+>", " ", desc_html)
        desc = re.sub(r"\s+", " ", desc).strip()

        # Filter to AI/automation/applied roles — WWR posts a LOT of generic
        # software jobs, no point ingesting them all.
        relevance = re.search(
            r"\b(AI|ML|machine learning|LLM|claude|gpt|founding|forward deployed|"
            r"applied|automation|solutions engineer|customer engineer|"
            r"implementation engineer|workflow|agent)\b",
            title + " " + desc,
            re.I,
        )
        if not relevance:
            return None

        if hard_reject(title, desc, item.get("region")):
            return None

        return NormalizedJob(
            external_id=raw.external_id,
            title=title[:120],
            company_name=company[:80],
            description=desc[:8000],
            location=item.get("region"),
            remote=True,
            employment_type="full_time",
            url=item.get("link"),
            posted_at=item.get("pub_date"),
        )


source = WeWorkRemotelySource()
