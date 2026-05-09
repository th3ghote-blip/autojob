"""Supabase client + small helpers shared by all workers."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv()


@lru_cache(maxsize=1)
def db() -> Client:
    url = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def get_settings() -> dict:
    res = db().table("settings").select("*").eq("id", 1).single().execute()
    return res.data


def get_source(slug: str) -> dict | None:
    res = db().table("sources").select("*").eq("slug", slug).maybe_single().execute()
    return res.data if res else None


def list_enabled_sources() -> list[dict]:
    res = db().table("sources").select("*").eq("enabled", True).order("slug").execute()
    return res.data or []


def upsert_company(name: str, domain: str | None, **fields) -> str:
    """Insert or update a company by domain (preferred) or name. Returns id."""
    payload = {"name": name, **fields}
    if domain:
        payload["domain"] = domain.lower()
        # Try domain match first.
        existing = (
            db().table("companies").select("id").eq("domain", domain.lower()).limit(1).execute()
        )
    else:
        existing = (
            db().table("companies").select("id").eq("name", name).limit(1).execute()
        )
    if existing.data:
        cid = existing.data[0]["id"]
        db().table("companies").update(payload).eq("id", cid).execute()
        return cid
    return db().table("companies").insert(payload).execute().data[0]["id"]


def upsert_job_raw(source_id: str, external_id: str, payload_json: dict, payload_html: str | None = None) -> str:
    res = db().table("job_raw").insert({
        "source_id": source_id,
        "external_id": external_id,
        "payload_json": payload_json,
        "payload_html": payload_html,
    }).execute()
    return res.data[0]["id"]


def upsert_job(*, source_id: str, company_id: str, external_id: str, raw_id: str, **fields) -> tuple[str, bool]:
    """Insert a job; on conflict (source_id, external_id) do nothing. Returns (id, was_new)."""
    existing = (
        db().table("jobs").select("id")
        .eq("source_id", source_id).eq("external_id", external_id).limit(1).execute()
    )
    if existing.data:
        return existing.data[0]["id"], False
    res = db().table("jobs").insert({
        "source_id": source_id,
        "company_id": company_id,
        "external_id": external_id,
        "raw_id": raw_id,
        **fields,
    }).execute()
    return res.data[0]["id"], True


def start_worker_run(source_id: str | None, kind: str, github_run_url: str | None = None) -> str:
    res = db().table("worker_runs").insert({
        "source_id": source_id,
        "worker_kind": kind,
        "status": "running",
        "github_run_url": github_run_url,
    }).execute()
    return res.data[0]["id"]


def finish_worker_run(run_id: str, *, status: str, found: int = 0, new: int = 0,
                      skipped: int = 0, errors: list | None = None,
                      duration_ms: int | None = None) -> None:
    db().table("worker_runs").update({
        "status": status,
        "found_count": found,
        "new_count": new,
        "skipped_count": skipped,
        "error_count": len(errors or []),
        "errors_json": errors,
        "duration_ms": duration_ms,
        "finished_at": "now()",
    }).eq("id", run_id).execute()


def update_source_last_run(source_id: str, status: str, error: str | None = None) -> None:
    db().table("sources").update({
        "last_run_at": "now()",
        "last_status": status,
        "last_error": error,
    }).eq("id", source_id).execute()
