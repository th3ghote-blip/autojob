"""DuckDuckGo HTML search for consulting-buyer signals.

Free, no API key. We hit the HTML endpoint (`https://html.duckduckgo.com/html/`)
and parse result links/snippets.

Queries cover the consulting-buyer surface: companies running automation-relevant
SMB stacks (Vicidial, HubSpot, Pipedrive, Shopify, etc.) AND companies admitting
AI/ops gaps by hiring Head of AI / fractional CTO / automation lead.

The classifier (Haiku) does the final prospect/non-prospect cut. The historical
filename `google_vicidial.py` is kept for git continuity; the source slug is
still `google_vicidial` so existing rows don't fork into duplicates.

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

# Each query yields ~10-30 hits depending on noise. Total runtime budget
# scales linearly — keep below ~40 to stay under 5 min per run.
_TOOLS = [
    "Vicidial", "GoAutoDial", "HubSpot CRM", "Pipedrive", "Zoho CRM",
    "Shopify", "QuickBooks Online", "Xero", "Asana", "monday.com",
    "Mailchimp", "ActiveCampaign", "BambooHR", "ServiceTitan", "Jobber",
    "Zendesk", "Freshdesk",
]

# Buyer-signal templates — applied to each tool above.
_TOOL_TEMPLATES = [
    '"we use {tool}"',
    '"running {tool}"',
    '"our {tool} setup"',
]

# Standalone queries — companies admitting AI/ops gaps (consulting-buying signal).
_GAP_QUERIES = [
    '"hiring head of AI"',
    '"hiring AI lead"',
    '"hiring fractional CTO"',
    '"hiring automation lead"',
    '"AI transformation consultant"',
    '"workflow automation consultant"',
    'site:linkedin.com "hiring AI consultant"',
]

QUERIES: list[str] = [tpl.format(tool=t) for t in _TOOLS for tpl in _TOOL_TEMPLATES] + _GAP_QUERIES

# Domains we know are not buyer signals (vendors themselves, docs, generic).
NOISE_DOMAINS = {
    # vendors themselves
    "vicidial.com", "vicidial.org", "goautodial.com",
    "hubspot.com", "pipedrive.com", "zoho.com",
    "shopify.com", "quickbooks.intuit.com", "xero.com",
    "asana.com", "monday.com", "mailchimp.com", "activecampaign.com",
    "bamboohr.com", "servicetitan.com", "getjobber.com",
    "zendesk.com", "freshworks.com", "freshdesk.com",
    # generic noise
    "github.com", "stackoverflow.com", "wikipedia.org", "youtube.com",
    "reddit.com",  # operator: no forum-anchored leads
    # NOTE: g2.com, capterra.com, softwareadvice.com, trustpilot.com kept IN-scope
    # — these pages surface NAMED customers in reviews (e.g. GOSAT came through
    # softwareadvice.com in run #1).
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
