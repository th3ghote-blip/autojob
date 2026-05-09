"""Hacker News — Ask HN: Who is hiring?

The thread is plain text and posters include their contact email directly,
which makes it the highest-signal source for the meta-demo pitch.

Strategy:
 1. Use the HN Algolia search API to find recent "Ask HN: Who is hiring?"
    threads. config.json.months controls how many recent monthly threads to
    walk (default 6 — gives us hundreds of historical postings on first run).
 2. For each thread, pull /items/<id> for nested children.
 3. Each top-level child = one listing. external_id = the comment id.
 4. Parse heuristically — the convention is `COMPANY | TITLE | LOCATION | REMOTE | URL`
    on the first line, contact email anywhere in the body.
 5. Hard-reject obvious junk via the profile pre-filter; the LLM qualifier
    sees the rest in pipeline.py.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..profile import hard_reject
from .base import NormalizedJob, RawListing, Source

# Use /search_by_date so threads come back chronologically — /search ranks by
# relevance, which surfaces 2018-era all-time-popular threads first. The
# numericFilters floor narrows to the last ~12 months so we never walk old data.
import time as _time
_ONE_YEAR_AGO = int(_time.time()) - 60 * 60 * 24 * 365
ALGOLIA_SEARCH = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?query=Ask+HN%3A+Who+is+hiring%3F"
    "&tags=story"
    "&hitsPerPage=24"
    f"&numericFilters=created_at_i%3E{_ONE_YEAR_AGO}"
)
ALGOLIA_ITEM = "https://hn.algolia.com/api/v1/items/{id}"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
SALARY_RE = re.compile(r"\$\s?(\d{2,3})\s?[kK]\s?(?:[-–to]+\s?\$?(\d{2,3})\s?[kK])?")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _fetch_json(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def _is_who_is_hiring(title: str | None) -> bool:
    if not title:
        return False
    t = title.lower()
    return "who is hiring" in t or "who's hiring" in t


class HNWhosHiringSource(Source):
    slug = "hn_whoshiring"
    kind = "html"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        months_back = int(config.get("months", 6))

        search = _fetch_json(ALGOLIA_SEARCH)
        threads = sorted(
            [h for h in search.get("hits", []) if _is_who_is_hiring(h.get("title"))],
            key=lambda h: h.get("created_at_i", 0),
            reverse=True,
        )[:months_back]

        for hit in threads:
            thread_id = hit["objectID"]
            try:
                thread = _fetch_json(ALGOLIA_ITEM.format(id=thread_id))
            except Exception:  # noqa: BLE001
                continue
            for child in thread.get("children", []):
                text = (child.get("text") or "").strip()
                if not text:
                    continue
                yield RawListing(
                    external_id=str(child["id"]),
                    payload_json={
                        "id": child["id"],
                        "author": child.get("author"),
                        "created_at": child.get("created_at"),
                        "text": text,
                        "thread_id": thread_id,
                        "thread_title": hit.get("title"),
                    },
                    payload_html=text,
                )

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        body = raw.payload_json.get("text") or ""
        plain = self._strip_html(body)
        if not plain:
            return None

        first_line = plain.split("\n", 1)[0].strip()
        company, title, location, remote = self._parse_header(first_line)
        if not company:
            return None

        # Sanity cap on company name (parser sometimes captures whole post).
        if len(company) > 80:
            company = company[:80].rsplit(" ", 1)[0] + "…"

        # Cheap pre-filter — skip junk before the LLM qualifier sees it.
        full_title = title or first_line[:80]
        if hard_reject(full_title, plain, location):
            return None

        email_match = EMAIL_RE.search(plain)
        contact_email = email_match.group(0).lower() if email_match else None

        url_match = URL_RE.search(plain)
        company_url = url_match.group(0) if url_match else None
        company_domain = _domain_from_url(company_url) if company_url else None

        comp_min, comp_max = self._parse_salary(plain)
        posted_iso = raw.payload_json.get("created_at")

        return NormalizedJob(
            external_id=raw.external_id,
            title=title or "(see post)",
            company_name=company,
            company_domain=company_domain,
            company_website=company_url,
            description=plain[:8000],
            comp_min=comp_min,
            comp_max=comp_max,
            location=location,
            remote=remote,
            employment_type=_guess_type(plain),
            contact_email=contact_email,
            url=f"https://news.ycombinator.com/item?id={raw.external_id}",
            posted_at=posted_iso,
        )

    @staticmethod
    def _strip_html(body: str) -> str:
        plain = re.sub(r"<[^>]+>", "\n", body)
        plain = (plain
                 .replace("&#x27;", "'").replace("&quot;", '"')
                 .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
        return plain.strip()

    @staticmethod
    def _parse_header(line: str) -> tuple[str | None, str | None, str | None, bool]:
        parts = [p.strip() for p in re.split(r"\s*\|\s*", line) if p.strip()]
        if not parts:
            return None, None, None, False
        company = parts[0]
        title = parts[1] if len(parts) > 1 else None
        location_blob = " | ".join(parts[2:]) if len(parts) > 2 else ""
        remote = bool(re.search(r"\bremote\b", line, re.I))
        return company, title, location_blob or None, remote

    @staticmethod
    def _parse_salary(text: str) -> tuple[int | None, int | None]:
        m = SALARY_RE.search(text)
        if not m:
            return None, None
        lo = int(m.group(1)) * 1000
        hi = int(m.group(2)) * 1000 if m.group(2) else None
        return lo, hi


def _domain_from_url(url: str) -> str | None:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url, re.I)
    return m.group(1).lower() if m else None


def _guess_type(text: str) -> str:
    t = text.lower()
    if "contract" in t or "consult" in t:
        return "contract"
    if "intern" in t:
        return "internship"
    return "full_time"


source = HNWhosHiringSource()
