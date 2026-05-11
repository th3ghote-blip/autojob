"""Backfill recruiter emails for companies that don't have one yet.

For each company missing contact_email, runs the email-finder agent against
the company's website. On a hit, also propagates the email to all of that
company's jobs that don't already have their own contact_email.

Usage:
  python -m workers.find_emails                  # all companies, never-checked first
  python -m workers.find_emails --max 50         # cap iterations
  python -m workers.find_emails --recheck        # re-run even if checked already
"""
from __future__ import annotations

import argparse
import time

from .agents.email_finder import find_company_email
from .agents.email_finder_github import find_company_email_github
from .db import db


def _candidates(limit: int, recheck: bool) -> list[dict]:
    """Return companies to scan. Prefers never-checked rows first.

    With recheck=False (default): only rows that have never been checked AND
    don't already have an email.
    With recheck=True: all rows ordered oldest-checked first.
    """
    if not recheck:
        return (
            db().table("companies")
            .select("id, name, domain, website")
            .is_("contact_email", "null")
            .is_("contact_email_checked_at", "null")
            .limit(limit)
            .execute()
        ).data or []
    return (
        db().table("companies")
        .select("id, name, domain, website")
        .order("contact_email_checked_at", desc=False)
        .limit(limit)
        .execute()
    ).data or []


def _propagate_to_jobs(company_id: str, email: str) -> int:
    """Set contact_email on company's jobs that don't already have one."""
    res = (
        db().table("jobs").update({"contact_email": email})
        .eq("company_id", company_id).is_("contact_email", None).execute()
    )
    return len(res.data or [])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=200, help="cap how many companies to process")
    ap.add_argument("--recheck", action="store_true", help="also process companies already checked")
    args = ap.parse_args()

    companies = _candidates(args.max, args.recheck)
    print(f"checking {len(companies)} companies…")

    found = no_match = errored = 0
    propagated_total = 0

    for c in companies:
        site = c.get("website") or c.get("domain")
        if not site:
            db().table("companies").update({
                "contact_email_checked_at": "now()",
            }).eq("id", c["id"]).execute()
            no_match += 1
            continue

        try:
            result = find_company_email(name=c.get("name"), domain=c.get("domain"), website=c.get("website"))
        except Exception as e:  # noqa: BLE001
            print(f"  ! {c['name']}: {e}")
            errored += 1
            db().table("companies").update({
                "contact_email_checked_at": "now()",
            }).eq("id", c["id"]).execute()
            continue

        # If website scrape returned nothing, fall back to GitHub commit emails.
        if not result:
            try:
                gh = find_company_email_github(name=c.get("name"), domain=c.get("domain"))
                if gh:
                    result = {
                        "email": gh["email"],
                        "source_url": gh["source_url"],
                        "priority": 50,  # mid-tier — between careers@ (low number) and generic info@
                    }
                    print(f"  ↳ github fallback: {gh.get('ranked_via')} from {gh['source_url']}")
            except Exception as e:  # noqa: BLE001
                print(f"  ! github fallback for {c['name']}: {e}")

        if result:
            updates = {
                "contact_email": result["email"],
                "contact_email_source": result["source_url"],
                "contact_email_priority": result["priority"],
                "contact_email_checked_at": "now()",
            }
            # If we resolved the website from a name guess, persist it.
            if not c.get("website") and result.get("resolved_website"):
                updates["website"] = result["resolved_website"]
            db().table("companies").update(updates).eq("id", c["id"]).execute()
            n = _propagate_to_jobs(c["id"], result["email"])
            propagated_total += n
            print(f"  ✓ {c['name'][:30]:30} -> {result['email']}  (+{n} jobs)")
            found += 1
        else:
            db().table("companies").update({
                "contact_email_checked_at": "now()",
            }).eq("id", c["id"]).execute()
            print(f"  · {c['name']}: no email found")
            no_match += 1

        time.sleep(0.3)  # gentle rate limit across companies

    print(f"\nfound={found} no_match={no_match} errored={errored} propagated_to_jobs={propagated_total}")


if __name__ == "__main__":
    main()
