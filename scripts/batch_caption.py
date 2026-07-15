"""
FamilyVault Batch Captioning Job
Pulls uncaptioned images and videos from the database, generates captions
via the Claude vision API, and saves the results back to the database.
Videos are captioned from an extracted representative frame.

Run with: python3 scripts/batch_caption.py --limit 10
"""

from __future__ import annotations

import argparse
from pathlib import Path

from familyvault.captioner import caption_media_batch
from familyvault.database import get_media_needing_captions, save_caption
from familyvault.logger import get_logger

log = get_logger(__name__)


def run(limit: int) -> None:
    files = get_media_needing_captions(limit=limit)

    if not files:
        print("No uncaptioned media found. Nothing to do.")
        return

    print(f"Found {len(files)} uncaptioned file(s). Requesting captions...")

    path_to_id = {f["path"]: f["id"] for f in files}
    paths = [Path(f["path"]) for f in files]

    results = caption_media_batch(paths, max_items=limit)

    succeeded = 0
    failed = 0

    for result in results:
        file_id = path_to_id.get(str(result.path))
        if file_id is None:
            log.warning(f"Could not match result path back to a file id: {result.path}")
            continue

        if result.success:
            save_caption(file_id, result.caption)
            succeeded += 1
            print(f"  OK   #{file_id} {result.path.name}: {result.caption[:70]}")
        else:
            failed += 1
            print(f"  FAIL #{file_id} {result.path.name}: {result.error}")

    print(f"\nDone. {succeeded} captioned, {failed} failed, {len(files) - len(results)} skipped (unsupported format).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Caption a batch of uncaptioned images and videos.")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of files to caption in this run (default: 10)",
    )
    args = parser.parse_args()
    run(args.limit)


if __name__ == "__main__":
    main()
