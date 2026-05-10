"""ai-jobs.net (aijobs.net) — static-rendered listings page.

Scrape the homepage `<ul id="job_list">` of <li> cards. Updated 2026-05 for
the current Django/htmx markup. The old structure (`li.list-group-item`)
no longer exists.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from ..profile import hard_reject
from .base import NormalizedJob, RawListing, Source

INDEX = "https://aijobs.net/"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get(url: str) -> str:
    with httpx.Client(
        timeout=30, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (autojob/1.0)"},
    ) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


_SALARY_RE = re.compile(r"(USD|EUR|GBP|CAD|AUD)\s*([\d.]+)\s*([Kk])\s*[-–]\s*([\d.]+)\s*([Kk])")


class AiJobsSource(Source):
    slug = "ai_jobs"
    kind = "html"

    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        base = (config.get("base") or INDEX).rstrip("/") + "/"
        html = _get(base)
        soup = BeautifulSoup(html, "lxml")
        ul = soup.find("ul", id="job_list")
        if not ul:
            return
        for li in ul.find_all("li", recursive=False):
            link = li.select_one("a.stretched-link[href^='/job/']")
            if not link:
                continue
            href = link.get("href") or ""
            external_id = re.sub(r"^/job/", "", href).rstrip("/").split("?", 1)[0]
            full_url = base.rstrip("/") + href

            # Title is the text node inside the <a>, minus the "Featured" / "Feat." badges.
            for badge in link.select("span"):
                badge.extract()
            title = link.get_text(strip=True)

            # Salary chip is a sibling .text-bg-success span.
            sal_el = li.select_one("span.text-bg-success")
            salary = sal_el.get_text(strip=True) if sal_el else ""

            # Right-side text-end column: seniority + company + posted-ago.
            right = li.select_one("div.text-end")
            seniority = ""
            company = ""
            posted = ""
            if right:
                sen_el = right.select_one("span.text-bg-warning")
                if sen_el:
                    seniority = sen_el.get_text(strip=True)
                # Company is in the second <div> of text-end (after seniority div).
                divs = right.find_all("div", recursive=False)
                if len(divs) >= 2:
                    company = divs[1].get_text(strip=True)
                if len(divs) >= 3:
                    posted = divs[-1].get_text(strip=True)

            yield RawListing(
                external_id=external_id,
                payload_json={
                    "url": full_url,
                    "title": title,
                    "company": company,
                    "salary": salary,
                    "seniority": seniority,
                    "posted_relative": posted,
                },
                payload_html=str(li),
            )

    def parse(self, raw: RawListing) -> NormalizedJob | None:
        item = raw.payload_json
        title = (item.get("title") or "").strip()
        company = (item.get("company") or "").strip()
        if not title or not company:
            return None

        # Cheap pre-filter (junior, ML research, MLOps infra, etc.).
        if hard_reject(title, None, None):
            return None

        # Parse salary if present.
        comp_min = comp_max = None
        currency = "USD"
        if item.get("salary"):
            m = _SALARY_RE.search(item["salary"])
            if m:
                currency = m.group(1)
                comp_min = int(float(m.group(2)) * 1000)
                comp_max = int(float(m.group(4)) * 1000)

        # Detect remote-friendly from posting (heuristic).
        text_blob = f"{title} {item.get('seniority','')} {item.get('salary','')}"
        remote = bool(re.search(r"\bremote\b", text_blob, re.I))

        return NormalizedJob(
            external_id=raw.external_id,
            title=title,
            company_name=company,
            description=None,  # description requires a per-job /job/<id> fetch — defer to research step
            comp_min=comp_min,
            comp_max=comp_max,
            comp_currency=currency,
            location=None,
            remote=remote,
            employment_type="full_time",
            url=item.get("url"),
        )


source = AiJobsSource()
