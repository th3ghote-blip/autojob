"""Free recruiter-email scraper.

For a given company, pulls the homepage + /careers + /jobs + /contact +
/about, extracts every email visible (mailto: links and plain regex
matches), then ranks them.

Priority (highest -> lowest):
  1. jobs@, careers@, talent@, recruiting@, recruitment@, hiring@
  2. hr@, people@
  3. hello@, contact@, team@, partnerships@, founders@
  4. info@, business@
Anything matching noreply/no-reply/donotreply/press/legal/privacy/security/abuse
is excluded outright.

Returns the highest-priority email and the URL it was found on, or None.
Designed to be free and respectful: 1 request/sec/domain max, short timeouts,
gracefully skip on 403/404/SSL errors.
"""
from __future__ import annotations

import re
import time
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


# ─── Patterns ───────────────────────────────────────────────────────────────
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# In priority order. The first matching prefix wins.
PRIORITY_PREFIXES: list[str] = [
    "jobs", "careers", "talent", "recruiting", "recruitment", "hiring", "join",
    "hr", "people",
    "hello", "contact", "team", "partnerships", "founders", "founder",
    "info", "business",
]

# Hard exclude — never return these even if they're the only thing on the page.
EXCLUDE_PREFIXES = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "press", "media", "marketing",
    "legal", "privacy", "security", "abuse", "compliance",
    "billing", "accounting", "finance",
    "sales",  # we want recruiters, not SDRs
    "support", "help", "feedback",
    "unsubscribe",
    "webmaster", "postmaster", "admin", "root",
    "wordpress", "wp",
}

PATHS_TO_TRY = [
    "/",
    "/careers",
    "/careers/",
    "/jobs",
    "/jobs/",
    "/about",
    "/about/",
    "/contact",
    "/contact/",
    "/contact-us",
    "/team",
    "/company/contact",
]


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
def _fetch(url: str, timeout: float = 12.0) -> str | None:
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "autojob-email-bot/1.0 (+https://autojob-sigma.vercel.app)"},
            verify=True,
        ) as c:
            r = c.get(url)
            if r.status_code == 200:
                return r.text
            return None
    except Exception:
        return None


def _normalize_website(website_or_domain: str) -> str | None:
    """Return a canonical https://example.com URL, or None if junk."""
    if not website_or_domain:
        return None
    s = website_or_domain.strip()
    if not s.startswith("http"):
        s = "https://" + s
    try:
        u = urlparse(s)
        host = (u.netloc or "").lower().lstrip("www.")
        if not host or "." not in host:
            return None
        return f"https://{host}"
    except Exception:
        return None


def _email_priority(email: str) -> int:
    """Lower = better. Returns 999 for excluded; otherwise PRIORITY_PREFIXES index, or 100."""
    local = email.split("@", 1)[0].lower()
    if local in EXCLUDE_PREFIXES:
        return 999
    for i, p in enumerate(PRIORITY_PREFIXES):
        if local == p:
            return i
    # Personal-looking address (e.g. "alex.fernandez") — accept but rank lower.
    return 100


def _emails_in_html(html_text: str, base_url: str) -> Iterable[str]:
    if not html_text:
        return
    seen: set[str] = set()
    # Mailto: hrefs first.
    for m in re.finditer(r'href=["\']mailto:([^"\'?]+)', html_text, re.I):
        e = m.group(1).strip().lower()
        if e and e not in seen and "@" in e:
            seen.add(e)
            yield e
    # Plain text regex.
    for m in EMAIL_RE.finditer(html_text):
        e = m.group(0).strip().lower()
        if e and e not in seen:
            seen.add(e)
            yield e


def find_company_email(
    *,
    name: str | None = None,
    domain: str | None = None,
    website: str | None = None,
    sleep_between_requests: float = 0.4,
) -> dict | None:
    """Try several pages on the company site; return best match dict or None.

    Returns:
        {"email": str, "source_url": str, "priority": int} or None
    """
    base = _normalize_website(website or domain or "")
    if not base:
        return None
    company_host = urlparse(base).netloc.lstrip("www.")

    candidates: list[tuple[int, str, str]] = []  # (priority, email, source_url)

    for path in PATHS_TO_TRY:
        url = urljoin(base + "/", path.lstrip("/"))
        html_text = _fetch(url)
        if not html_text:
            continue
        for email in _emails_in_html(html_text, base):
            # Reject emails on a different domain than the company (prevents
            # capturing third-party SaaS support addresses on the page).
            host = email.split("@", 1)[1]
            host_root = ".".join(host.split(".")[-2:])
            company_root = ".".join(company_host.split(".")[-2:])
            if host_root != company_root:
                continue
            pri = _email_priority(email)
            if pri >= 999:
                continue
            candidates.append((pri, email, url))
        time.sleep(sleep_between_requests)
        # Early exit if we already have a top-tier match.
        if candidates and min(c[0] for c in candidates) <= 5:
            break

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    pri, email, src = candidates[0]
    return {"email": email, "source_url": src, "priority": pri}
