#!/usr/bin/env python3
import sys
import argparse
import io
from pathlib import Path

# Fix Windows console encoding for UTF-8 / emojis
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.audit.scanner import FileScanner
from tools.audit.reporters import ConsoleReporter, ToonReporter

def main():
    parser = argparse.ArgumentParser(
        description="edge-audit: Deterministic Codebase Health & Bloat Assessment Tool"
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Target directory to audit (e.g. /home/oguz/MS-Randevu-monolith/src or .)"
    )
    parser.add_argument(
        "--format",
        choices=["human", "toon"],
        default="human",
        help="Output format: 'human' (colored console table) or 'toon' (AXI token-frugal notation)"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Maximum number of hotspots to display (default: 15)"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Optional file path to write report to (e.g. report.md)"
    )

    args = parser.parse_args()

    target_path = FileScanner.normalize_target_path(args.target)
    scanner = FileScanner()

    try:
        summary = scanner.scan(target_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.format == "toon":
        output = ToonReporter.render(summary, top_n=args.top)
    else:
        output = ConsoleReporter.render(summary, top_n=args.top)

    print(output)

    if args.output:
        out_file = Path(args.output)
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\n📁 Report successfully saved to: {out_file}")

if __name__ == "__main__":
    main()
