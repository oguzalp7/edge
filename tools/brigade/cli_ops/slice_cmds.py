"""Vertical slice lifecycle, spec critique, and queued merge commands."""

import argparse
from typing import Any, Dict

from tools.brigade.cli_ops._facade import resolve_symbol
from tools.common import normalize_target_path


def cmd_start_slice(args: argparse.Namespace) -> int:
    """Initiate a feature or refactor slice with an isolated worktree."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    expected_files = [f.strip() for f in args.expected_files.split(",") if f.strip()] if getattr(args, "expected_files", None) else None
    track = getattr(args, "track", "feature")
    raw_allow_mig = getattr(args, "allow_migration", None)
    ok, ticket, msg = fsm.start_slice(
        name=args.name, track=track, target_file=getattr(args, "target_file", ""),
        domain=getattr(args, "domain", ""), test_seam_command=getattr(args, "test_cmd", "npm run test:unit"),
        allow_schema_migration=(track == "feature") if raw_allow_mig is None else bool(raw_allow_mig),
        auto_lease_worktree=True, expected_files=expected_files, spec_path=getattr(args, "spec", None),
        lavish_path=getattr(args, "lavish", None), require_qa=getattr(args, "require_qa", None),
        issue_number=getattr(args, "issue", None), parent_issue=getattr(args, "parent_issue", None),
        offline=bool(getattr(args, "offline", False)),
    )
    if not ok:
        print(f"❌ {msg}")
        return 1
    print("\n=======================================================\n🚀  EDGE BRIGADE — VERTICAL SLICE INITIATED\n=======================================================")
    print(f"Ticket ID:       {ticket.ticket_id}\nInitial State:   {fsm.state.current_state.value}\nTrack:           {ticket.track.upper()}")
    print(f"Domain:          {ticket.domain}\nBranch:          {ticket.branch_name}\nTarget File:     {ticket.target_file}")
    for label, val in (("Expected Files", ", ".join(ticket.expected_files) if ticket.expected_files else ""), ("Spec Path", ticket.spec_path), ("Lavish Path", getattr(ticket, "lavish_path", None))):
        if val:
            print(f"{label + ':':<17}{val}")
    if getattr(ticket, "require_qa", None) is not None:
        print(f"Require QA:      {ticket.require_qa}")
    print(f"Test Seam:       {ticket.test_seam_command}\nWorktree Path:   {ticket.worktree_path or 'Primary (no worktree backend)'}")
    print("=======================================================")
    if ticket.worktree_path:
        print(f"\n🛡️ ZERO-TOUCH INVARIANT: Coder/Surgeon MUST work strictly inside:\n   cd {ticket.worktree_path}\n")
    return 0


def cmd_critique_spec(args: argparse.Namespace) -> int:
    """Run advisory cross-provider Goldfish Spec Critic."""
    repo_path = normalize_target_path(args.repo)
    spec_arg, issue_arg = getattr(args, "spec", None), getattr(args, "issue", None)
    if not spec_arg and issue_arg is None:
        print("❌ Either --spec or --issue must be provided.")
        return 1
    crit_fn = resolve_symbol("run_spec_critique", "tools.brigade.spec_critic")
    pri = resolve_symbol("PRIMARY_CRITIC_MODEL", "tools.brigade.spec_critic")
    fb = resolve_symbol("FALLBACK_CRITIC_MODEL", "tools.brigade.spec_critic")
    res = crit_fn(
        repo_path=repo_path, spec_path=spec_arg,
        primary_model=getattr(args, "model", pri), fallback_model=getattr(args, "fallback_model", fb),
        timeout=getattr(args, "timeout", 180), issue_number=issue_arg,
        offline=bool(getattr(args, "offline", False)), post_comment=not bool(getattr(args, "no_post_comment", False)),
    )
    print("\n=======================================================\n🐟  EDGE BRIGADE — SPEC CRITIC (GOLDFISH CRITIC)\n=======================================================")
    print(f"Status:             {'SUCCESS' if res.success else 'FAILED'}\nModel Used:         {res.model_used}\nFallback Triggered: {res.fallback_triggered}")
    for lbl, val in (("Report Path", res.report_path), ("Summary", res.summary), ("Error", res.error)):
        if val:
            print(f"{lbl + ':':<20}{val}")
    print("=======================================================\n")
    return 0 if res.success else 1


def cmd_finish_slice(args: argparse.Namespace) -> int:
    """Fast-forward merge or PR-deliver active slice and complete linked ticket."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    use_pr, no_auto = bool(getattr(args, "pr", False)), bool(getattr(args, "no_auto_merge", False))
    fin_kwargs: Dict[str, Any] = {}
    if use_pr or no_auto:
        fin_kwargs["open_pr"], fin_kwargs["auto_merge_two_way"] = use_pr, not no_auto
    if getattr(args, "offline", False):
        fin_kwargs["offline"] = True
    ok, msg = fsm.finish_slice(**fin_kwargs)
    if not ok:
        print(f"❌ {msg}")
        return 1
    print("\n=======================================================\n✅  EDGE BRIGADE — VERTICAL SLICE FINISHED\n=======================================================")
    print(msg + "\n=======================================================\n")
    return 0


def cmd_confirm_merge(args: argparse.Namespace) -> int:
    """Confirm queued PR merge and reset FSM to IDLE."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    offline = bool(getattr(args, "offline", False))
    ok, msg = fsm.confirm_merge(offline=offline) if offline else fsm.confirm_merge()
    print(f"✅ {msg}" if ok else f"❌ {msg}")
    return 0 if ok else 1
