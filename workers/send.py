"""Send queued outreaches.

Two modes:

  python -m workers.send --outreach <uuid>
      Send exactly that one outreach (force=True so stage doesn't have to be
      ready_to_send — used by the /jobs/[id] Send button).

  python -m workers.send --max 20
      Batch: send every ready_to_send outreach up to the daily cap.
"""
from __future__ import annotations

import argparse

from .agents.sender import send_outreach
from .db import db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outreach", help="single-send mode: outreach UUID")
    ap.add_argument("--test-to", help="if set, redirect the send to this address instead of the recruiter")
    ap.add_argument("--max", type=int, default=20)
    args = ap.parse_args()

    if args.outreach:
        result = send_outreach(args.outreach, force=True, test_to=args.test_to)
        label = "TEST" if args.test_to else "sent"
        if result.get("ok"):
            target = args.test_to or "recruiter"
            print(f"  ✓ {label} {args.outreach} -> {target}  share_url={result.get('share_url')}")
        elif result.get("skipped"):
            print(f"  · skipped {args.outreach}: {result['reason']}")
        else:
            print(f"  ✗ failed {args.outreach}: {result.get('error')}")
        return

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
