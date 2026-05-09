"""Daily pipeline orchestrator.

Runs after the discover step (so jobs/companies are fresh) and walks new
jobs through: research → fit gate → outreach create → letter draft.
Sending is handled by a separate workflow (send.yml) so review/approval
can be added later.

Usage:
  python -m workers.pipeline                # process all qualified jobs
  python -m workers.pipeline --max 5        # cap how many to advance
"""
from __future__ import annotations

import argparse
import time

from .agents.letter import draft_letter
from .agents.research import research_company
from .db import db
from .process import log_step


def _new_jobs(limit: int) -> list[dict]:
    return (
        db().table("jobs").select("*")
        .eq("status", "new")
        .order("created_at", desc=True).limit(limit).execute()
    ).data or []


def _company_needs_research(company_id: str) -> bool:
    res = db().table("companies").select("last_researched_at, fit_score").eq("id", company_id).single().execute().data
    return res.get("last_researched_at") is None


def _ensure_outreach(job_id: str, company_id: str) -> str:
    existing = (
        db().table("outreach").select("id").eq("job_id", job_id).limit(1).execute()
    ).data
    if existing:
        return existing[0]["id"]
    settings = db().table("settings").select("pitch_default").eq("id", 1).single().execute().data
    return db().table("outreach").insert({
        "job_id": job_id,
        "company_id": company_id,
        "pitch_angle": settings["pitch_default"],
        "stage": "researching",
    }).execute().data[0]["id"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=20, help="max jobs to advance this run")
    args = ap.parse_args()

    settings = db().table("settings").select("min_fit_score").eq("id", 1).single().execute().data
    min_fit = settings["min_fit_score"]

    jobs = _new_jobs(args.max)
    advanced = qualified = skipped = 0

    for job in jobs:
        company_id = job["company_id"]
        outreach_id = _ensure_outreach(job["id"], company_id)

        log_step(outreach_id, kind="source_discovered",
                 title=f"Found in source: {job['title']}",
                 summary=f"Title: {job['title']}\n\nSource URL: {job.get('url') or '—'}",
                 inputs={"job_id": job["id"]}, outputs={"posted_at": job.get("posted_at")})

        if _company_needs_research(company_id):
            try:
                research_company(company_id, outreach_id=outreach_id)
            except Exception as e:  # noqa: BLE001
                db().table("jobs").update({"status": "skipped", "skip_reason": f"research_failed: {e}"}).eq("id", job["id"]).execute()
                db().table("outreach").update({"stage": "lost", "lost_reason": f"research_failed: {e}"}).eq("id", outreach_id).execute()
                skipped += 1
                continue

        company = db().table("companies").select("fit_score, name").eq("id", company_id).single().execute().data
        fit = company.get("fit_score") or 0

        log_step(outreach_id, kind="fit_scored",
                 title=f"Fit score: {fit}/100",
                 summary=f"Threshold for proceeding is {min_fit}/100. " +
                         ("Proceeding to letter draft." if fit >= min_fit else "Below threshold — not pursuing."),
                 inputs={"min_fit": min_fit}, outputs={"fit_score": fit})

        if fit < min_fit:
            db().table("jobs").update({"status": "skipped", "skip_reason": f"fit_below_min ({fit}<{min_fit})"}).eq("id", job["id"]).execute()
            db().table("outreach").update({"stage": "lost", "lost_reason": "fit_below_threshold"}).eq("id", outreach_id).execute()
            skipped += 1
            continue

        try:
            draft_letter(outreach_id)
            db().table("jobs").update({"status": "qualified"}).eq("id", job["id"]).execute()
            qualified += 1
            advanced += 1
        except Exception as e:  # noqa: BLE001
            db().table("outreach").update({"stage": "drafting"}).eq("id", outreach_id).execute()
            print(f"  ⚠ letter draft failed for outreach {outreach_id}: {e}")

    print(f"advanced={advanced} qualified={qualified} skipped={skipped} considered={len(jobs)}")


if __name__ == "__main__":
    main()
