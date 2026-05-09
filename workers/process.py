"""Append-only logger for the AI process trail shown to recruiters.

Every meaningful step the agent takes for an outreach gets a row in
process_steps. The /share/[token] page renders these as a timeline so the
recruiter can see exactly how the agent found and pitched them — which is
itself the demonstration of the automation we are selling.
"""
from __future__ import annotations

from typing import Any

from .db import db


def log_step(
    outreach_id: str,
    *,
    kind: str,
    title: str,
    summary: str | None = None,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    model: str | None = None,
    tokens_used: int | None = None,
    duration_ms: int | None = None,
    visible_to_recruiter: bool = True,
) -> str:
    """Append one process step. step_order is computed server-side."""
    next_order = (
        db().table("process_steps").select("step_order")
        .eq("outreach_id", outreach_id).order("step_order", desc=True).limit(1).execute()
    ).data
    step_order = (next_order[0]["step_order"] + 1) if next_order else 1
    res = db().table("process_steps").insert({
        "outreach_id": outreach_id,
        "step_order": step_order,
        "kind": kind,
        "title": title,
        "summary": summary,
        "input_redacted_json": _redact(inputs),
        "output_redacted_json": _redact(outputs),
        "model": model,
        "tokens_used": tokens_used,
        "duration_ms": duration_ms,
        "visible_to_recruiter": visible_to_recruiter,
    }).execute()
    return res.data[0]["id"]


def _redact(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip secrets from anything we persist for recruiter view."""
    if payload is None:
        return None
    redacted: dict[str, Any] = {}
    for k, v in payload.items():
        if isinstance(v, str) and (
            "key" in k.lower() or "token" in k.lower() or "password" in k.lower()
        ):
            redacted[k] = "***"
        elif isinstance(v, str) and len(v) > 4000:
            redacted[k] = v[:4000] + f"\n…[truncated, {len(v)} chars total]"
        else:
            redacted[k] = v
    return redacted
