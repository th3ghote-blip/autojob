"""Cheap title triage: archive obvious-reject titles + prioritise LLM scoring.

Two passes against status=new + qualifier_checked_at=null:

  Pass 1 (free, instant) — regex on title only:
    - TIER_1_LIKELY patterns (FDE / applied / solutions / founding eng / etc.)
        → leave alone, scored in pass 2
    - HARD_REJECT patterns (junior / staff / DevOps / Account Exec / etc.)
        → archive directly with skip_reason='title_pattern_reject'
    - AMBIGUOUS (anything else) → leave for the regular cron

  Pass 2 (Haiku, ~$0.001/job) — LLM qualifier on the TIER_1_LIKELY bucket only.
    These titles look like real matches; we want them ranked TODAY, not over
    the next ~10 days of cron processing.

Usage:
  python -m workers.triage              # archive rejects + score tier-1 titles
  python -m workers.triage --dry-run    # just show counts, no writes
"""
from __future__ import annotations

import argparse
import re
import time
from typing import Iterable

from .agents.qualify import qualify_job
from .db import db


# Titles we want LLM-scored first. Matches Forward Deployed, Applied,
# Solutions, Founding, etc. (mirrors profile.yaml tier_1).
TIER_1_LIKELY = re.compile(
    r"\b("
    r"forward[- ]deployed|"
    r"applied (ai|ml|engineer|scientist)|"
    r"founding (engineer|eng|product engineer|software engineer|full[- ]?stack)|"
    r"first (engineer|technical|hire)|"
    r"founder'?s associate|chief of staff|"
    r"solutions (engineer|architect)|"
    r"customer (engineer|success engineer)|"
    r"implementation engineer|"
    r"automation engineer|"
    r"internal tools|"
    r"ai (engineer|integration|integrations engineer|generalist)|"
    r"deployed engineer|"
    r"workflow|"
    r"base44"
    r")\b",
    re.I,
)

# Junk we never want to spend tokens on.
HARD_REJECT = re.compile(
    r"\b("
    r"intern|internship|"
    r"junior|jr\.?|entry[- ]level|associate engineer|"
    r"staff (engineer|software|ml|machine|scientist)|principal|distinguished|"
    r"research (scientist|engineer|fellow)|pretraining|"
    r"data scientist|quantitative|quant analyst|"
    r"mlops|"
    r"sre|site reliability|"
    r"devops|"
    r"infrastructure engineer|infra engineer|"
    r"platform engineer|"
    r"security engineer|compliance|risk|"
    r"office manager|executive assistant|receptionist|secretary|"
    r"recruiter|talent (acquisition|partner)|"
    r"sales (development|representative|rep)|account executive|business development|"
    r"marketing|content (manager|writer|strategist)|"
    r"director of|head of|vp of|vice president|chief (executive|operating|financial)|cto|cfo|coo|ceo|"
    r"hardware|firmware|fpga|"
    r"clinical|biology|chemistry|pharmacist|nurse|"
    r"customer support|customer service|"
    r"finance|accountant|bookkeeper|"
    r"legal counsel|paralegal"
    r")\b",
    re.I,
)


def _pull_all_unscored() -> list[dict]:
    """Iterate Supabase REST in pages of 1000 to grab everything."""
    out: list[dict] = []
    offset = 0
    while True:
        # supabase-py respects range() via .range()
        res = (
            db().table("jobs")
            .select("id, title")
            .eq("status", "new")
            .is_("qualifier_checked_at", "null")
            .range(offset, offset + 999)
            .execute()
        ).data or []
        out.extend(res)
        if len(res) < 1000:
            break
        offset += 1000
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print counts without writing")
    ap.add_argument("--max-llm", type=int, default=400, help="cap LLM-scored tier-1 candidates")
    args = ap.parse_args()

    jobs = _pull_all_unscored()
    print(f"pool: {len(jobs)} unscored jobs")

    tier1, reject, ambig = [], [], []
    for j in jobs:
        t = (j.get("title") or "").strip()
        if not t:
            reject.append(j)
            continue
        if TIER_1_LIKELY.search(t):
            tier1.append(j)
        elif HARD_REJECT.search(t):
            reject.append(j)
        else:
            ambig.append(j)

    print(f"  tier_1_likely (LLM-score now): {len(tier1)}")
    print(f"  hard_reject   (archive now):   {len(reject)}")
    print(f"  ambiguous     (cron handles):  {len(ambig)}")

    if args.dry_run:
        return

    # ─── Pass 1: archive rejects (no LLM) ───────────────────────────────────
    archived = 0
    for j in reject:
        db().table("jobs").update({
            "status": "archived",
            "skip_reason": "title_pattern_reject",
            "qualifier_checked_at": "now()",
        }).eq("id", j["id"]).execute()
        archived += 1
        if archived % 50 == 0:
            print(f"  archived {archived}/{len(reject)}…")
    print(f"  ✓ archived {archived} reject-titled jobs")

    # ─── Pass 2: LLM-score tier-1 candidates (Haiku, ~$0.001 each) ──────────
    to_score = tier1[: args.max_llm]
    print(f"\nLLM-scoring {len(to_score)} tier-1-titled jobs…")
    hits = 0
    errors = 0
    for i, j in enumerate(to_score, 1):
        try:
            r = qualify_job(j["id"], outreach_id=None, log_to_process=False, write_to_job=True)
            tier = r.get("realism_tier", "?")
            fit = r.get("fit_score", 0)
            if tier in ("tier_1_apply", "tier_2_consulting"):
                hits += 1
                print(f"  [{i:>3}/{len(to_score)}]  fit={fit:>3}  {tier:18}  {j['title'][:70]}")
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"  ! {j['id']}: {e}")
        time.sleep(0.05)

    print(f"\nDONE. archived={archived}  scored={len(to_score)}  matches={hits}  errors={errors}")


if __name__ == "__main__":
    main()
