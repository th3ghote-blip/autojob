"""Software-review aggregator scraper.

For each SMB ops tool in TOOLS, hit its Capterra / SoftwareAdvice profile
and extract the customer-review listings. Each review names the reviewer's
company (often), their industry, company size, and the pain point they
mention — all of which feed the consulting-buyer classifier downstream.

Why these sites: reviewers self-identify with their company and what they
use the tool for, so we get IDENTIFIABLE companies with explicit signal
that they run an automation-relevant stack. This is exactly how GOSAT
surfaced in run #1 (via softwareadvice.com).

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

# (tool slug, category slug, display name) — these are the consulting-buyer
# stacks. Each company using one of these = potential $1-2.5k/mo prospect for
# either an analytics overlay, AI workflow, or automation glue.
SOFTWAREADVICE_PROFILES = [
    # Call centres / dialers
    ("vicidial",     "call-center", "VICIdial"),
    ("goautodial",   "call-center", "GoAutoDial"),
    # CRM / sales SMB
    ("hubspot-crm",  "crm",         "HubSpot CRM"),
    ("pipedrive",    "crm",         "Pipedrive"),
    ("zoho-crm",     "crm",         "Zoho CRM"),
    # E-commerce
    ("shopify",      "ecommerce",   "Shopify"),
    # Accounting (SMB)
    ("quickbooks-online", "accounting", "QuickBooks Online"),
    ("xero",         "accounting",  "Xero"),
    # PM / collab
    ("asana",        "project-management", "Asana"),
    ("monday-com",   "project-management", "monday.com"),
    # Marketing automation
    ("mailchimp",    "email-marketing", "Mailchimp"),
    ("activecampaign", "email-marketing", "ActiveCampaign"),
    # HR / recruiting
    ("bamboohr",     "hr",          "BambooHR"),
    # Field service / trades
    ("servicetitan", "field-service-management", "ServiceTitan"),
    ("jobber",       "field-service-management", "Jobber"),
    # Customer support
    ("zendesk",      "help-desk",   "Zendesk"),
    ("freshdesk",    "help-desk",   "Freshdesk"),
]

BASE = "https://www.softwareadvice.com"
MAX_REVIEWS_PER_TOOL = 30  # cap per tool to stay polite + bounded run time


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def _get(url: str) -> str:
    with httpx.Client(
        timeout=25,
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


def _profile_url(category: str, slug: str) -> str:
    return f"{BASE}/{category}/{slug}-profile/"


def _reviews_url(category: str, slug: str) -> str:
    # SoftwareAdvice puts reviews on the same profile page; we still hit a
    # dedicated reviews URL when available because it surfaces more entries.
    return f"{BASE}/{category}/{slug}-profile/reviews/"


def _parse_reviews(html: str, tool_display: str) -> list[dict[str, Any]]:
    """Best-effort review extraction. SoftwareAdvice changes markup
    periodically; we try a handful of selector strategies and fall back
    to text-block heuristics."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []

    # Strategy 1: structured review blocks (their current schema)
    blocks = soup.select("[data-test-id*='review'], [class*='Review_review'], [class*='review-card']")
    if not blocks:
        # Strategy 2: article-style blocks with star ratings
        blocks = soup.select("article")

    for block in blocks[:MAX_REVIEWS_PER_TOOL]:
        body_text = block.get_text(" ", strip=True)
        if len(body_text) < 80:
            continue

        # Company / industry / size are usually in a meta strip near the top.
        # Look for "Industry:", "Company size:", country labels, etc.
        industry = _extract_label(body_text, ["Industry:", "Sector:"])
        size     = _extract_label(body_text, ["Company size:", "Employees:", "Used the software for:"])
        role     = _extract_label(body_text, ["Used the software for:", "Reviewer:"])
        country  = _extract_country(body_text)

        # The reviewer's company name is rarely in the markup — most reviews
        # are pseudonymous. We capture the surrounding context so the
        # classifier can decide if a company is identifiable.
        title_el = block.select_one("h3, h4, .review-title, [class*='title']")
        title = title_el.get_text(strip=True) if title_el else None

        # Anchor URL for this review (if any) — fall back to the profile URL.
        review_a = block.select_one("a[href*='review']")
        href = review_a.get("href") if review_a else None
        out.append({
            "title": title,
            "body": body_text[:1500],
            "industry": industry,
            "size": size,
            "role": role,
            "country": country,
            "href": href,
        })
    return out


LABEL_RE_CACHE: dict[str, re.Pattern] = {}


def _extract_label(text: str, labels: list[str]) -> str | None:
    for lbl in labels:
        key = lbl
        if key not in LABEL_RE_CACHE:
            LABEL_RE_CACHE[key] = re.compile(re.escape(lbl) + r"\s*([A-Za-z0-9 ,\-\&/]+?)(?:\s{2,}|[\.\|]|$)", re.I)
        m = LABEL_RE_CACHE[key].search(text)
        if m:
            return m.group(1).strip()[:120] or None
    return None


COUNTRY_RE = re.compile(
    r"\b(United States|USA|UK|United Kingdom|Canada|Australia|Brazil|Mexico|Spain|Portugal|Argentina|Colombia|Chile|Germany|France|India|Philippines)\b",
    re.I,
)


def _extract_country(text: str) -> str | None:
    m = COUNTRY_RE.search(text)
    return m.group(1) if m else None


class SoftwareReviewSource(LeadSource):
    slug = "software_review"
    lead_kind = "consulting"

    def discover(self) -> Iterable[RawLead]:
        for slug, category, display in SOFTWAREADVICE_PROFILES:
            urls = [_reviews_url(category, slug), _profile_url(category, slug)]
            html: str | None = None
            chosen_url: str | None = None
            for u in urls:
                try:
                    html = _get(u)
                    chosen_url = u
                    break
                except Exception:
                    continue
            if not html or not chosen_url:
                yield RawLead(
                    source=self.slug,
                    source_url=f"_error:{slug}",
                    title=display,
                    excerpt=f"both profile and reviews URLs failed for {display}",
                    raw_json={"_error": "fetch_failed", "slug": slug},
                )
                continue

            reviews = _parse_reviews(html, display)
            if not reviews:
                # Even the profile page itself is a useful lead-of-leads: it
                # confirms the tool exists and links to its customer pool.
                yield RawLead(
                    source=self.slug,
                    source_url=chosen_url,
                    title=f"{display} — software-review profile",
                    excerpt=f"No structured reviews extracted from {display}'s profile.",
                    signal_kind="customer_mention",
                    raw_json={"slug": slug, "tool": display, "no_reviews": True},
                )
                time.sleep(2)
                continue

            for r in reviews:
                # One row per review. The classifier decides if it's a real
                # prospect (named company with pain) or noise.
                anchor = r.get("href") or chosen_url
                # Synthesize a stable per-review URL for dedupe — fragment on
                # the first 80 chars of the review body so re-runs upsert.
                stable_key = chosen_url + "#" + re.sub(r"\W+", "_", r["body"][:80])
                yield RawLead(
                    source=self.slug,
                    source_url=stable_key,
                    title=r.get("title") or f"{display} review",
                    excerpt=r["body"],
                    company_guess=None,  # classifier extracts from body
                    company_domain=None,
                    signal_kind="customer_mention",
                    posted_at=None,
                    raw_json={
                        "tool": display,
                        "tool_slug": slug,
                        "tool_category": category,
                        "profile_url": chosen_url,
                        "review_url": anchor,
                        "industry": r.get("industry"),
                        "size": r.get("size"),
                        "role": r.get("role"),
                        "country": r.get("country"),
                        "body": r["body"],
                    },
                )

            time.sleep(2.5)  # polite delay between tools


source = SoftwareReviewSource()
