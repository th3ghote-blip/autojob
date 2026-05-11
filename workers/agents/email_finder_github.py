"""GitHub-commit-based email finder.

For a given company, try to resolve their GitHub org and pull author emails
from their most-recently-active public repos. Returns the best company-domain
email found (or, as a fallback, a personal address of a top committer who
looks like a founder).

Free up to 5000 req/hour with a GitHub PAT (we reuse $GITHUB_TOKEN from
the existing Vercel env). No paid services.

Strategy per company:
 1. Resolve a GitHub org/user slug from the company name (try direct slug,
    `<name>+ai`, `<name>+labs`, then GitHub user search).
 2. Pull top 3 most-recently-updated public repos (skip forks/archived).
 3. For each repo, pull the most-recent 100 commits.
 4. Tally email → count, filtering out noreply/bot patterns.
 5. Rank: prefer emails on the company's own domain, then top-committed
    personal emails that look like a founder (firstname@gmail style).
 6. Return the best hit or None.
"""
from __future__ import annotations

import os
import re
import time
from collections import Counter
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

GH_API = "https://api.github.com"

# Emails we never return.
BOT_PATTERNS = re.compile(
    r"(noreply|no-reply|do-not-reply|donotreply|dependabot|github-actions|"
    r"users\.noreply\.github|web-flow|renovate-bot|copilot-swe-agent|"
    r"actions@github|app/dependabot|hello@greenkeeper|snyk-bot|"
    r"\.bot@|imgbot|allcontributors|users\.noreply\.github)",
    re.I,
)

# Personal-domain hints used when filtering fallback addresses.
PERSONAL_DOMAINS = {
    "gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com",
    "protonmail.com", "proton.me", "fastmail.com", "me.com", "live.com",
}


def _gh_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "autojob/1.0",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
def _gh_get(path: str, params: dict | None = None) -> Any:
    with httpx.Client(timeout=20, headers=_gh_headers()) as c:
        r = c.get(GH_API + path, params=params or {})
        if r.status_code == 404:
            return None
        if r.status_code == 403 and "rate limit" in r.text.lower():
            # Surface so the caller can throttle, but don't retry.
            raise RuntimeError("github_rate_limited")
        r.raise_for_status()
        return r.json()


def _slugify_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", name).lower()


def _resolve_org(name: str, domain: str | None) -> str | None:
    """Pick a GitHub org/user slug for this company. Returns None on no match."""
    if not name:
        return None
    candidates: list[str] = []
    slug = _slugify_name(name)
    if slug:
        candidates.extend([slug, slug + "ai", slug + "labs", slug + "hq", slug + "inc"])
    # If domain is e.g. "anthropic.com", also try its root.
    if domain:
        root = domain.split(".")[0].lower()
        root = re.sub(r"[^a-z0-9]", "", root)
        if root and root not in candidates:
            candidates.append(root)
    for cand in candidates:
        try:
            info = _gh_get(f"/users/{cand}")
            if info:
                return info["login"]
        except Exception:  # noqa: BLE001
            continue
    # Last resort: GitHub user search.
    try:
        res = _gh_get("/search/users", params={"q": name + " in:name type:org", "per_page": 1})
        if res and res.get("items"):
            return res["items"][0]["login"]
    except Exception:  # noqa: BLE001
        pass
    return None


def _top_repos(org: str, limit: int = 3) -> list[dict]:
    """Most-recently-pushed non-fork public repos, capped at `limit`."""
    repos = _gh_get(f"/users/{org}/repos", params={"per_page": 30, "sort": "pushed", "type": "owner"})
    if not repos:
        return []
    out = []
    for r in repos:
        if r.get("fork") or r.get("archived") or r.get("private"):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def _commits_emails(owner: str, repo: str, max_commits: int = 100) -> list[str]:
    commits = _gh_get(f"/repos/{owner}/{repo}/commits", params={"per_page": max_commits}) or []
    out = []
    for c in commits:
        email = ((c.get("commit") or {}).get("author") or {}).get("email")
        if not email:
            continue
        email = email.lower().strip()
        if BOT_PATTERNS.search(email):
            continue
        out.append(email)
    return out


def _rank(emails: list[str], company_domain: str | None) -> tuple[str, str] | None:
    """Pick the best email from a tally of (email -> count). Returns (email, why)."""
    if not emails:
        return None
    tally = Counter(emails)

    # Tier 1: same domain as the company.
    if company_domain:
        root = ".".join(company_domain.lower().split(".")[-2:])
        same_domain = [(e, n) for e, n in tally.items() if e.split("@", 1)[-1].endswith(root)]
        if same_domain:
            same_domain.sort(key=lambda x: -x[1])
            return same_domain[0][0], "same_domain_top_committer"

    # Tier 2: top committer on personal-domain — could be the founder.
    by_count = tally.most_common()
    for email, _n in by_count:
        host = email.split("@", 1)[-1]
        if host in PERSONAL_DOMAINS:
            local = email.split("@", 1)[0]
            # Personal-looking local part (no numeric suffix, no dot-heavy chains).
            if re.match(r"^[a-z]+(\.[a-z]+)?$", local):
                return email, "founder_personal_email_top_committer"

    # Tier 3: anything else — the top committer regardless.
    return by_count[0][0], "top_committer"


def find_company_email_github(
    *,
    name: str | None,
    domain: str | None = None,
) -> dict | None:
    """Return {email, source_url, method, ranked_via} or None."""
    if not name:
        return None
    try:
        org = _resolve_org(name, domain)
    except Exception:  # noqa: BLE001
        return None
    if not org:
        return None

    try:
        repos = _top_repos(org, limit=3)
    except Exception:  # noqa: BLE001
        return None
    if not repos:
        return None

    all_emails: list[str] = []
    repos_used: list[str] = []
    for r in repos:
        try:
            emails = _commits_emails(org, r["name"], max_commits=100)
        except Exception:  # noqa: BLE001
            continue
        all_emails.extend(emails)
        repos_used.append(r["name"])
        time.sleep(0.2)  # gentle on rate limit
        if len(all_emails) > 300:
            break

    picked = _rank(all_emails, domain)
    if not picked:
        return None
    email, ranked_via = picked
    return {
        "email": email,
        "source_url": f"https://github.com/{org}",
        "method": "github_commits",
        "ranked_via": ranked_via,
        "repos_scanned": repos_used,
        "candidates_collected": len(all_emails),
    }
