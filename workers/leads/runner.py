"""Lead pipeline orchestrator.

Flow:
  1. Run each scraper (DDG search / software-review aggregators) → RawLead iterator.
  2. Upsert into `leads` table by (source, source_url). New rows get
     status='new' and no fit_score yet.
  3. For every row where fit_score IS NULL (new or never-classified), call
     Haiku to classify as a consulting buyer. Persist fit_score, classification,
     company_name, reasoning, scored_at.

The classifier scores for CONSULTING-BUYER fit (identifiable company + automation
stack + SMB size + decision-maker reachable), not Vicidial-specific fit. Existing
Vicidial leads remain tagged with lead_kind='vicidial'; new leads come in as
lead_kind='consulting' via base.py / source classes.

Usage:
  python -m workers.leads.runner                 # full run
  python -m workers.leads.runner --scrape-only   # discover, no classify
  python -m workers.leads.runner --classify-only # score existing unscored
  python -m workers.leads.runner --dry-run       # print counts, no writes
  python -m workers.leads.runner --max-classify 100
"""
from __future__ import annotations

import argparse
import time
from dataclasses import asdict
from typing import Iterable

from ..db import db
from .base import LeadSource, RawLead
from .classifier import classify_lead

# Import sources here so the runner is the single source of truth on which
# scrapers are active. To disable one for a run, comment it out.
#
# 2026-05 pivot:
#   - dropped forum + reddit (no anonymous-poster outreach)
#   - dropped software_review (SoftwareAdvice/Capterra are Next.js SPAs;
#     reviews hydrate client-side and our BeautifulSoup parser only saw
#     empty shells. The signal still flows through DDG snippets, so we
#     doubled down on DDG with 58 consulting-buyer queries instead.)
from .google_vicidial import source as google_source

SOURCES: list[LeadSource] = [
    google_source,
]


def _ingest_one(lead: RawLead, dry_run: bool) -> tuple[bool, bool]:
    """Insert or update one lead. Returns (is_new, errored)."""
    if lead.source_url.startswith("_error:"):
        # Scraper-level error — log to worker_runs by returning errored=True.
        return False, True

    payload = {
        "lead_kind": "vicidial",
        "source": lead.source,
        "source_url": lead.source_url,
        "title": (lead.title or "")[:500] or None,
        "company_name": lead.company_guess,
        "company_domain": lead.company_domain,
        "excerpt": (lead.excerpt or "")[:2000] or None,
        "signal_kind": lead.signal_kind,
        "posted_at": lead.posted_at,
        "raw_json": lead.raw_json or {},
    }
    if dry_run:
        return True, False

    # Check existence by (source, source_url).
    existing = (
        db().table("leads").select("id")
        .eq("source", lead.source).eq("source_url", lead.source_url).limit(1).execute()
    )
    if existing.data:
        # Update only the fields that change between runs (excerpt may
        # refresh on a forum thread); never overwrite fit_score/classification.
        db().table("leads").update({
            "title": payload["title"],
            "excerpt": payload["excerpt"],
            "raw_json": payload["raw_json"],
        }).eq("id", existing.data[0]["id"]).execute()
        return False, False

    db().table("leads").insert(payload).execute()
    return True, False


def scrape_all(*, dry_run: bool = False) -> dict:
    found = 0
    new = 0
    errored = 0
    by_source: dict[str, dict[str, int]] = {}
    for src in SOURCES:
        s_found = s_new = s_err = 0
        start = time.time()
        try:
            for lead in src.discover():
                s_found += 1
                is_new, was_err = _ingest_one(lead, dry_run)
                if was_err:
                    s_err += 1
                elif is_new:
                    s_new += 1
        except Exception as e:
            print(f"[{src.slug}] FATAL: {e}")
            s_err += 1
        elapsed = round(time.time() - start, 1)
        by_source[src.slug] = {"found": s_found, "new": s_new, "errors": s_err, "elapsed_s": elapsed}
        print(f"[{src.slug}] found={s_found} new={s_new} errors={s_err} elapsed={elapsed}s")
        found += s_found
        new += s_new
        errored += s_err
    return {"found": found, "new": new, "errors": errored, "by_source": by_source}


def classify_unscored(*, max_classify: int, dry_run: bool = False) -> dict:
    res = (
        db().table("leads").select("id,source_url,title,excerpt")
        .is_("fit_score", "null")
        .order("created_at", desc=False)
        .limit(max_classify)
        .execute()
    )
    rows = res.data or []
    print(f"unscored leads to classify: {len(rows)} (cap {max_classify})")
    scored = 0
    prospects = 0
    for row in rows:
        if dry_run:
            scored += 1
            continue
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
    return {"scored": scored, "prospects": prospects}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scrape-only", action="store_true")
    ap.add_argument("--classify-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-classify", type=int, default=300,
                    help="cap on Haiku calls per run (cost guard)")
    args = ap.parse_args()

    if args.classify_only:
        out = classify_unscored(max_classify=args.max_classify, dry_run=args.dry_run)
        print(f"CLASSIFY DONE: scored={out['scored']} prospects={out['prospects']}")
        return

    scrape_summary = scrape_all(dry_run=args.dry_run)
    print(f"SCRAPE DONE: found={scrape_summary['found']} "
          f"new={scrape_summary['new']} errors={scrape_summary['errors']}")

    if not args.scrape_only:
        out = classify_unscored(max_classify=args.max_classify, dry_run=args.dry_run)
        print(f"CLASSIFY DONE: scored={out['scored']} prospects={out['prospects']}")


if __name__ == "__main__":
    main()
