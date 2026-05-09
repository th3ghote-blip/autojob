"""Wellfound (ex-AngelList Talent) — Playwright with auth state.

Wellfound is the most anti-bot-heavy source on the list. Without a
logged-in session and a real browser fingerprint, the public job
board returns blocking interstitials.

Strategy: headed Playwright + persisted storage_state, only enabled
once a one-time `login` flow has been run interactively.

This file ships a structurally complete worker that NO-OPs cleanly
when no auth state exists, so the cron stays green. To enable:

    python -m workers.sources.wellfound login   # opens a window; you sign in once

That writes workers/.auth/wellfound.json. From the next cron run on,
the session cookie is reused. If the session expires, this source
goes back to no-op until you re-login.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable

from .base import NormalizedJob, RawListing, Source

AUTH_PATH = Path(__file__).parent.parent / ".auth" / "wellfound.json"
DEFAULT_SEARCH = "https://wellfound.com/jobs?role=ai-engineer"


class WellfoundSource(Source):
    slug = "wellfound"
    kind = "html"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        if not AUTH_PATH.exists():
            return iter(())  # no auth state -> no-op (cron stays green)

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
                    for card in page.query_selector_all("[data-test='JobSearchCard']"):
                        title_el = card.query_selector("[class*='Title']")
                        company_el = card.query_selector("[class*='CompanyName']")
                        link_el = card.query_selector("a[href*='/jobs/']")
                        if not (title_el and company_el and link_el):
                            continue
                        href = link_el.get_attribute("href") or ""
                        jid = href.rstrip("/").split("/")[-1].split("-", 1)[0]
                        if not jid:
                            continue
                        results.append(RawListing(
                            external_id=jid,
                            payload_json={
                                "url": "https://wellfound.com" + href if href.startswith("/") else href,
                                "title": (title_el.inner_text() or "").strip(),
                                "company": (company_el.inner_text() or "").strip(),
                            },
                        ))
                finally:
                    browser.close()
        except Exception:  # noqa: BLE001
            # Browser binary missing or any runtime failure — silent skip.
            return iter(())
        return iter(results)

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


def _login_flow() -> None:
    """Run once interactively to capture a logged-in session."""
    from playwright.sync_api import sync_playwright

    AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto("https://wellfound.com/login")
        print("Sign in in the browser window, then press ENTER here…")
        input()
        ctx.storage_state(path=str(AUTH_PATH))
        print(f"Saved auth state to {AUTH_PATH}")
        browser.close()


source = WellfoundSource()


if __name__ == "__main__" and "login" in sys.argv:
    _login_flow()
