"""Send all ready_to_send outreaches up to the daily cap.

Run as a separate workflow so you can keep this manual-approval-only by
disabling the cron and triggering by hand. Default (cron-enabled) will send
silently up to settings.daily_send_limit per UTC day.
"""
from __future__ import annotations

import argparse

from .agents.sender import send_outreach
from .db import db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=20)
    args = ap.parse_args()

    rows = (
        db().table("outreach").select("id").eq("stage", "ready_to_send")
        .order("created_at").limit(args.max).execute()
    ).data or []

    sent = skipped = failed = 0
    for r in rows:
        result = send_outreach(r["id"])
        if result.get("ok"):
            sent += 1
            print(f"  ✓ sent {r['id']} -> {result['share_url']}")
        elif result.get("skipped"):
            skipped += 1
            print(f"  · skipped {r['id']}: {result['reason']}")
        else:
            failed += 1
            print(f"  ✗ failed {r['id']}: {result.get('error')}")

    print(f"sent={sent} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
