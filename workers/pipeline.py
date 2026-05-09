"""Daily pipeline orchestrator.

Walks new jobs through:
  qualify (cheap LLM screen against profile)
    -> if qualifies -> research the company -> draft letter
    -> if rejected  -> mark job/outreach as skipped with reason

Sending is handled by a separate workflow (send.yml).

Usage:
  python -m workers.pipeline                # process all new jobs
  python -m workers.pipeline --max 50       # cap how many to advance
"""
from __future__ import annotations

import argparse
import time

from .agents.letter import draft_letter
from .agents.qualify import qualify_job
from .agents.research import research_company
from .db import db
from .process import log_step


def _new_jobs(limit: int) -> list[dict]:
    return (
        db().table("jobs").select("*")
        .eq("status", "new")
        .order("created_at", desc=True).limit(limit).execute()
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=50, help="max jobs to advance this run")
    args = ap.parse_args()

    jobs = _new_jobs(args.max)
    qualified_n = skipped_n = drafted_n = 0

    for job in jobs:
        company_id = job["company_id"]
        outreach_id = _ensure_outreach(job["id"], company_id)

        log_step(outreach_id, kind="source_discovered",
                 title=f"Found in source: {job['title']}",
                 summary=f"Title: {job['title']}\n\nSource URL: {job.get('url') or '—'}",
                 inputs={"job_id": job["id"]}, outputs={"posted_at": job.get("posted_at")})

        # Qualify against profile (cheap Haiku call).
        try:
            decision = qualify_job(job["id"], outreach_id=outreach_id)
        except Exception as e:  # noqa: BLE001
            db().table("jobs").update({"status": "skipped", "skip_reason": f"qualify_failed: {e}"}).eq("id", job["id"]).execute()
            db().table("outreach").update({"stage": "lost", "lost_reason": "qualify_failed"}).eq("id", outreach_id).execute()
            skipped_n += 1
            continue

        if not decision.get("qualifies"):
            db().table("jobs").update({
                "status": "skipped",
                "skip_reason": decision.get("skip_reason") or "qualifier rejected",
            }).eq("id", job["id"]).execute()
            db().table("outreach").update({
                "stage": "lost",
                "lost_reason": decision.get("skip_reason") or "qualifier rejected",
            }).eq("id", outreach_id).execute()
            skipped_n += 1
            continue

        # Persist tier + pitch angle on the outreach row.
        pitch_angle = decision.get("pitch_angle") or "consulting"
        db().table("outreach").update({
            "pitch_angle": pitch_angle,
            "stage": "researching",
        }).eq("id", outreach_id).execute()

        # Company research (skip if recently done).
        company_row = db().table("companies").select("last_researched_at").eq("id", company_id).single().execute().data
        if not company_row.get("last_researched_at"):
            try:
                research_company(company_id, outreach_id=outreach_id)
            except Exception as e:  # noqa: BLE001
                # Research failure is recoverable — proceed to draft anyway with what we have.
                log_step(outreach_id, kind="company_researched",
                         title=f"Company research failed (proceeding anyway)",
                         summary=f"Error: {e}", inputs={}, outputs={})

        qualified_n += 1
        try:
            draft_letter(outreach_id)
            db().table("jobs").update({"status": "qualified"}).eq("id", job["id"]).execute()
            drafted_n += 1
        except Exception as e:  # noqa: BLE001
            db().table("outreach").update({"stage": "drafting"}).eq("id", outreach_id).execute()
            print(f"  ⚠ letter draft failed for outreach {outreach_id}: {e}")

    print(f"considered={len(jobs)} qualified={qualified_n} drafted={drafted_n} skipped={skipped_n}")


if __name__ == "__main__":
    main()
