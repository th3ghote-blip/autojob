"""Reddit — `[HIRING]`/freelance/founder posts across configured subreddits.

Free public JSON API: GET https://www.reddit.com/r/<sub>/new.json?limit=100
No auth needed for read-only browsing.

config_json:
  {
    "subreddits": [
      {"sub": "forhire", "must_match": "[HIRING]"},
      {"sub": "SideProject", "must_match": "(?i)(hiring|looking for|need help)"}
    ],
    "limit_per_sub": 100
  }

Posters in r/forhire use `[HIRING]` / `[FOR HIRE]` prefixes — we keep
[HIRING] only since [FOR HIRE] is people offering services.
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..profile import hard_reject
from .base import NormalizedJob, RawListing, Source

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
SALARY_RE = re.compile(r"\$\s?(\d{2,3})\s?[kK]?\s?(?:[-–to]+\s?\$?(\d{2,3})\s?[kK]?)?")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _fetch_json(url: str) -> dict[str, Any]:
    with httpx.Client(
        timeout=20, follow_redirects=True,
        headers={"User-Agent": "autojob/1.0 (by /u/anonymous)"},
    ) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


class RedditSource(Source):
    slug = "reddit"
    kind = "api"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        subs = config.get("subreddits") or [
            {"sub": "forhire", "must_match": r"\[HIRING\]"},
        ]
        limit = int(config.get("limit_per_sub", 100))

        for entry in subs:
            sub = entry.get("sub") if isinstance(entry, dict) else entry
            must_match = (entry.get("must_match") if isinstance(entry, dict) else None) or ""
            if not sub:
                continue
            url = f"https://www.reddit.com/r/{sub}/new.json?limit={limit}"
            try:
                data = _fetch_json(url)
            except Exception as e:  # noqa: BLE001
                yield RawListing(
                    external_id=f"_error_{sub}",
                    payload_json={"_error": str(e), "sub": sub},
                )
                continue

            for child in data.get("data", {}).get("children", []):
                post = child.get("data") or {}
                title = post.get("title") or ""
                if must_match and not re.search(must_match, title):
                    continue
                yield RawListing(
                    external_id=f"{sub}:{post.get('id')}",
                    payload_json={
                        "sub": sub,
                        "id": post.get("id"),
                        "title": title,
                        "selftext": post.get("selftext") or "",
                        "author": post.get("author"),
                        "url": "https://www.reddit.com" + (post.get("permalink") or ""),
                        "created_utc": post.get("created_utc"),
                        "ups": post.get("ups"),
                    },
                )

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        item = raw.payload_json
        if "_error" in item:
            return None

        title = (item.get("title") or "").strip()
        body = (item.get("selftext") or "").strip()
        if not title:
            return None

        # Strip the [HIRING] / [REMOTE] tags from the title for storage.
        clean_title = re.sub(r"\[[A-Z][A-Z\s/]+\]", "", title).strip(" -|·")[:120]

        # Pull contact details from body.
        email_match = EMAIL_RE.search(body)
        contact_email = email_match.group(0).lower() if email_match else None

        # Location & remote heuristic from title + body.
        text = title + "\n" + body
        remote = bool(re.search(r"\b(remote|anywhere|worldwide|wfh)\b", text, re.I))
        location_match = re.search(r"\[(remote[^\]]*|.*?city.*?|EU|USA|US|UK|Canada|EMEA|Europe|LATAM)\]", title, re.I)
        location = location_match.group(1) if location_match else None

        # Company / poster — Reddit doesn't expose this directly. Use the post
        # author handle as a sentinel so dedupe doesn't collide with other sources.
        company_name = f"{item.get('author') or 'reddit user'} ({item.get('sub')})"

        # Hard-reject obvious junk.
        if hard_reject(clean_title or title, body, location):
            return None

        # Salary parse.
        comp_min, comp_max = _parse_salary(text)

        # Convert UTC seconds to ISO.
        posted_iso = None
        if item.get("created_utc"):
            from datetime import datetime, timezone
            posted_iso = datetime.fromtimestamp(item["created_utc"], tz=timezone.utc).isoformat()

        # First URL in body for the company website (best-effort).
        url_m = URL_RE.search(body)
        company_url = url_m.group(0) if url_m else None
        company_domain = None
        if company_url:
            try:
                company_domain = urlparse(company_url).netloc.lstrip("www.") or None
            except Exception:
                pass

        return NormalizedJob(
            external_id=raw.external_id,
            title=clean_title or title[:120],
            company_name=company_name,
            company_domain=company_domain,
            company_website=company_url,
            description=body[:8000],
            comp_min=comp_min,
            comp_max=comp_max,
            location=location,
            remote=remote,
            employment_type="contract",
            contact_email=contact_email,
            url=item.get("url"),
            posted_at=posted_iso,
        )


def _parse_salary(text: str) -> tuple[int | None, int | None]:
    m = SALARY_RE.search(text)
    if not m:
        return None, None
    raw = m.group(0).lower()
    mult = 1000 if "k" in raw else 1
    lo = int(m.group(1)) * mult
    hi = int(m.group(2)) * mult if m.group(2) else None
    return lo, hi


source = RedditSource()
