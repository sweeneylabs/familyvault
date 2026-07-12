"""
FamilyVault CLI
Entry point for running FamilyVault from the command line.
Usage: familyvault scan <path>
"""

import sys
import time
import argparse
from pathlib import Path

from familyvault.logger import get_logger
from familyvault.scanner import scan
from familyvault.database import init_db, save_scan

log = get_logger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format_size(size_bytes: int) -> str:
    """Return a human-readable file size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"


def _format_duration(seconds: float) -> str:
    """Return a human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.1f}s"


def _print_summary(result, scan_id: int, duration: float) -> None:
    """Print a formatted scan summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Scan Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Scan ID':<20} #{scan_id:<{width - 23}}│")
    print(f"│  {'Root':<20} {str(result.root)[:width - 23]:<{width - 23}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Images':<20} {result.image_count:<{width - 23}}│")
    print(f"│  {'Videos':<20} {result.video_count:<{width - 23}}│")
    print(f"│  {'Total media':<20} {result.total_count:<{width - 23}}│")
    print(f"│  {'Total size':<20} {_format_size(result.total_size_bytes):<{width - 23}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Skipped':<20} {result.skipped_count:<{width - 23}}│")
    print(f"│  {'Errors':<20} {result.error_count:<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("└" + "─" * width + "┘")
    print()


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_scan(args) -> int:
    """Handle the scan subcommand."""
    root = Path(args.path).expanduser().resolve()

    if not root.exists():
        print(f"Error: path does not exist: {root}", file=sys.stderr)
        return 1

    if not root.is_dir():
        print(f"Error: path is not a directory: {root}", file=sys.stderr)
        return 1

    print(f"Scanning: {root}")
    print("This may take a moment for large libraries...\n")

    init_db()
    start = time.perf_counter()

    try:
        result = scan(root)
        scan_id = save_scan(result)
        duration = time.perf_counter() - start
        _print_summary(result, scan_id, duration)
        return 0

    except Exception as e:
        log.error(f"Scan failed: {e}")
        print(f"\nError: scan failed — {e}", file=sys.stderr)
        return 1


# ── Entry Point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="familyvault",
        description="Private AI-powered photo and video library.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # scan subcommand
    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan a directory for media files.",
    )
    scan_parser.add_argument(
        "path",
        metavar="<path>",
        help="Directory to scan.",
    )
    scan_parser.set_defaults(func=cmd_scan)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()