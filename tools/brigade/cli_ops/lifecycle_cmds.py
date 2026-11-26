"""Brigade cycle advance, abort, escalate, release, pause, and resume commands."""

import argparse
from typing import Any, Dict

from tools.brigade.cli_ops._facade import resolve_symbol
from tools.brigade.models import CycleState
from tools.common import normalize_target_path


def _print_handoff_banner(handoff: Dict[str, Any]) -> None:
    print("\n" + "=" * 65 + "\n🤝 NEXT STATION HANDOFF (Autonomous Kitchen Relay)\n" + "=" * 65)
    print(f"   Target State:    {handoff['target_state']}")
    print(f"   Target Role:     {handoff['target_role']} ({handoff['station_name']})")
    print(f"   Conversation ID: {handoff['recipient_cid'] or '[NOT_REGISTERED]'}")
    print(f"   Model:           {handoff['model']}\n   Suggested Action:")
    cid, inst = handoff.get("recipient_cid", ""), handoff.get("instruction", "")
    if cid:
        target_cid = "<orchestrator_cid>" if cid == "orchestrator" else cid
        print(f'     send_message(\n       Recipient: "{target_cid}",\n       Message: "{inst}"\n     )')
    else:
        print(f"     ⚠️ Station '{handoff['target_role']}' is not registered.")
        print(f"     Register with: brigade register <repo> --role {handoff['target_role']} --conversation-id <id>")
    print("=" * 65 + "\n")


def cmd_advance(args: argparse.Namespace) -> int:
    """Execute transition guards and advance FSM state."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    prev = fsm.state.current_state
    success, next_state, message = fsm.advance(force=args.force)
    if success:
        print(f"🚀 STATE ADVANCED: [{prev.value}] ➔ [{next_state.value}]\n   Result: {message}")
        _print_handoff_banner(fsm.get_next_station_handoff(next_state))
        return 0
    print(f"❌ STATE TRANSITION BLOCKED: Remained at [{prev.value}]\n   Reason: {message}")
    return 1


def cmd_abort(args: argparse.Namespace) -> int:
    """Abort current cycle and reset state to IDLE."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    constraint = getattr(args, "constraint", None)
    fsm.abort(reason=args.reason, force=getattr(args, "force", True), negative_constraint=constraint)
    print("🛑 Cycle aborted. Worktree returned to Treehouse pool, state reset to IDLE.")
    print(f"   Reason: {args.reason}")
    if constraint:
        print(f"   Negative Constraint: {constraint}")
    return 0


def cmd_escalate(args: argparse.Namespace) -> int:
    """Escalate active ticket to captain and pause execution."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    if not fsm.state.active_ticket:
        print("⚠️ No active ticket to escalate. Brigade is currently IDLE.")
        return 1
    checkpoint = fsm.escalate(reason=args.reason)
    ticket = fsm.state.active_ticket
    print("\n=======================================================\n🚨  EDGE BRIGADE — TICKET ESCALATED TO CAPTAIN\n=======================================================")
    print(f"Ticket ID:     {ticket.ticket_id}\nState Frozen:  [{checkpoint.fsm_state}]")
    print(f"Worktree:      {ticket.worktree_path or 'Primary'}\nReason:        {args.reason}")
    print("\nExecution is safely PAUSED. Worktree and uncommitted changes are preserved.")
    print(f'To resolve and release the ticket after decision, run:\n   python tools/brigade/cli.py release {args.repo} --decision "<captain_decision>"')
    print("=======================================================\n")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    """Release paused escalation with binding captain decision."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    if fsm.state.current_state != CycleState.PAUSED:
        print(f"⚠️ Brigade is not paused (Current state: [{fsm.state.current_state.value}]).")
        return 1
    success, checkpoint, message = fsm.release(decision=args.decision)
    if not success:
        print(f"⚠️ Failed to release: {message}")
        return 1
    print("\n=======================================================\n👑  EDGE BRIGADE — ESCALATION RESOLVED & RELEASED\n=======================================================")
    print(f"Decision:       {args.decision}\nRestored State: [{fsm.state.current_state.value}]")
    print(f"Active Branch:  {fsm.state.active_branch or 'None'}")
    print(f"Next Action:    {checkpoint.next_action if checkpoint else 'Continue'}")
    print("=======================================================\n")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    """Pause brigade execution and write durable checkpoint."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    cp = fsm.pause(reason=args.reason)
    print("\n=======================================================\n⏸️  EDGE BRIGADE — EXECUTION PAUSED SAFELY\n=======================================================")
    print(f"Repository:       {fsm.target_repo}\nPrior State:      [{cp.fsm_state}]\nReason:           {cp.reason}")
    print(f"Active Ticket:    {cp.active_ticket.ticket_id if cp.active_ticket else 'None'}\nActive Branch:    {cp.active_branch or 'None'}")
    print(f"WIP Commit SHA:   {cp.wip_commit_sha or 'None'}\nUncommitted Work: {'Committed as WIP' if cp.has_uncommitted_work else 'Clean'}")
    print(f"Checkpoint File:  {fsm.checkpoint_file}\n\nNext Action:      {cp.next_action}")
    print(f"\nTo resume in a new/clean session, run:\n   python tools/brigade/cli.py resume {args.repo}")
    print("=======================================================\n")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume brigade execution from durable checkpoint."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    success, cp, message = fsm.resume()
    if not success:
        print(f"⚠️ {message}")
        return 1
    print("\n=======================================================\n▶️  EDGE BRIGADE — EXECUTION RESUMED\n=======================================================")
    print(f"Repository:       {fsm.target_repo}\nRestored State:   [{fsm.state.current_state.value}]\nActive Branch:    {fsm.state.active_branch or 'None'}")
    ticket = fsm.state.active_ticket
    if ticket:
        print(f"Active Ticket:    {ticket.ticket_id} [{ticket.domain}]\nTarget File:      {ticket.target_file}:{ticket.line_number}")
        print(f"Rule:             {ticket.rule_id} ({ticket.severity})")
    print(f"\nNext Action:      {cp.next_action if cp else 'Continue pipeline'}")
    print("=======================================================\n")
    return 0
