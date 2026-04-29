#!/usr/bin/env python
"""
Backfill: author auto-listeners on every existing share.

For every share row in the xomify-shares table, write a listener row
(shareId, author_email) into xomify-share-listeners with source=author_create.
mark_listened is idempotent (uses if_not_exists for listenedAt + source) so
re-running this script is safe — already-marked rows update only the
updatedAt timestamp.

Usage:
    # From the repo root:
    AWS_PROFILE=xomify \
    SHARES_TABLE_NAME=xomify-shares \
    SHARE_LISTENERS_TABLE_NAME=xomify-share-listeners \
    .venv/bin/python scripts/backfill_author_listeners.py

    # Dry run (no writes — just count what WOULD be marked):
    .venv/bin/python scripts/backfill_author_listeners.py --dry-run

Env vars:
    AWS_PROFILE                       — AWS credential profile to use.
    AWS_DEFAULT_REGION                — Defaults to us-east-1.
    SHARES_TABLE_NAME                 — Override the shares table (prod default).
    SHARE_LISTENERS_TABLE_NAME        — Override the listeners table (prod default).

Exit codes:
    0  success
    1  unhandled error
"""

from __future__ import annotations

import argparse
import os
import sys


def _ensure_env() -> None:
    """Surface clear errors if the required table-name env vars aren't set."""
    missing = [
        name for name in ("SHARES_TABLE_NAME", "SHARE_LISTENERS_TABLE_NAME")
        if not os.environ.get(name)
    ]
    if missing:
        sys.stderr.write(
            "ERROR: missing required env var(s): "
            + ", ".join(missing)
            + "\nSee the docstring at the top of this script for usage.\n"
        )
        sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip writes; just count rows that would be marked.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="DDB scan page size (default 100).",
    )
    args = parser.parse_args()

    _ensure_env()

    # Imports must come AFTER env validation so the lambdas.common modules
    # don't pick up empty table names from constants.py.
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
    from lambdas.common.shares_dynamo import scan_all_shares
    from lambdas.common.share_listeners_dynamo import mark_listened

    print(
        f"Backfill starting (dry_run={args.dry_run}, page_size={args.page_size})..."
    )

    total_seen = 0
    total_written = 0
    total_skipped = 0
    total_failed = 0

    try:
        for page in scan_all_shares(page_size=args.page_size):
            for share in page:
                total_seen += 1
                share_id = share.get("shareId")
                author_email = share.get("email")
                if not share_id or not author_email:
                    total_skipped += 1
                    if total_seen % 100 == 0:
                        print(
                            f"...processed {total_seen} (written={total_written}, "
                            f"skipped={total_skipped}, failed={total_failed})"
                        )
                    continue

                if args.dry_run:
                    total_written += 1
                else:
                    try:
                        mark_listened(share_id, author_email, source="author_create")
                        total_written += 1
                    except Exception as err:
                        total_failed += 1
                        print(
                            f"WARN: mark_listened failed for share={share_id} "
                            f"author={author_email}: {err}",
                            file=sys.stderr,
                        )

                if total_seen % 100 == 0:
                    print(
                        f"...processed {total_seen} (written={total_written}, "
                        f"skipped={total_skipped}, failed={total_failed})"
                    )

    except Exception as err:
        print(f"FATAL: backfill aborted after {total_seen} rows: {err}", file=sys.stderr)
        return 1

    print(
        f"Backfill complete. seen={total_seen} "
        f"written={total_written} skipped={total_skipped} failed={total_failed} "
        f"(dry_run={args.dry_run})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
