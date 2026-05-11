"""Hacker News — Ask HN: Freelancer? Seeking freelancer?

Monthly thread companion to "Who is hiring". Posters use one of two prefixes:
  - `SEEKING FREELANCER` — companies hiring contractors  ← we want these
  - `SEEKING WORK`       — freelancers offering services  ← ignore

Same Algolia API + thread-walking strategy as hn_whoshiring. Default pitch
angle for resulting outreach is `consulting` since these posters have
already self-identified as contract buyers.
"""
from __future__ import annotations

import re
import time as _time
from typing import Any, Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..profile import hard_reject
from .base import NormalizedJob, RawListing, Source


_FLOOR_SECS = int(_time.time()) - 60 * 60 * 24 * 95
# Dropping the literal "?" chars from the query — they confuse the URL-encoder
# round-trip and httpx ends up sending a malformed query string.
ALGOLIA_SEARCH = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?query=Ask+HN+Freelancer+Seeking+freelancer"
    "&tags=story"
    "&hitsPerPage=8"
    f"&numericFilters=created_at_i%3E{_FLOOR_SECS}"
)
ALGOLIA_ITEM = "https://hn.algolia.com/api/v1/items/{id}"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
SALARY_RE = re.compile(r"\$\s?(\d{2,3})\s?[kK]?\s?(?:[-–to]+\s?\$?(\d{2,3})\s?[kK]?)?")
SEEKING_RE = re.compile(r"^\s*seeking\s+freelancer", re.I)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _fetch_json(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def _is_freelancer_thread(title: str | None) -> bool:
    if not title:
        return False
    t = title.lower()
    return "freelancer" in t and ("seeking" in t or "freelancer?" in t)


class HNFreelancerSource(Source):
    slug = "hn_freelancer"
    kind = "html"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        months_back = int(config.get("months", 3))

        search = _fetch_json(ALGOLIA_SEARCH)
        threads = sorted(
            [h for h in search.get("hits", []) if _is_freelancer_thread(h.get("title"))],
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
                # Only keep SEEKING FREELANCER posts — skip SEEKING WORK and other noise.
                plain_first = _strip_html(text).split("\n", 1)[0].strip()
                if not SEEKING_RE.search(plain_first):
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
        plain = _strip_html(body)
        if not plain:
            return None

        lines = [l.strip() for l in plain.split("\n") if l.strip()]
        if not lines:
            return None

        # First line is something like:
        #   SEEKING FREELANCER | <skills/role> | <location> | <budget>
        # or just "SEEKING FREELANCER" with structure on lines 2-N.
        header = lines[0]
        # Strip the "SEEKING FREELANCER[S]" prefix to find the actual ad headline.
        header_after = re.sub(r"^seeking\s+freelancers?\s*[:\-—|]?\s*", "", header, flags=re.I).strip()

        parts = [p.strip() for p in re.split(r"\s*\|\s*", header_after) if p.strip()]
        role_or_skills = parts[0] if parts else "(see post)"
        location = " | ".join(parts[1:3]) if len(parts) > 1 else None
        remote = bool(re.search(r"\bremote\b|\banywhere\b|\bworldwide\b", header, re.I))

        # Title heuristic: prefer the first part of the header, else first ~80 chars of line 2.
        title = role_or_skills[:90] if role_or_skills and role_or_skills != "(see post)" else (
            lines[1][:90] if len(lines) > 1 else "Freelance project"
        )

        # Company / poster: many posts say "We at <X>" or "I'm <name> from <X>" or just have a URL.
        company_name = None
        for l in lines[:6]:
            m = re.search(r"\b(?:we (?:at|are)|i'?m\s+\w+\s+(?:from|at)|company:\s*)\s*([A-Z][A-Za-z0-9&.\-_ ]{1,40})", l)
            if m:
                company_name = m.group(1).strip().rstrip(".,")
                break
        if not company_name:
            # Try URL → domain as company.
            url_m = URL_RE.search(plain)
            if url_m:
                from urllib.parse import urlparse
                host = urlparse(url_m.group(0)).netloc.lstrip("www.")
                if host:
                    company_name = host.split(".")[0].title()
        if not company_name:
            # Fallback: use the author + " (HN)" so dedupe doesn't collide with another source.
            company_name = f"{raw.payload_json.get('author') or 'Freelance client'} (HN)"

        if hard_reject(title, plain, location):
            return None

        email_match = EMAIL_RE.search(plain)
        contact_email = email_match.group(0).lower() if email_match else None

        url_m = URL_RE.search(plain)
        company_url = url_m.group(0) if url_m else None
        company_domain = _domain_from_url(company_url) if company_url else None

        comp_min, comp_max = _parse_salary(plain)
        posted_iso = raw.payload_json.get("created_at")

        return NormalizedJob(
            external_id=raw.external_id,
            title=title,
            company_name=company_name[:80],
            company_domain=company_domain,
            company_website=company_url,
            description=plain[:8000],
            comp_min=comp_min,
            comp_max=comp_max,
            location=location,
            remote=remote,
            employment_type="contract",  # seeking freelancer = contract by definition
            contact_email=contact_email,
            url=f"https://news.ycombinator.com/item?id={raw.external_id}",
            posted_at=posted_iso,
        )


def _strip_html(body: str) -> str:
    plain = re.sub(r"<[^>]+>", "\n", body)
    plain = (plain
             .replace("&#x27;", "'").replace("&quot;", '"')
             .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
    return plain.strip()


def _domain_from_url(url: str) -> str | None:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url, re.I)
    return m.group(1).lower() if m else None


def _parse_salary(text: str) -> tuple[int | None, int | None]:
    m = SALARY_RE.search(text)
    if not m:
        return None, None
    lo = int(m.group(1)) * (1000 if "k" in (m.group(0) or "").lower() else 1)
    hi = (int(m.group(2)) * (1000 if "k" in (m.group(0) or "").lower() else 1)) if m.group(2) else None
    return lo, hi


source = HNFreelancerSource()
