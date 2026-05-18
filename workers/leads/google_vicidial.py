"""DuckDuckGo HTML search for Vicidial customer signals.

Free, no API key, no rate-limit auth needed. We hit the HTML endpoint
(`https://html.duckduckgo.com/html/`) and parse result links/snippets.

Queries are tuned to find COMPANIES running Vicidial, not the project
itself. The classifier (Haiku) does the final prospect/non-prospect cut.

Run cost: free.
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterable
from urllib.parse import urlparse, quote_plus

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import LeadSource, RawLead

# Queries tuned for buyer-signal, not noise. Each yields ~20-30 hits.
QUERIES = [
    '"we use vicidial"',
    '"running vicidial"',
    '"vicidial admin" hiring',
    '"vicidial" "call center" hiring',
    'site:linkedin.com "vicidial"',
    'site:upwork.com "vicidial"',
    'site:reddit.com "vicidial" "our company"',
    '"vicidial dialer" company',
]

# Domains we know are not customer signals (the project itself, docs, generic).
NOISE_DOMAINS = {
    "vicidial.com",
    "vicidial.org",
    "github.com",
    "stackoverflow.com",
    "wikipedia.org",
    "youtube.com",
}

# Pull a domain out of an absolute URL.
def _domain_of(url: str) -> str | None:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def _ddg_html(query: str) -> str:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    with httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    ) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


class GoogleVicidialSource(LeadSource):
    """Misnomer — we use DuckDuckGo (free) but keep the slug `google_vicidial`
    so the operator can mentally bucket it as 'web search results'."""
    slug = "google_vicidial"
    lead_kind = "vicidial"

    def discover(self) -> Iterable[RawLead]:
        seen: set[str] = set()
        for q in QUERIES:
            try:
                html = _ddg_html(q)
            except Exception as e:
                yield RawLead(
                    source=self.slug,
                    source_url=f"_error:{q}",
                    title=None,
                    excerpt=f"DDG fetch failed for {q!r}: {e}",
                    raw_json={"_error": str(e), "query": q},
                )
                continue

            soup = BeautifulSoup(html, "html.parser")
            for result in soup.select("div.result"):
                a = result.select_one("a.result__a")
                if not a:
                    continue
                href = a.get("href") or ""
                # DDG sometimes wraps in a redirect — extract uddg=.
                m = re.search(r"uddg=([^&]+)", href)
                if m:
                    from urllib.parse import unquote
                    href = unquote(m.group(1))
                if not href.startswith("http"):
                    continue

                domain = _domain_of(href)
                if domain in NOISE_DOMAINS:
                    continue
                if href in seen:
                    continue
                seen.add(href)

                title = a.get_text(strip=True) or None
                snippet_el = result.select_one(".result__snippet")
                excerpt = snippet_el.get_text(strip=True) if snippet_el else None

                yield RawLead(
                    source=self.slug,
                    source_url=href,
                    title=title,
                    excerpt=excerpt,
                    company_guess=None,
                    company_domain=domain,
                    signal_kind="customer_mention",
                    posted_at=None,
                    raw_json={"query": q, "title": title, "snippet": excerpt},
                )

            # Be polite — DDG will rate-limit aggressively otherwise.
            time.sleep(2.5)


source = GoogleVicidialSource()
