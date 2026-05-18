"""ATS-job → consulting-lead pump.

Reads from the existing `jobs` table (Greenhouse/Lever/Ashby scraped via
`workers/sources/*`), filters to job titles that signal a consulting buyer
(company is hiring out an automation gap they could pay AiAppGenius to
fill instead), and writes matches into the `leads` table.

Why this exists: the job-application pipeline auto-archives ops/automation
titles as rejects for Andrew-as-hire. But "Acme hiring Ops Manager" is
exactly a consulting prospect. We need a second pass with a different lens.

Buyer-signal title patterns (case-insensitive):
  - "head of ai" | "ai lead" | "chief ai" | "vp ai" | "director of ai"
  - "ai strategy" | "ai advisor" | "ai consultant" | "ai transformation"
  - "ai implementation" | "ai program"
  - "fractional cto" | "interim cto"
  - "head of automation" | "director of automation" | "automation lead"
  - "process automation" | "rpa" | "workflow automation"
  - "head of operations" | "head of ops" | "ops manager"
  - "chief of staff" | "head of revenue operations" | "revops"
  - "head of customer ops" | "head of cx ops"
  - "implementation manager" | "implementation lead"

Each match → leads row with:
  - source = 'ats_consulting'
  - source_url = job.url
  - title = job.title (so the classifier sees the role hint)
  - excerpt = job.description (truncated)
  - raw_json with company_name pulled from companies table
"""
from __future__ import annotations

import argparse
import re
import time
from typing import Any

from ..db import db
from .classifier import classify_lead

# Title regex — case-insensitive — only roles signaling a consulting buyer.
BUYER_TITLES = re.compile(
    r"\b("
    r"head of ai|ai lead|chief ai|vp ai|director of ai|"
    r"ai strategy|ai advisor|ai consultant|ai transformation|"
    r"ai implementation|ai program(?: manager| lead)?|"
    r"fractional cto|interim cto|"
    r"head of automation|director of automation|automation lead|"
    r"process automation|rpa|workflow automation|"
    r"head of operations|head of ops|ops manager|operations manager|"
    r"chief of staff|head of revenue operations|revops|"
    r"head of customer ops|head of cx ops|"
    r"implementation manager|implementation lead"
    r")\b",
    re.I,
)


def _pull_candidate_jobs(limit: int) -> list[dict]:
    """Pull jobs whose title matches a buyer-signal pattern. We don't filter
    on status — even archived (auto-rejected for Andrew-as-hire) jobs are
    valid consulting prospects."""
    # PostgREST `or=()` for multiple ilike patterns. Splitting by the most
    # discriminative tokens — anything with these in the title becomes a
    # candidate, the Python regex above is the precise filter.
    patterns = [
        "head of ai", "ai lead", "ai strategy", "ai advisor", "ai consultant",
        "ai transformation", "ai implementation", "ai program",
        "fractional cto", "interim cto",
        "head of automation", "automation lead", "process automation",
        "workflow automation", "rpa",
        "head of operations", "head of ops", "ops manager", "operations manager",
        "chief of staff", "head of revenue operations", "revops",
        "head of customer ops", "head of cx ops",
        "implementation manager", "implementation lead",
    ]
    or_clause = ",".join(f"title.ilike.*{p.replace(' ', '%20')}*" for p in patterns)
    res = (
        db().table("jobs")
        .select("id,title,description,url,company_id,location,remote,posted_at")
        .or_(or_clause)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = res.data or []
    # Tighten with the local regex — the broad ilike may catch substrings.
    return [r for r in rows if BUYER_TITLES.search(r["title"] or "")]


def _company_name(company_id: str | None) -> str | None:
    if not company_id:
        return None
    res = db().table("companies").select("name,domain").eq("id", company_id).limit(1).execute()
    if res.data:
        return res.data[0].get("name")
    return None


def _ingest(job: dict, dry_run: bool) -> tuple[bool, bool]:
    """Upsert one job into leads. Returns (is_new, errored)."""
    url = job.get("url")
    if not url:
        return False, True
    if dry_run:
        return True, False
    existing = (
        db().table("leads").select("id")
        .eq("source", "ats_consulting").eq("source_url", url).limit(1).execute()
    )
    if existing.data:
        return False, False

    company_name = _company_name(job.get("company_id"))
    payload = {
        "lead_kind": "consulting",
        "source": "ats_consulting",
        "source_url": url,
        "title": (job.get("title") or "")[:500] or None,
        "company_name": company_name,
        "excerpt": (job.get("description") or "")[:2000] or None,
        "signal_kind": "job_post",
        "posted_at": job.get("posted_at"),
        "raw_json": {
            "job_id": job.get("id"),
            "location": job.get("location"),
            "remote": job.get("remote"),
            "company_id": job.get("company_id"),
        },
    }
    db().table("leads").insert(payload).execute()
    return True, False


def run(*, max_jobs: int, max_classify: int, dry_run: bool) -> dict:
    cand = _pull_candidate_jobs(limit=max_jobs)
    print(f"candidate jobs (title-matched): {len(cand)}")
    new = 0
    for j in cand:
        is_new, _ = _ingest(j, dry_run)
        if is_new:
            new += 1
    print(f"new leads inserted: {new}")

    # Now classify any unscored ats_consulting leads (cap-bound to keep cost predictable).
    if dry_run:
        return {"candidates": len(cand), "inserted": new, "scored": 0, "prospects": 0}

    res = (
        db().table("leads").select("id,source_url,title,excerpt")
        .eq("source", "ats_consulting").is_("fit_score", "null")
        .order("created_at", desc=False).limit(max_classify).execute()
    )
    rows = res.data or []
    print(f"unscored ats_consulting leads: {len(rows)} (cap {max_classify})")
    scored = 0
    prospects = 0
    for row in rows:
        result = classify_lead(
            source_url=row["source_url"],
            title=row.get("title"),
            excerpt=row.get("excerpt"),
        )
        db().table("leads").update({
            "classification": result["classification"],
            "fit_score": result["fit_score"],
            "install_size_guess": result["install_size_guess"],
            "company_name": result.get("company_name"),
            "signal_kind": result.get("signal_kind"),
            "reasoning": result.get("reasoning"),
            "scored_at": "now()",
        }).eq("id", row["id"]).execute()
        scored += 1
        if result["classification"] == "prospect":
            prospects += 1
    return {"candidates": len(cand), "inserted": new, "scored": scored, "prospects": prospects}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-jobs", type=int, default=2000,
                    help="cap on candidate jobs pulled from `jobs` table")
    ap.add_argument("--max-classify", type=int, default=400,
                    help="cap on Haiku calls in this run")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out = run(max_jobs=args.max_jobs, max_classify=args.max_classify, dry_run=args.dry_run)
    print(
        f"ATS-CONSULTING DONE: candidates={out['candidates']} "
        f"inserted={out['inserted']} scored={out['scored']} prospects={out['prospects']}"
    )


if __name__ == "__main__":
    main()
