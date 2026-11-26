"""Argparse subparser registrations for refactor, QA, tier, ship, and audit commands."""

from typing import Any


def register_refactor_parsers(subparsers: Any) -> None:
    """Register create-refactor-ticket, seal-refactor, confirm-merge, pause, resume, check-heat."""
    p_crt = subparsers.add_parser("create-refactor-ticket", help="Create dual-layer refactor ticket and optional tasks-axi entry")
    p_crt.add_argument("repo", help="Path to target repository")
    p_crt.add_argument("--slug", required=True, help="Refactor ticket slug")
    p_crt.add_argument("--track", required=True, choices=["core", "ui"], help="Refactor track")
    p_crt.add_argument("--rules", default="", help="Comma-separated target rules")
    p_crt.add_argument("--files", default="", help="Comma-separated target files")
    p_crt.add_argument("--targets", default="", help="Comma-separated metric targets")
    p_crt.add_argument("--door", default="two-way", choices=["two-way", "one-way"], help="Door classification")
    crt_sync = p_crt.add_mutually_exclusive_group()
    crt_sync.add_argument("--sync-tasks", dest="sync_tasks", action="store_true", default=None, help="Sync ticket to tracker (default)")
    crt_sync.add_argument("--no-sync-tasks", dest="sync_tasks", action="store_false", default=None, help="Skip tracker issue creation")
    p_crt.add_argument("--hold-captain", action="store_true", help="Add hold:captain label on tracker issue")
    p_crt.add_argument("--parent-issue", type=int, default=None, help="Parent tracker issue number")
    p_crt.add_argument("--offline", action="store_true", help="Use local tracker backend")

    p_sref = subparsers.add_parser("seal-refactor", help="Synthesize 4-seal machine-generated RefactorReceipt")
    p_sref.add_argument("repo", help="Path to target repository")
    p_sref.add_argument("--slug", default=None, help="Refactor receipt slug")
    p_sref.add_argument("--base", default=None, help="Base branch to diff against")

    p_cm = subparsers.add_parser("confirm-merge", help="Confirm queued PR merge, complete linked tracker issue, and reset FSM to IDLE")
    p_cm.add_argument("repo", help="Path to target repository")
    p_cm.add_argument("--offline", action="store_true", help="Use local tracker backend")

    p_pause = subparsers.add_parser("pause", help="Safely pause brigade execution and create durable checkpoint")
    p_pause.add_argument("repo", help="Path to target repository")
    p_pause.add_argument("--reason", default="MANUAL_PAUSE", help="Reason for pausing")

    subparsers.add_parser("resume", help="Resume brigade execution from durable checkpoint").add_argument("repo", help="Path to target repository")

    p_heat = subparsers.add_parser("check-heat", help="Check context window token heat from transcript")
    p_heat.add_argument("transcript", help="Path to transcript.jsonl or logs directory")
    p_heat.add_argument("--repo", default=".", help="Path to target repository (default: .)")


def register_qa_tier_parsers(subparsers: Any) -> None:
    """Register distill, qa-inspect, prototype, and tier subparsers."""
    p_distill = subparsers.add_parser("distill", help="Zero-token transcript harvester, candidate pool, and pattern miner")
    p_distill.add_argument("distill_args", nargs="*", help="Arguments forwarded to edge-distill CLI")

    p_qa = subparsers.add_parser("qa-inspect", help="Deterministic React Fiber component locator & frontier staging")
    p_qa.add_argument("query", help="CSS selector, XPath, or text")
    p_qa.add_argument("repo", nargs="?", default=".", help="Path to target repository (default: .)")
    p_qa.add_argument("--issue", help="Description of UI anomaly")
    p_qa.add_argument("--category", choices=["contrast", "overflow", "layout", "visual-regression", "misalignment"], help="Anomaly category")
    p_qa.add_argument("--frontier", action="store_true", help="Stage finding into frontier-axi")
    p_qa.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_qa.add_argument("--offline", action="store_true", help="Use local tracker backend")

    p_proto = subparsers.add_parser("prototype", help="Lavish-axi interactive UI prototype bridge")
    p_proto.add_argument("repo", help="Path to target repository")
    p_proto.add_argument("--action", required=True, choices=["serve", "poll", "stop", "status"], help="Prototype action")
    p_proto.add_argument("--file", help="Path to .lavish/*.html prototype file")
    p_proto.add_argument("--agent-reply", help="Optional reply text to show in Lavish Editor")

    p_tier = subparsers.add_parser("tier", help="Edge Brigade tier management (status, switch)")
    p_tier.add_argument("repo", nargs="?", default=".", help="Path to target repository (default: .)")
    p_tier.add_argument("--action", required=True, choices=["status", "switch"], help="Tier action: status or switch")
    p_tier.add_argument("--target", choices=["pro", "ultra"], help="Target tier when action is switch")
    p_tier.add_argument("--json", action="store_true", help="Output machine-readable JSON")


def register_ship_audit_parsers(subparsers: Any) -> None:
    """Register prepare-ship, smoke-routes, and security-audit subparsers."""
    p_ship = subparsers.add_parser("prepare-ship", help="Synthesize per-spec Specs-to-PR ship plans and split branches")
    p_ship.add_argument("repo", help="Path to target repository")
    p_ship.add_argument("--base", default="development", help="Base branch to diff against (default: development)")
    p_ship.add_argument("--spec", default=None, help="Filter to a single changed spec slug")
    p_ship.add_argument("--split-branches", action="store_true", help="Create isolated ship/<spec-slug> branches off base")
    p_ship.add_argument("--publish-evidence", action="store_true", help="Publish verified QA screenshots to evidence branch")
    p_ship.add_argument("--evidence-branch", default="edge-qa-evidence", help="Target orphan branch for QA screenshot evidence")
    p_ship.add_argument("--format", choices=["pr", "show-me", "json"], default="pr", help="Output format (default: pr)")
    p_ship.add_argument("--out", help="Optional output file path (written atomically)")
    p_ship.add_argument("--strict-proofs", action="store_true", help="Require at least one verified QA proof or ExaminerReceipt")
    p_ship.add_argument("--require-smoke", action="store_true", help="Require passing .edge/qa/smoke-routes.json when targeting staging")
    p_ship.add_argument("--allow-topology-override", action="store_true", help="Allow manual bypass of stage branch topology guard")
    p_ship.add_argument("--stage-branch", action="append", default=[], help="Override stage branch mapping")
    p_ship.add_argument("--issue", type=int, action="append", default=None, help="Tracker issue number(s) to include and link")
    p_ship.add_argument("--parent-issue", type=int, default=None, help="Parent Frontier/Spec issue number")
    p_ship.add_argument("--offline", action="store_true", help="Use local tracker backend")

    p_smoke = subparsers.add_parser("smoke-routes", help="Discover and headless-smoke-scan all project routes")
    p_smoke.add_argument("repo", help="Path to target repository")
    p_smoke.add_argument("--base-url", default="http://localhost:3000", help="Running app base URL")
    p_smoke.add_argument("--pattern", default=None, help="Optional extra glob pattern for custom routes")
    p_smoke.add_argument("--param", action="append", default=[], help="Dynamic route param replacement (key=val)")
    p_smoke.add_argument("--auth-cookie", default=None, help="Optional Cookie header for authenticated routes")
    p_smoke.add_argument("--no-triage", action="store_true", help="Do not auto-triage failed routes")
    p_smoke.add_argument("--discover-only", action="store_true", help="Only discover and print routes")
    p_smoke.add_argument("--out", default=None, help="Optional output path")
    p_smoke.add_argument("--format", choices=["toon", "json", "markdown"], default="toon", help="Smoke report format")
    p_smoke.add_argument("--settle-budget-ms", type=int, default=1500, help="Spinner/skeleton settling budget in ms")
    p_smoke.add_argument("--heap-budget-mb", type=float, default=80.0, help="JS heap usage budget in MB")

    p_sec = subparsers.add_parser("security-audit", help="Run incremental 4-class security audit with shared coverage ledger")
    p_sec.add_argument("repo", help="Path to target repository")
    p_sec.add_argument("--scope", action="append", default=[], help="Audit scope directory/file/glob")
    p_sec.add_argument("--diff-only", action="store_true", help="Restrict audit to git diff changed files")
    p_sec.add_argument("--base", default=None, help="Git base ref for --diff-only")
    p_sec.add_argument("--recursive", action="store_true", help="Audit all repository source files")
    p_sec.add_argument("--profile", choices=["quick", "standard", "deep"], default="standard", help="Audit depth profile")
    p_sec.add_argument("--no-triage", action="store_true", help="Do not auto-triage confirmed findings")
    p_sec.add_argument("--format", choices=["toon", "json", "markdown"], default="toon", help="Output format")
