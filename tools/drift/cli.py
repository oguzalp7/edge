#!/usr/bin/env python3
"""
CLI entry point for edge-drift:
Detects architectural drift, discovers specs, archives ephemeral slice specs,
and consolidates domain contracts.
"""

import sys
import argparse
from pathlib import Path
from typing import List, Optional

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common.paths import normalize_target_path
from tools.drift.models import DriftStateStore, parse_domain_frontmatter
from tools.drift.scanner import (
    DRIFT_MODEL,
    archive_ephemeral_spec,
    check_drift,
    discover_specs,
    consolidate_domain,
    get_head_sha,
)


def run_drift(argv: Optional[List[str]] = None) -> int:
    """Runs drift CLI commands."""
    parser = argparse.ArgumentParser(
        prog="edge-drift",
        description="Edge Drift: Git-diff gated domain contract drift detector.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # discover
    p_discover = subparsers.add_parser(
        "discover",
        help="Discover canonical domain deeds vs ephemeral slice specs.",
    )
    p_discover.add_argument("repo", help="Path to repository")

    # check
    p_check = subparsers.add_parser(
        "check",
        help="Audit domain contracts against live code implementation.",
    )
    p_check.add_argument("repo", help="Path to repository")
    p_check.add_argument(
        "--model",
        default=DRIFT_MODEL,
        help=f"Model to use for LLM drift audit (default: {DRIFT_MODEL})",
    )
    p_check.add_argument(
        "--mark-clean",
        dest="mark_clean",
        help="Advance baseline SHA for a domain to current HEAD without audit",
    )

    # consolidate
    p_consolidate = subparsers.add_parser(
        "consolidate",
        help="Consolidate specs and code into a canonical domain contract ('Tapu').",
    )
    p_consolidate.add_argument("repo", help="Path to repository")
    p_consolidate.add_argument(
        "--domain",
        required=True,
        help="Canonical domain name (e.g. bookings, orders)",
    )
    p_consolidate.add_argument(
        "--paths",
        required=True,
        help="Comma-separated tracked paths or globs (e.g. 'src/lib/bookings/**,src/actions/bookings.ts')",
    )
    p_consolidate.add_argument(
        "--sources",
        help="Comma-separated paths to ephemeral source specifications",
    )
    p_consolidate.add_argument(
        "--archive-sources",
        action="store_true",
        help="Safely archive source specs to .edge/archive/specs/ after consolidation",
    )
    p_consolidate.add_argument(
        "--model",
        default=DRIFT_MODEL,
        help=f"Model to use for consolidation synthesis (default: {DRIFT_MODEL})",
    )

    args = parser.parse_args(argv)

    if args.subcommand == "discover":
        norm_repo = normalize_target_path(args.repo)
        report = discover_specs(norm_repo)
        print(f"\n🔍 Edge Spec Discovery Report: {norm_repo}")
        print("-" * 60)
        print(f"📜 Canonical Domain Deeds (docs/domains/*.md): {len(report.domain_contracts)}")
        for doc in report.domain_contracts:
            print(f"  • {doc}")

        print(f"\n📦 Ephemeral / Candidate Specs: {len(report.ephemeral_candidates)}")
        for spec in report.ephemeral_candidates:
            print(f"  • {spec}")
        print("")
        return 0

    elif args.subcommand == "check":
        norm_repo = normalize_target_path(args.repo)

        if args.mark_clean:
            domain_name = args.mark_clean.strip()
            doc_file = norm_repo / "docs" / "domains" / f"{domain_name}.md"
            if not doc_file.exists():
                print(f"❌ Error: Domain contract '{doc_file}' does not exist.")
                return 1

            try:
                with open(doc_file, "r", encoding="utf-8") as f:
                    content = f.read()
                parsed_domain, tracked_paths, _ = parse_domain_frontmatter(
                    content, fallback_domain=domain_name
                )
            except Exception as e:
                print(f"❌ Error reading contract: {e}")
                return 1

            head_sha = get_head_sha(norm_repo)
            rel_doc_path = doc_file.relative_to(norm_repo).as_posix()
            state_store = DriftStateStore.load_from_repo(norm_repo)
            state_store.update_record(
                domain=parsed_domain,
                sha=head_sha,
                doc_path=rel_doc_path,
                tracked_paths=tracked_paths,
            )
            print(
                f"✅ [edge-drift] Successfully marked domain '{parsed_domain}' CLEAN at HEAD ({head_sha})."
            )
            return 0

        results = check_drift(norm_repo, model=args.model)
        has_failure = False

        print(f"\n🛡️ Edge Domain Drift Check: {norm_repo}")
        print("-" * 70)
        if not results:
            print("No domain contracts found under docs/domains/*.md.")
            return 0

        for r in results:
            status_icon = "✅" if r.status == "CLEAN" else "⚠️" if r.status == "UNTRACKED" else "❌"
            llm_indicator = "⚡(LLM)" if r.llm_invoked else "🔒(Zero-Token)"
            print(f"{status_icon} [{r.status}] {r.domain} | {llm_indicator} | {r.summary}")
            if r.status in ("DRIFT_DETECTED", "ERROR"):
                has_failure = True
                if r.findings_markdown:
                    print("\nFindings:")
                    for line in r.findings_markdown.strip().splitlines():
                        print(f"  {line}")
                    print("")

        print("-" * 70)
        report_path = norm_repo / ".edge" / "drift" / "latest-drift-report.md"
        print(f"Detailed report saved to: {report_path}\n")

        return 1 if has_failure else 0

    elif args.subcommand == "consolidate":
        norm_repo = normalize_target_path(args.repo)
        tracked_paths = [p.strip() for p in args.paths.split(",") if p.strip()]
        source_paths: Optional[List[Path]] = None
        if args.sources:
            source_paths = [Path(s.strip()) for s in args.sources.split(",") if s.strip()]

        success, target_path, msg = consolidate_domain(
            repo_path=norm_repo,
            domain=args.domain,
            tracked_paths=tracked_paths,
            source_specs=source_paths,
            archive_sources=args.archive_sources,
            model=args.model,
        )

        if success:
            print(f"✅ [edge-drift] {msg}")
            return 0
        else:
            print(f"❌ [edge-drift] Error: {msg}")
            return 1

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main execution function."""
    return run_drift(argv)


if __name__ == "__main__":
    sys.exit(main())
