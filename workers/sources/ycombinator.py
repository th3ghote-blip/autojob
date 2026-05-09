"""YC Work at a Startup — Playwright-based.

Public listings at https://www.workatastartup.com/jobs are partially
visible without login (titles, company, blurb). Full details + apply
flow require sign-in. Strategy:
  1. Headless Playwright pull of the search page filtered to AI/ML.
  2. For each job card, extract company, title, location, comp blurb,
     URL. external_id = the trailing job number in the URL.
  3. Description is stored as the on-page snippet; the research step
     can enrich later by visiting the URL with a logged-in session.

Auth state (cookies) can be persisted to workers/.auth/yc.json by
running a one-time interactive `python -m workers.sources.ycombinator login`.
This module's discover() will load that state if present.

If the Playwright browser binary isn't installed (default on CI runners),
this source silently returns nothing — runner stays green.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from .base import NormalizedJob, RawListing, Source

AUTH_PATH = Path(__file__).parent.parent / ".auth" / "yc.json"
SEARCH_URL = "https://www.workatastartup.com/jobs?role_types[]=eng&role_types[]=ml"


def _scrape(url: str, storage_state: str | None) -> list[dict[str, str]]:
    """Run Playwright; return a list of raw listings or [] on any failure."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(storage_state=storage_state)
                page = ctx.new_page()
                page.goto(url, wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(2500)
                out: list[dict[str, str]] = []
                seen: set[str] = set()
                for card in page.query_selector_all("a[href*='/jobs/']"):
                    href = card.get_attribute("href") or ""
                    if not href.startswith("/jobs/"):
                        continue
                    jid = href.rstrip("/").split("/")[-1].split("-", 1)[0]
                    if not jid.isdigit() or jid in seen:
                        continue
                    seen.add(jid)
                    title = (card.inner_text() or "").strip()
                    company = ""
                    container = card.evaluate_handle("el => el.closest('div')")
                    if container:
                        container_el = container.as_element()
                        if container_el:
                            company_el = (
                                container_el.query_selector("[class*='company']")
                                or container_el.query_selector("h3")
                            )
                            if company_el:
                                company = (company_el.inner_text() or "").strip()
                    out.append({
                        "id": jid,
                        "url": "https://www.workatastartup.com" + href,
                        "title": title,
                        "company": company,
                    })
                return out
            finally:
                browser.close()
    except Exception:  # noqa: BLE001
        # Browser binary missing, network blocked, or any other failure —
        # silent skip so the cron stays green.
        return []


class YCombinatorSource(Source):
    slug = "ycombinator"
    kind = "html"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        url = config.get("search_url", SEARCH_URL)
        storage_state = str(AUTH_PATH) if AUTH_PATH.exists() else None
        for item in _scrape(url, storage_state):
            yield RawListing(
                external_id=item["id"],
                payload_json={"url": item["url"], "title": item["title"], "company": item["company"]},
            )

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        item = raw.payload_json
        title = (item.get("title") or "").strip()
        company = (item.get("company") or "").strip()
        if not title or not company:
            return None
        return NormalizedJob(
            external_id=raw.external_id,
            title=title,
            company_name=company,
            url=item.get("url"),
            employment_type="full_time",
        )


source = YCombinatorSource()
