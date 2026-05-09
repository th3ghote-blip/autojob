"""Discover-only entry point used by GitHub Actions cron.

Loops through enabled sources, runs each one, writes companies + jobs +
job_raw rows, and records a worker_runs row per source for observability.

Usage:
    python -m workers.runner                       # all enabled sources
    python -m workers.runner --source hn_whoshiring # one source
    python -m workers.runner --source hn_whoshiring --once --limit 5
"""
from __future__ import annotations

import argparse
import os
import time
import traceback
from typing import Any

from .db import (
    db,
    finish_worker_run,
    list_enabled_sources,
    start_worker_run,
    update_source_last_run,
    upsert_company,
    upsert_job,
    upsert_job_raw,
)
from .sources import load


def run_source(src: dict[str, Any], *, limit: int | None = None) -> dict[str, int]:
    """Discover + parse + persist one source. Returns counts."""
    slug = src["slug"]
    config = src.get("config_json") or {}
    found = new = skipped = 0
    errors: list[dict] = []

    started_ms = time.time()
    run_id = start_worker_run(
        source_id=src["id"],
        kind="discover",
        github_run_url=os.environ.get("GITHUB_RUN_URL"),
    )

    try:
        impl = load(slug)
    except Exception as e:
        finish_worker_run(
            run_id, status="error",
            errors=[{"stage": "load_source", "error": str(e), "trace": traceback.format_exc()}],
        )
        update_source_last_run(src["id"], status="error", error=f"load failed: {e}")
        return {"found": 0, "new": 0, "skipped": 0, "errors": 1}

    try:
        for raw in impl.discover(config):
            found += 1
            if limit is not None and new >= limit:
                break
            try:
                parsed = impl.parse(raw)
                if parsed is None:
                    skipped += 1
                    continue
                raw_id = upsert_job_raw(
                    source_id=src["id"],
                    external_id=raw.external_id,
                    payload_json=raw.payload_json,
                    payload_html=raw.payload_html,
                )
                company_id = upsert_company(
                    name=parsed.company_name,
                    domain=parsed.company_domain,
                    website=parsed.company_website,
                )
                _, was_new = upsert_job(
                    source_id=src["id"],
                    company_id=company_id,
                    external_id=parsed.external_id,
                    raw_id=raw_id,
                    title=parsed.title,
                    description=parsed.description,
                    comp_min=parsed.comp_min,
                    comp_max=parsed.comp_max,
                    comp_currency=parsed.comp_currency,
                    location=parsed.location,
                    remote=parsed.remote,
                    employment_type=parsed.employment_type,
                    contact_name=parsed.contact_name,
                    contact_email=parsed.contact_email,
                    contact_role=parsed.contact_role,
                    url=parsed.url,
                    posted_at=parsed.posted_at,
                )
                if was_new:
                    new += 1
                else:
                    skipped += 1
            except Exception as e:
                errors.append({
                    "stage": "parse_or_persist",
                    "external_id": raw.external_id,
                    "error": str(e),
                })
        status = "ok" if not errors else ("partial" if new else "error")
    except Exception as e:
        status = "error"
        errors.append({"stage": "discover", "error": str(e), "trace": traceback.format_exc()})

    duration_ms = int((time.time() - started_ms) * 1000)
    finish_worker_run(
        run_id, status=status, found=found, new=new, skipped=skipped,
        errors=errors or None, duration_ms=duration_ms,
    )
    update_source_last_run(
        src["id"], status=status,
        error=errors[0]["error"] if errors and status == "error" else None,
    )
    return {"found": found, "new": new, "skipped": skipped, "errors": len(errors)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="run a single source slug instead of all enabled")
    ap.add_argument("--limit", type=int, help="cap new jobs per source (debugging)")
    ap.add_argument("--once", action="store_true", help="kept for symmetry; runner is single-pass")
    args = ap.parse_args()

    if args.source:
        res = db().table("sources").select("*").eq("slug", args.source).single().execute()
        sources = [res.data] if res.data else []
    else:
        sources = list_enabled_sources()

    totals = {"found": 0, "new": 0, "skipped": 0, "errors": 0}
    for src in sources:
        print(f"▶ {src['slug']}")
        counts = run_source(src, limit=args.limit)
        for k, v in counts.items():
            totals[k] = totals[k] + v
        print(f"  found={counts['found']} new={counts['new']} skipped={counts['skipped']} errors={counts['errors']}")

    print(f"\nTOTALS: {totals}")


if __name__ == "__main__":
    main()
