"""vicidial.org community forum scraper.

The forum is phpBB. Companies routinely post asking for help installing,
upgrading, or troubleshooting their dialer — these self-identify as
active Vicidial sites. Posters often include company name and seat-count
in their signatures or post bodies.

Boards of interest:
  - viewforum.php?f=4   = ViciDial General Discussion
  - viewforum.php?f=7   = ViciDial Installation Help
  - viewforum.php?f=3   = ViciDial Programmers' Discussion

We pull the recent topic list from each, then fetch the first post of
each topic for the body excerpt. Polite delays between requests.

Run cost: free.
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterable
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import LeadSource, RawLead

BASE = "https://www.vicidial.org/VICIDIALforum/"
BOARDS = [
    ("viewforum.php?f=4",  "general"),
    ("viewforum.php?f=7",  "install_help"),
    ("viewforum.php?f=3",  "programmers"),
]
MAX_TOPICS_PER_BOARD = 25  # ~75 topics total per run


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8))
def _get(url: str) -> str:
    with httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (autojob lead finder; contact: info@getaiappgenius.com)",
            "Accept-Language": "en-US,en;q=0.9",
        },
    ) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


def _topic_links(board_url: str) -> list[tuple[str, str]]:
    """Return (topic_url, title) tuples for the recent topics on a board."""
    html = _get(board_url)
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    # phpBB uses `a.topictitle` for topic links.
    for a in soup.select("a.topictitle")[:MAX_TOPICS_PER_BOARD]:
        href = a.get("href") or ""
        if not href:
            continue
        full = urljoin(board_url, href)
        title = a.get_text(strip=True)
        out.append((full, title))
    return out


def _first_post_body(topic_url: str) -> tuple[str | None, str | None, str | None]:
    """Return (body_excerpt, author, posted_iso) for the first post."""
    try:
        html = _get(topic_url)
    except Exception:
        return None, None, None
    soup = BeautifulSoup(html, "html.parser")
    post = soup.select_one(".postbody") or soup.select_one(".content")
    body = post.get_text(" ", strip=True)[:1500] if post else None

    author_el = soup.select_one(".author strong, .username, .username-coloured")
    author = author_el.get_text(strip=True) if author_el else None

    # phpBB shows post time in a `.author` block: e.g. "by foo » Mon May 12, 2025 4:23 pm".
    posted_iso = None
    author_block = soup.select_one(".author")
    if author_block:
        text = author_block.get_text(" ", strip=True)
        m = re.search(r"»\s*([A-Z][a-z]+\s+[A-Z][a-z]+\s+\d{1,2},\s*\d{4})", text)
        if m:
            try:
                from datetime import datetime
                dt = datetime.strptime(m.group(1), "%a %b %d, %Y")
                posted_iso = dt.isoformat() + "+00:00"
            except Exception:
                pass

    return body, author, posted_iso


class VicidialForumSource(LeadSource):
    slug = "vicidial_forum"
    lead_kind = "vicidial"

    def discover(self) -> Iterable[RawLead]:
        seen: set[str] = set()
        for path, board_slug in BOARDS:
            board_url = urljoin(BASE, path)
            try:
                topics = _topic_links(board_url)
            except Exception as e:
                yield RawLead(
                    source=self.slug,
                    source_url=f"_error:{board_slug}",
                    title=None,
                    excerpt=f"forum board fetch failed: {e}",
                    raw_json={"_error": str(e), "board": board_slug},
                )
                continue

            for topic_url, topic_title in topics:
                if topic_url in seen:
                    continue
                seen.add(topic_url)

                body, author, posted_iso = _first_post_body(topic_url)
                excerpt = body or topic_title

                yield RawLead(
                    source=self.slug,
                    source_url=topic_url,
                    title=topic_title,
                    excerpt=excerpt,
                    company_guess=None,
                    company_domain=None,
                    signal_kind="forum_post",
                    posted_at=posted_iso,
                    raw_json={
                        "board": board_slug,
                        "topic_title": topic_title,
                        "author": author,
                        "body": body,
                    },
                )
                time.sleep(1.5)


source = VicidialForumSource()
