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
from tools.drift.models import (
    DriftStateStore,
    OntologyReport,
    parse_canonical_domain_doc,
    parse_context_glossary,
    parse_domain_frontmatter,
)
from tools.drift.scanner import (
    DRIFT_MODEL,
    _discover_domain_contract_files,
    archive_ephemeral_spec,
    check_drift,
    discover_specs,
    consolidate_domain,
    get_head_sha,
    validate_ontology,
)


def _build_drift_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-drift",
        description="Edge Drift: Git-diff gated domain contract drift detector.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    p_discover = subparsers.add_parser(
        "discover",
        help="Discover canonical domain deeds vs ephemeral slice specs.",
    )
    p_discover.add_argument("repo", help="Path to repository")

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
        help="Advance baseline SHA for a domain (or 'all') to current HEAD without audit",
    )
    p_check.add_argument(
        "--ontology-only",
        action="store_true",
        help="Run deterministic ontology validation only (0 LLM / git calls)",
    )

    p_consolidate = subparsers.add_parser(
        "consolidate",
        help="Consolidate specs and code into a canonical domain contract ('Tapu').",
    )
    p_consolidate.add_argument("repo", help="Path to repository")
    p_consolidate.add_argument("--domain", required=True, help="Canonical domain name")
    p_consolidate.add_argument("--paths", required=True, help="Comma-separated tracked paths or globs")
    p_consolidate.add_argument("--sources", help="Comma-separated paths to ephemeral source specifications")
    p_consolidate.add_argument("--issue", type=int, action="append", default=None, help="Tracker issue number(s) to include as source specs")
    p_consolidate.add_argument("--offline", action="store_true", help="Use local tracker backend")
    p_consolidate.add_argument("--archive-sources", action="store_true", help="Archive source specs after consolidation")
    p_consolidate.add_argument("--model", default=DRIFT_MODEL, help=f"Model to use (default: {DRIFT_MODEL})")
    return parser


def _cmd_discover(repo_arg: str) -> int:
    norm_repo = normalize_target_path(repo_arg)
    report = discover_specs(norm_repo)
    print(f"\n🔍 Edge Spec Discovery Report: {norm_repo}")
    print("-" * 60)
    print(f"📜 Canonical Domain Deeds (docs/*/DOMAIN.md & docs/domains/*.md): {len(report.domain_contracts)}")
    for doc in report.domain_contracts:
        print(f"  • {doc}")
    print(f"\n📦 Ephemeral / Candidate Specs: {len(report.ephemeral_candidates)}")
    for spec in report.ephemeral_candidates:
        print(f"  • {spec}")
    print("")
    return 0


def _resolve_mark_clean_targets(
    norm_repo: Path,
    domain_arg: str,
) -> Optional[List[tuple]]:
    if domain_arg == "all":
        targets = _discover_domain_contract_files(norm_repo)
        if not targets:
            print("❌ Error: No domain contracts found to mark clean.")
            return None
        return targets

    if domain_arg.lower() != "domains":
        canon_file = norm_repo / "docs" / domain_arg / "DOMAIN.md"
        if canon_file.is_file():
            return [(domain_arg, canon_file, True)]

    legacy_file = norm_repo / "docs" / "domains" / f"{domain_arg}.md"
    if legacy_file.is_file() and legacy_file.name.lower() != "domain.md":
        return [(domain_arg, legacy_file, False)]

    print(f"❌ Error: Domain contract for '{domain_arg}' does not exist.")
    return None


def _load_cli_context_globs(norm_repo: Path) -> dict:
    context_path = norm_repo / "CONTEXT.md"
    if not context_path.is_file():
        return {}
    try:
        globs, _ = parse_context_glossary(context_path.read_text(encoding="utf-8-sig", errors="replace"))
        return globs
    except Exception:
        return {}


def _parse_contract_for_mark_clean(
    norm_repo: Path,
    domain_name: str,
    doc_file: Path,
    is_canonical: bool,
    context_globs: Optional[dict] = None,
) -> tuple:
    content = doc_file.read_text(encoding="utf-8-sig")
    rel_doc_path = doc_file.relative_to(norm_repo).as_posix()
    globs_map = context_globs if context_globs is not None else {}
    if is_canonical:
        parsed = parse_canonical_domain_doc(content, doc_path=rel_doc_path, fallback_domain=domain_name)
        resolved = globs_map.get(parsed.domain) or parsed.tracked_paths
        return parsed.domain, resolved, rel_doc_path
    parsed_domain, tracked_paths, _ = parse_domain_frontmatter(content, fallback_domain=domain_name)
    resolved = globs_map.get(parsed_domain) or tracked_paths
    return parsed_domain, resolved, rel_doc_path


def _cmd_mark_clean(norm_repo: Path, domain_arg: str) -> int:
    head_sha = get_head_sha(norm_repo)
    if not head_sha:
        print("❌ Error: Unable to resolve git HEAD SHA (empty HEAD).")
        return 1

    targets = _resolve_mark_clean_targets(norm_repo, domain_arg.strip())
    if targets is None:
        return 1

    context_globs = _load_cli_context_globs(norm_repo)
    state_store = DriftStateStore.load_from_repo(norm_repo)
    for domain_name, doc_file, is_canonical in targets:
        try:
            parsed_domain, tracked_paths, rel_doc_path = _parse_contract_for_mark_clean(
                norm_repo, domain_name, doc_file, is_canonical, context_globs
            )
        except Exception as e:
            print(f"❌ Error reading contract '{doc_file}': {e}")
            return 1
        state_store.update_record(
            domain=parsed_domain,
            sha=head_sha,
            doc_path=rel_doc_path,
            tracked_paths=tracked_paths,
        )
        print(f"✅ [edge-drift] Marked domain '{parsed_domain}' CLEAN at HEAD ({head_sha}).")
    return 0


def _print_ontology_report(report: OntologyReport) -> None:
    if report.skipped:
        return
    errors = sum(1 for i in report.issues if i.severity == "ERROR")
    warnings = sum(1 for i in report.issues if i.severity == "WARNING")
    print(
        f"🧭 Ontology Check: {len(report.domain_docs)} domain(s), "
        f"{len(report.context_concepts)} concept(s), {errors} error(s), {warnings} warning(s)"
    )
    for issue in report.issues:
        icon = "❌" if issue.severity == "ERROR" else "⚠️"
        print(f"  {icon} [{issue.severity}] {issue.code} ({issue.file_path}): {issue.detail}")


def _cmd_check(args: argparse.Namespace) -> int:
    norm_repo = normalize_target_path(args.repo)
    if args.mark_clean:
        return _cmd_mark_clean(norm_repo, args.mark_clean)

    ontology_report = validate_ontology(norm_repo)
    _print_ontology_report(ontology_report)
    if args.ontology_only:
        return 1 if ontology_report.has_errors else 0

    results = check_drift(norm_repo, model=args.model)
    has_failure = ontology_report.has_errors

    print(f"\n🛡️ Edge Domain Drift Check: {norm_repo}")
    print("-" * 70)
    if not results:
        print("No domain contracts found under docs/*/DOMAIN.md or docs/domains/*.md.")
        return 1 if has_failure else 0

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


def _cmd_consolidate(args: argparse.Namespace) -> int:
    norm_repo = normalize_target_path(args.repo)
    tracked_paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    from tools.drift.tracker_specs import resolve_issue_source_specs

    source_paths: List[Path] = []
    if args.sources:
        source_paths.extend(Path(s.strip()) for s in args.sources.split(",") if s.strip())
    issue_nums = getattr(args, "issue", None)
    if issue_nums:
        source_paths.extend(resolve_issue_source_specs(norm_repo, issue_nums, offline=bool(getattr(args, "offline", False))))

    success, _, msg = consolidate_domain(
        repo_path=norm_repo,
        domain=args.domain,
        tracked_paths=tracked_paths,
        source_specs=source_paths or None,
        archive_sources=args.archive_sources,
        model=args.model,
    )
    if success:
        print(f"✅ [edge-drift] {msg}")
        return 0
    print(f"❌ [edge-drift] Error: {msg}")
    return 1


def run_drift(argv: Optional[List[str]] = None) -> int:
    """Runs drift CLI commands."""
    from tools.tracker.models import TrackerAuthError

    args = _build_drift_parser().parse_args(argv)
    try:
        if args.subcommand == "discover":
            return _cmd_discover(args.repo)
        if args.subcommand == "check":
            return _cmd_check(args)
        if args.subcommand == "consolidate":
            return _cmd_consolidate(args)
    except TrackerAuthError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main execution function."""
    return run_drift(argv)


if __name__ == "__main__":
    sys.exit(main())
