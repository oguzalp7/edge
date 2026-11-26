"""Treehouse worktree management and transcript context-heat check commands."""

import argparse
from pathlib import Path
from typing import Any

from tools.brigade.cli_ops._facade import resolve_symbol
from tools.common import normalize_target_path


def _worktree_lease(fsm: Any, args: argparse.Namespace) -> int:
    branch = getattr(args, "branch", None) or (fsm.state.active_ticket.branch_name if fsm.state.active_ticket else None)
    if not branch:
        print("❌ --branch is required to lease a worktree when no active ticket is present.")
        return 1
    acquire_fn = resolve_symbol("acquire_worktree", "tools.brigade.worktree")
    ok, wt_path, err = acquire_fn(fsm.target_repo, branch_name=branch, lease_holder=getattr(args, "holder", "edge-brigade"))
    if not ok:
        print(f"❌ Failed to acquire Treehouse worktree: {err}")
        return 1
    fsm.state.active_worktree = wt_path
    if fsm.state.active_ticket:
        fsm.state.active_ticket.worktree_path = wt_path
    fsm.save()
    print("\n=======================================================\n🌳  TREEHOUSE WORKTREE LEASED\n=======================================================")
    print(f"Repository:      {fsm.target_repo}\nBranch:          {branch}\nWorktree Path:   {wt_path}\n=======================================================")
    print(f"\n👉 ZERO-TOUCH INVARIANT: Execute all file edits & tests inside:\n   cd {wt_path}\n")
    return 0


def _worktree_return(fsm: Any, args: argparse.Namespace) -> int:
    path_to_return = getattr(args, "path", None) or fsm.state.active_worktree or (fsm.state.active_ticket.worktree_path if fsm.state.active_ticket else None)
    if not path_to_return:
        print("❌ No active worktree recorded to return. Specify --path.")
        return 1
    return_fn = resolve_symbol("return_worktree", "tools.brigade.worktree")
    ok, msg = return_fn(fsm.target_repo, path_to_return, force=getattr(args, "force", False))
    if not ok:
        print(f"❌ Failed to return worktree: {msg}")
        return 1
    if fsm.state.active_worktree == path_to_return:
        fsm.state.active_worktree = None
    if fsm.state.active_ticket and fsm.state.active_ticket.worktree_path == path_to_return:
        fsm.state.active_ticket.worktree_path = None
    fsm.save()
    print(f"✅ Worktree at '{path_to_return}' returned to Treehouse pool.")
    return 0


def cmd_worktree(args: argparse.Namespace) -> int:
    """Inspect, lease, or return a Treehouse worktree."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    action = getattr(args, "action", "status")
    if action == "lease":
        return _worktree_lease(fsm, args)
    if action == "return":
        return _worktree_return(fsm, args)
    print("\n=======================================================\n🌳  TREEHOUSE WORKTREE STATUS\n=======================================================")
    print(f"Repository:      {fsm.target_repo}\nActive Worktree: {fsm.state.active_worktree or 'None (idle/no active lease)'}")
    ok, out, err = resolve_symbol("get_pool_status", "tools.brigade.worktree")(fsm.target_repo)
    print(f"\n--- Treehouse Pool Status ---\n{out}" if ok else f"\n⚠️ Could not query Treehouse status: {err}")
    print("=======================================================\n")
    return 0


def cmd_check_heat(args: argparse.Namespace) -> int:
    """Measure context window token heat for a transcript path."""
    transcript_path = Path(args.transcript)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(normalize_target_path(getattr(args, "repo", ".")))
    zone, tokens, recommendation = fsm.check_heat(transcript_path)
    zone_icons = {"GREEN": "🟢 GREEN ZONE (Optimal)", "YELLOW": "🟡 YELLOW ZONE (Drain & Freeze)", "RED": "🔴 RED ZONE (Emergency Checkpoint)"}
    z_str = zone.value if hasattr(zone, "value") else str(zone)
    print("\n=======================================================\n🌡️  CONTEXT HEAT MONITOR\n=======================================================")
    print(f"Transcript Path:  {transcript_path}\nEstimated Tokens: {tokens:,}\nHeat Status:      {zone_icons.get(z_str, z_str)}")
    print(f"\nPolicy Recommendation:\n   {recommendation}\n=======================================================\n")
    return 0
