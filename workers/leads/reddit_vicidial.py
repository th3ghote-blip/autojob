"""Reddit r/VICIDial scraper.

Free public JSON API. Returns recent posts in the subreddit, which is
small but high-signal — most posts are admins managing real installs.

Run cost: free.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import LeadSource, RawLead

SUBREDDITS = ["VICIDial", "vicidial"]  # both casings exist as separate subs
URL = "https://www.reddit.com/r/{sub}/new.json?limit=100"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8))
def _fetch(sub: str) -> dict[str, Any]:
    with httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": "autojob/1.0 (lead finder)"},
    ) as c:
        r = c.get(URL.format(sub=sub))
        r.raise_for_status()
        return r.json()


class RedditVicidialSource(LeadSource):
    slug = "reddit_vicidial"
    lead_kind = "vicidial"

    def discover(self) -> Iterable[RawLead]:
        seen: set[str] = set()
        for sub in SUBREDDITS:
            try:
                data = _fetch(sub)
            except Exception as e:
                yield RawLead(
                    source=self.slug,
                    source_url=f"_error:{sub}",
                    title=None,
                    excerpt=f"reddit fetch failed for r/{sub}: {e}",
                    raw_json={"_error": str(e), "sub": sub},
                )
                continue

            for child in data.get("data", {}).get("children", []):
                post = child.get("data") or {}
                permalink = post.get("permalink") or ""
                url = "https://www.reddit.com" + permalink
                if url in seen:
                    continue
                seen.add(url)

                title = post.get("title") or ""
                body = (post.get("selftext") or "").strip()
                created = post.get("created_utc")
                posted_iso = (
                    datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
                    if created else None
                )

                yield RawLead(
                    source=self.slug,
                    source_url=url,
                    title=title,
                    excerpt=(body[:1500] or title) or None,
                    company_guess=None,
                    company_domain=None,
                    signal_kind="forum_post",
                    posted_at=posted_iso,
                    raw_json={
                        "sub": sub,
                        "id": post.get("id"),
                        "title": title,
                        "body": body,
                        "author": post.get("author"),
                        "ups": post.get("ups"),
                    },
                )


source = RedditVicidialSource()
