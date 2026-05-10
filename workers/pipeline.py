"""Pipeline orchestrator — qualifier (optional, sort-only) + research + letter draft.

Two modes:

  python -m workers.pipeline --job <uuid>
      Single-job mode: skip qualifier gate, ALWAYS run research + letter.
      Used by the /jobs page "Draft" button via workflow_dispatch.

  python -m workers.pipeline --max 50
      Batch mode (default): walk N new jobs, qualifier writes fit_score +
      tier as metadata to outreach.notes (sort key, NOT a gate). Letters are
      NOT drafted in batch mode — user picks which to draft via the dashboard.
"""
from __future__ import annotations

import argparse
import json
import time

from .agents.letter import draft_letter
from .agents.qualify import qualify_job
from .agents.research import research_company
from .db import db
from .process import log_step


def _new_jobs(limit: int) -> list[dict]:
    """Score-worthy jobs: status=new, has contact_email (so we can actually
    send), and posted within the last ~60 days. Ordered most-recent first.
    """
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    return (
        db().table("jobs").select("*")
        .eq("status", "new")
        .not_.is_("contact_email", "null")
        .gte("posted_at", cutoff)
        .is_("qualifier_checked_at", "null")
        .order("posted_at", desc=True).limit(limit).execute()
    ).data or []


def _ensure_outreach(job_id: str, company_id: str) -> str:
    existing = (
        db().table("outreach").select("id").eq("job_id", job_id).limit(1).execute()
    ).data
    if existing:
        return existing[0]["id"]
    return db().table("outreach").insert({
        "job_id": job_id,
        "company_id": company_id,
        "stage": "researching",
    }).execute().data[0]["id"]


def draft_one(job_id: str) -> dict:
    """Single-job flow: research + letter, regardless of qualifier verdict.

    Idempotent on re-draft: if the outreach already has letters, we skip the
    source_discovered + qualifier steps (no duplicate trail entries) and just
    produce a new letter version.
    """
    started = time.time()
    job = db().table("jobs").select("*, companies(*)").eq("id", job_id).single().execute().data
    company_id = job["company_id"]
    outreach_id = _ensure_outreach(job_id, company_id)

    # Has this outreach already produced any letters? If so, this is a re-draft.
    existing_letters = (
        db().table("letters").select("id", count="exact", head=True)
        .eq("outreach_id", outreach_id).execute()
    )
    is_redraft = (existing_letters.count or 0) > 0

    if not is_redraft:
        # First-time flow: full trail.
        log_step(outreach_id, kind="source_discovered",
                 title=f"Selected by user: {job['title']}",
                 summary=f"User clicked Draft from /jobs.\n\nTitle: {job['title']}\nSource URL: {job.get('url') or '—'}",
                 inputs={"job_id": job_id, "manual": True},
                 outputs={"posted_at": job.get("posted_at")})

        try:
            decision = qualify_job(job_id, outreach_id=outreach_id)
            pitch_angle = decision.get("pitch_angle") or "consulting"
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ qualifier failed (proceeding anyway): {e}")
            pitch_angle = "consulting"

        db().table("outreach").update({
            "pitch_angle": pitch_angle,
            "stage": "researching",
        }).eq("id", outreach_id).execute()

        company = db().table("companies").select("last_researched_at").eq("id", company_id).single().execute().data
        if not company.get("last_researched_at"):
            try:
                research_company(company_id, outreach_id=outreach_id)
            except Exception as e:  # noqa: BLE001
                log_step(outreach_id, kind="company_researched",
                         title="Company research failed (proceeding anyway)",
                         summary=f"Error: {e}", inputs={}, outputs={})
    else:
        print(f"  re-draft for outreach {outreach_id} — skipping source/qualifier/research trail entries")

    # Draft the letter (always — produces v1 or v(N+1)).
    draft_letter(outreach_id)
    db().table("jobs").update({"status": "qualified"}).eq("id", job_id).execute()
    print(f"drafted letter for outreach {outreach_id} in {int((time.time() - started) * 1000)}ms")
    return {"outreach_id": outreach_id, "redraft": is_redraft}


def batch_score(max_jobs: int) -> None:
    """Batch qualifier — scores has-email + recent jobs, writes fit_score
    directly to jobs table. No outreach rows created. No letters drafted.
    """
    jobs = _new_jobs(max_jobs)
    scored = errored = 0
    fit_buckets = {"tier_1_apply": 0, "tier_2_consulting": 0, "retainer": 0, "reject": 0}
    print(f"scoring {len(jobs)} jobs (has email, posted last 60d, not yet checked)…")
    for job in jobs:
        try:
            decision = qualify_job(
                job["id"],
                outreach_id=None,
                log_to_process=False,
                write_to_job=True,
            )
            tier = decision.get("realism_tier") or "reject"
            fit_buckets[tier] = fit_buckets.get(tier, 0) + 1
            scored += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ score failed for {job['id']}: {e}")
            # Still mark checked so we don't retry forever.
            db().table("jobs").update({"qualifier_checked_at": "now()"}).eq("id", job["id"]).execute()
            errored += 1
    print(f"\nconsidered={len(jobs)} scored={scored} errored={errored}")
    print(f"tiers: {fit_buckets}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", help="single-job mode: process this job UUID through to letter")
    ap.add_argument("--max", type=int, default=50, help="batch mode: max jobs to score")
    args = ap.parse_args()

    if args.job:
        draft_one(args.job)
    else:
        batch_score(args.max)


if __name__ == "__main__":
    main()
