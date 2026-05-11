"""Upwork — Playwright-based search results scrape.

Upwork's public job feed is heavily anti-bot:
 - Cloudflare challenge on cold visits
 - Login wall after a few page-loads
 - Aggressive shadow-banning for automation

Strategy: persisted Playwright storage_state captured by running an
interactive login once, then headed Playwright pulls the saved-search
results page and parses cards.

Until the storage_state file exists at workers/.auth/upwork.json this
source no-ops cleanly so the cron stays green.

To enable:
    python -m workers.sources.upwork login    # signs you in once

config_json:
    {"search_url": "https://www.upwork.com/nx/search/jobs/?q=AI%20engineer&sort=recency"}
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable

from ..profile import hard_reject
from .base import NormalizedJob, RawListing, Source

AUTH_PATH = Path(__file__).parent.parent / ".auth" / "upwork.json"
DEFAULT_SEARCH = "https://www.upwork.com/nx/search/jobs/?q=AI%20engineer&sort=recency"


class UpworkSource(Source):
    slug = "upwork"
    kind = "html"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        if not AUTH_PATH.exists():
            return iter(())  # silent skip — no auth state yet

        try:
            from playwright.sync_api import sync_playwright
        except Exception:  # noqa: BLE001
            return iter(())

        url = config.get("search_url", DEFAULT_SEARCH)
        results: list[RawListing] = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    ctx = browser.new_context(storage_state=str(AUTH_PATH))
                    page = ctx.new_page()
                    page.goto(url, wait_until="networkidle", timeout=60000)
                    page.wait_for_timeout(3000)
                    # Card selectors on Upwork change frequently; using
                    # data-test attrs is more stable than class names.
                    cards = page.query_selector_all("[data-test='JobTile']")
                    for card in cards:
                        title_el = card.query_selector("[data-test='job-tile-title']")
                        link_el = card.query_selector("a[href*='/jobs/']")
                        desc_el = card.query_selector("[data-test='UpCLineClamp JobDescription']")
                        budget_el = card.query_selector("[data-test='is-fixed-price'], [data-test='job-type-label']")
                        if not (title_el and link_el):
                            continue
                        href = link_el.get_attribute("href") or ""
                        jid = href.rstrip("/").split("/")[-1].split("~", 1)[-1]
                        results.append(RawListing(
                            external_id=jid,
                            payload_json={
                                "url": "https://www.upwork.com" + href if href.startswith("/") else href,
                                "title": (title_el.inner_text() or "").strip(),
                                "description": (desc_el.inner_text() or "").strip() if desc_el else "",
                                "budget": (budget_el.inner_text() or "").strip() if budget_el else "",
                            },
                        ))
                finally:
                    browser.close()
        except Exception:  # noqa: BLE001
            return iter(())
        return iter(results)

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        item = raw.payload_json
        title = (item.get("title") or "").strip()
        if not title:
            return None
        if hard_reject(title, item.get("description"), None):
            return None
        return NormalizedJob(
            external_id=raw.external_id,
            title=title[:120],
            company_name=f"Upwork client",
            description=(item.get("description") or "")[:8000],
            location=None,
            remote=True,
            employment_type="contract",
            url=item.get("url"),
        )


def _login_flow() -> None:
    """Run once interactively to capture a logged-in Upwork session."""
    from playwright.sync_api import sync_playwright
    AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto("https://www.upwork.com/ab/account-security/login")
        print("Sign in to Upwork in the browser, complete any captcha, then press ENTER here…")
        input()
        ctx.storage_state(path=str(AUTH_PATH))
        print(f"Saved auth state to {AUTH_PATH}")
        browser.close()


source = UpworkSource()


if __name__ == "__main__" and "login" in sys.argv:
    _login_flow()
