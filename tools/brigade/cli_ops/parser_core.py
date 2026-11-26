"""Argparse subparser registrations for station, pipeline, worktree, and slice commands."""

from typing import Any

from tools.brigade.models import StationRole


def register_station_parsers(subparsers: Any) -> None:
    """Register init, register, unregister, stations, and triage subparsers."""
    p_init = subparsers.add_parser("init", help="Initialize brigade state in target repo")
    p_init.add_argument("repo", help="Path to target repository")
    p_init.add_argument("--base-branch", default="development", help="Base branch (default: development)")

    p_reg = subparsers.add_parser("register", help="Register a persistent station worker")
    p_reg.add_argument("repo", help="Path to target repository")
    p_reg.add_argument("--role", required=True, choices=[r.value for r in StationRole], help=f"Station role ({', '.join(r.value for r in StationRole)})")
    p_reg.add_argument("--conversation-id", required=True, help="Subagent conversation ID")
    p_reg.add_argument("--name", help="Human-readable station name")
    p_reg.add_argument("--model", default="flash", help="Model pinned to station (default: flash)")

    p_unreg = subparsers.add_parser("unregister", help="Unregister a station")
    p_unreg.add_argument("repo", help="Path to target repository")
    p_unreg.add_argument("--role", required=True, choices=[r.value for r in StationRole], help="Station role to unregister")

    subparsers.add_parser("stations", help="List registered stations").add_argument("repo", help="Path to target repository")

    p_triage = subparsers.add_parser("triage", help="Triage next debt item from radar ledger")
    p_triage.add_argument("repo", help="Path to target repository")
    p_triage.add_argument("--track", default="core", choices=["core", "ui"], help="Debt track")
    p_triage.add_argument("--domain", help="Filter by domain/module name")
    p_triage.add_argument("--whitelist", help="Comma-separated domains to allow")
    p_triage.add_argument("--blacklist", help="Comma-separated domains to skip")
    p_triage.add_argument("--transcript", help="Path to transcript file to check context heat before triaging")


def register_pipeline_parsers(subparsers: Any) -> None:
    """Register ticket, findings, seal-review, advance, status, graph, and escalation subparsers."""
    p_ticket = subparsers.add_parser("ticket", help="View active ticket or station prompt payload")
    p_ticket.add_argument("repo", help="Path to target repository")
    p_ticket.add_argument("--prompt", action="store_true", help="Print prompt payload for current station")
    p_ticket.add_argument("--format", choices=["toon", "json"], default="toon", help="Output format")

    p_find = subparsers.add_parser("add-finding", help="Record a review finding")
    p_find.add_argument("repo", help="Path to target repository")
    p_find.add_argument("--axis", required=True, choices=["standards", "spec", "evidence", "qa"], help="Review axis")
    p_find.add_argument("--severity", required=True, choices=["CRITICAL", "WARNING", "ADVISORY"], help="Severity")
    p_find.add_argument("--file", required=True, help="File path with finding")
    p_find.add_argument("--rule", required=True, help="Rule ID violated")
    p_find.add_argument("--desc", required=True, help="Description of finding")
    p_find.add_argument("--fix", help="Suggested remediation")
    p_find.add_argument("--line", type=int, help="Line number")

    subparsers.add_parser("clear-findings", help="Clear review findings").add_argument("repo", help="Path to target repository")

    p_seal = subparsers.add_parser("seal-review", help="Seal 3-axis Examiner review verdict into BrigadeState")
    p_seal.add_argument("repo", help="Path to target repository")
    p_seal.add_argument("--verdict", required=True, choices=["PASS", "FAIL", "pass", "fail"], help="Examiner verdict")
    p_seal.add_argument("--summary", required=True, help="Concise 3-axis review summary")
    p_seal.add_argument("--evidence-reviewed", default="", help="Comma-separated evidence paths reviewed")
    p_seal.add_argument("--examiner-cid", default=None, help="Optional Examiner conversation ID")

    p_adv = subparsers.add_parser("advance", help="Execute guards and advance to next state")
    p_adv.add_argument("repo", help="Path to target repository")
    p_adv.add_argument("--force", action="store_true", help="Force state advance bypassing guard")

    p_status = subparsers.add_parser("status", help="Print current state card")
    p_status.add_argument("repo", help="Path to target repository")
    p_status.add_argument("--format", choices=["human", "toon", "json"], default="human", help="Output format")

    p_graph = subparsers.add_parser("graph", help="Print ASCII and Mermaid state machine graph")
    p_graph.add_argument("repo", help="Path to target repository")
    p_graph.add_argument("--format", choices=["ascii", "mermaid", "all"], default="all", help="Graph output format")

def register_escalation_parsers(subparsers: Any) -> None:
    """Register abort, escalate, and release subparsers."""
    p_abort = subparsers.add_parser("abort", help="Abort current cycle and reset to IDLE")
    p_abort.add_argument("repo", help="Path to target repository")
    p_abort.add_argument("--reason", default="Manual abort", help="Reason for aborting")
    p_abort.add_argument("--force", action="store_true", default=True, help="Force worktree cleanup")
    p_abort.add_argument("--constraint", help="Explicit negative constraint to record in flight recorder")

    p_esc = subparsers.add_parser("escalate", help="Escalate active ticket to captain")
    p_esc.add_argument("repo", help="Path to target repository")
    p_esc.add_argument("--reason", required=True, help="Reason for escalation")

    p_rel = subparsers.add_parser("release", help="Release escalated ticket following captain decision")
    p_rel.add_argument("repo", help="Path to target repository")
    p_rel.add_argument("--decision", required=True, help="Captain's binding decision")


def register_worktree_slice_parsers(subparsers: Any) -> None:
    """Register worktree, start-slice, prompt, critique-spec, and finish-slice subparsers."""
    from tools.brigade.spec_critic import FALLBACK_CRITIC_MODEL, PRIMARY_CRITIC_MODEL

    p_wt = subparsers.add_parser("worktree", help="Inspect or manage isolated worktree pool")
    p_wt.add_argument("repo", nargs="?", default=".", help="Path to target repository (default: .)")
    p_wt.add_argument("--action", choices=["status", "lease", "return", "prune"], default="status", help="Worktree action")
    p_wt.add_argument("--branch", help="Branch name for lease")
    p_wt.add_argument("--path", help="Worktree path for return")
    p_wt.add_argument("--force", action="store_true", help="Force return worktree")
    p_wt.add_argument("--holder", default="edge-brigade", help="Lease holder tag")

    p_start = subparsers.add_parser("start-slice", help="Initiate a feature or refactor slice with an isolated worktree")
    p_start.add_argument("repo", help="Path to target repository")
    p_start.add_argument("--name", required=True, help="Slice/feature name")
    p_start.add_argument("--track", default="feature", choices=["feature", "core", "ui"], help="Slice track")
    p_start.add_argument("--target-file", default="", help="Primary target file (optional)")
    p_start.add_argument("--domain", default="", help="Domain module")
    p_start.add_argument("--test-cmd", default="npm run test:unit", help="Test seam command")
    p_start.add_argument("--allow-migration", action="store_true", default=None, help="Allow schema migrations")
    p_start.add_argument("--expected-files", help="Comma-separated expected files")
    p_start.add_argument("--spec", help="Path to specification document")
    p_start.add_argument("--lavish", help="Path to associated Lavish prototype HTML file")
    qa_group = p_start.add_mutually_exclusive_group()
    qa_group.add_argument("--qa", dest="require_qa", action="store_true", default=None, help="Explicitly mandate QA stage")
    qa_group.add_argument("--no-qa", dest="require_qa", action="store_false", default=None, help="Explicitly bypass QA stage")
    p_start.add_argument("--issue", type=int, default=None, help="Linked child/ticket tracker issue number")
    p_start.add_argument("--parent-issue", type=int, default=None, help="Linked parent Frontier/Spec tracker issue number")
    p_start.add_argument("--offline", action="store_true", help="Use local tracker backend")

    p_prompt = subparsers.add_parser("prompt", help="Compose and print 2-layer prompt for a station")
    p_prompt.add_argument("repo", help="Path to target repository")
    p_prompt.add_argument("--role", required=True, help="Station role slug")
    p_prompt.add_argument("--ticket", help="Optional ticket ID to bind")

    p_crit = subparsers.add_parser("critique-spec", help="Run advisory cross-provider Goldfish Spec Critic")
    p_crit.add_argument("repo", help="Path to target repository")
    p_crit.add_argument("--spec", default=None, help="Path to specification document")
    p_crit.add_argument("--issue", type=int, default=None, help="Tracker issue number to critique")
    p_crit.add_argument("--offline", action="store_true", help="Use local tracker backend")
    p_crit.add_argument("--no-post-comment", action="store_true", help="Skip posting critique comment on issue")
    p_crit.add_argument("--model", default=PRIMARY_CRITIC_MODEL, help=f"Primary critic model (default: {PRIMARY_CRITIC_MODEL})")
    p_crit.add_argument("--fallback-model", default=FALLBACK_CRITIC_MODEL, help=f"Fallback critic model (default: {FALLBACK_CRITIC_MODEL})")
    p_crit.add_argument("--timeout", type=int, default=180, help="Critique timeout in seconds (default: 180)")

    p_fin = subparsers.add_parser("finish-slice", help="Fast-forward merge slice, release worktree, and resolve ticket")
    p_fin.add_argument("repo", help="Path to target repository")
    p_fin.add_argument("--pr", action="store_true", help="Open a Spec-Anchored GitHub PR")
    p_fin.add_argument("--no-auto-merge", action="store_true", help="Do not auto-merge Two-Way Door PRs")
    p_fin.add_argument("--offline", action="store_true", help="Use local tracker backend")
