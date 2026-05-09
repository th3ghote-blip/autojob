"""Hacker News — Ask HN: Who is hiring?

The thread is plain text and posters include their contact email directly,
which makes it the highest-signal source for the meta-demo pitch.

Strategy:
 1. Use the HN Algolia search API to find the most recent "Ask HN: Who is
    hiring?" thread (Algolia is HN's official search and is free + clean JSON).
 2. Pull the full thread via /items/<id> (returns nested children).
 3. Each top-level child = one listing. external_id = the comment id.
 4. Parse heuristically — the convention is `COMPANY | TITLE | LOCATION | REMOTE | URL`
    on the first line, contact email anywhere in the body.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import NormalizedJob, RawListing, Source

ALGOLIA_SEARCH = (
    "https://hn.algolia.com/api/v1/search"
    "?query=Ask+HN%3A+Who+is+hiring%3F&tags=story&hitsPerPage=5"
)
ALGOLIA_ITEM = "https://hn.algolia.com/api/v1/items/{id}"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
SALARY_RE = re.compile(
    r"\$\s?(\d{2,3})\s?[kK]\s?(?:[-–to]+\s?\$?(\d{2,3})\s?[kK])?",
)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _fetch_json(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


class HNWhosHiringSource(Source):
    slug = "hn_whoshiring"
    kind = "html"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        # Find latest thread.
        search = _fetch_json(ALGOLIA_SEARCH)
        hits = sorted(search.get("hits", []), key=lambda h: h.get("created_at_i", 0), reverse=True)
        if not hits:
            return
        thread_id = hits[0]["objectID"]
        thread = _fetch_json(ALGOLIA_ITEM.format(id=thread_id))

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
                },
                payload_html=text,
            )

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        body = raw.payload_json.get("text") or ""
        # HN Algolia returns text with HTML entities and <p> tags.
        plain = re.sub(r"<[^>]+>", "\n", body)
        plain = re.sub(r"&#x27;", "'", plain)
        plain = re.sub(r"&quot;", '"', plain)
        plain = re.sub(r"&amp;", "&", plain)
        plain = re.sub(r"&lt;", "<", plain)
        plain = re.sub(r"&gt;", ">", plain)
        plain = plain.strip()
        if not plain:
            return None

        first_line = plain.split("\n", 1)[0].strip()
        company, title, location, remote = self._parse_header(first_line)
        if not company:
            return None

        email_match = EMAIL_RE.search(plain)
        contact_email = email_match.group(0).lower() if email_match else None

        url_match = URL_RE.search(plain)
        company_url = url_match.group(0) if url_match else None
        company_domain = _domain_from_url(company_url) if company_url else None

        comp_min, comp_max = self._parse_salary(plain)

        posted_iso = raw.payload_json.get("created_at")  # already ISO from Algolia

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
    def _parse_header(line: str) -> tuple[str | None, str | None, str | None, bool]:
        # Common shapes: "Company | Role | NYC or Remote (US)"
        # or "Company (YC W22) | Senior Engineer | Remote"
        parts = [p.strip() for p in re.split(r"\s*\|\s*", line) if p.strip()]
        if not parts:
            return None, None, None, False
        company = parts[0]
        title = parts[1] if len(parts) > 1 else None
        location_blob = " | ".join(parts[2:]) if len(parts) > 2 else ""
        remote = bool(re.search(r"\bremote\b", line, re.I))
        location = location_blob or None
        return company, title, location, remote

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
