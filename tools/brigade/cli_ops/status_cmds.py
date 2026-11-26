"""Brigade FSM status dashboard and state-graph rendering commands."""

import argparse
import json
from pathlib import Path
from typing import Any, Tuple

from tools.brigade.cli_ops._facade import resolve_symbol
from tools.brigade.models import CycleState, StationRole
from tools.common import normalize_target_path, toon_encode

_STATE_ICONS = {
    CycleState.IDLE: "⚪ IDLE", CycleState.TRIAGE: "🔍 TRIAGE", CycleState.RED_TEST: "🔴 RED_TEST",
    CycleState.SURGERY: "🔪 SURGERY", CycleState.VERIFY: "🧪 VERIFY", CycleState.REVIEW: "🧐 REVIEW",
    CycleState.POLISH: "✨ POLISH", CycleState.GATE: "🚪 GATE", CycleState.QA: "🍷 QA",
    CycleState.STAGING: "🚢 STAGING", CycleState.COMPLETED: "🏆 COMPLETED",
    CycleState.BLOCKED: "🛑 BLOCKED", CycleState.PAUSED: "⏸️ PAUSED",
}


def _print_status_ticket(state: Any) -> None:
    ticket = state.active_ticket
    print("\n📋 ACTIVE TICKET:")
    if not ticket:
        print("   No active ticket. (Run 'triage' to pick from radar)")
        return
    print(f"   ID:          {ticket.ticket_id}\n   Domain:      {ticket.domain}")
    print(f"   Target File: {ticket.target_file}:{ticket.line_number}\n   Rule:        {ticket.rule_id} ({ticket.severity})")
    print(f"   Allowance:   +{ticket.scaffolding_allowance} lines")
    if ticket.escalation_reason:
        print(f"   ⚠️ ESCALATION: {ticket.escalation_reason} ({ticket.escalation_at})")
    if ticket.captain_decision:
        print(f"   👑 CAPTAIN DECISION: {ticket.captain_decision}")


def cmd_status(args: argparse.Namespace) -> int:
    """Print current brigade FSM state card."""
    repo_path = normalize_target_path(args.repo)
    state = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path).state
    fmt = getattr(args, "format", "human")
    if fmt in ("toon", "json"):
        data = {"brigade_status": state.to_dict()}
        print(json.dumps(data, indent=2) if fmt == "json" else toon_encode(data))
        return 0
    ticket = state.active_ticket
    print("\n=======================================================\n🎖️  EDGE BRIGADE — STATE MACHINE DASHBOARD\n=======================================================")
    print(f"Repository:      {state.repo_path}\nBase Branch:     {state.base_branch}")
    print(f"Active State:    {_STATE_ICONS.get(state.current_state, str(state.current_state))}")
    print(f"Active Branch:   {state.active_branch or 'None'}")
    print(f"Active Worktree: {state.active_worktree or (ticket.worktree_path if ticket else 'None (primary checkout)')}")
    _print_status_ticket(state)
    print(f"\n🔍 REVIEW FINDINGS ({len(state.review_findings)}):")
    for f in state.review_findings:
        print(f"   {'🔴' if f.severity == 'CRITICAL' else '🟡'} [{f.axis.upper()}] {f.file_path}:{f.line_number or 'N/A'} - {f.rule}: {f.description}")
    if not state.review_findings:
        print("   None recorded.")
    print(f"\n🏛️ STATIONS REGISTERED ({len(state.stations)}):")
    for r, s in state.stations.items():
        print(f"   - {r.upper()}: {s.name} (ID: {s.conversation_id[:8]}...) [{s.status}]")
    print("\n📜 RECENT TRANSITIONS:")
    for log in (state.history[-5:] if state.history else []):
        print(f"   - [{log.from_state} ➔ {log.to_state}]: {log.message}")
    if not state.history:
        print("   No transitions recorded yet.")
    print("=======================================================\n")
    return 0


def _read_core_ledger_counts(repo_path: Path) -> Tuple[int, int, int]:
    ledger_path = repo_path / ".edge" / "ledger" / "core.json"
    if not ledger_path.exists():
        return 0, 0, 0
    try:
        items = json.loads(ledger_path.read_text(encoding="utf-8")).get("items", [])
        return (
            sum(1 for i in items if i.get("status") == "OPEN"),
            sum(1 for i in items if i.get("status") == "RESOLVED"),
            sum(1 for i in items if i.get("status") == "STAGNATED"),
        )
    except Exception:
        return 0, 0, 0


def _print_graph_mermaid(curr: str) -> None:
    print("\n📊 MERMAID GRAPH:\n```mermaid\nstateDiagram-v2\n    direction LR")
    for edge in (
        "IDLE --> TRIAGE: triage / start-slice", "TRIAGE --> SURGERY: assign to Coder/Surgeon",
        "SURGERY --> VERIFY: test seam & tsc", "VERIFY --> GATE: hermetic verify == 0",
        "GATE --> QA: gate.py == 0 (if QA required)", "GATE --> REVIEW: gate.py == 0 (no QA)",
        "QA --> REVIEW: ProofVerifier PASS", "REVIEW --> STAGING: 3-axis PASS + seal-review",
        "REVIEW --> POLISH: CRITICAL or FAIL", "POLISH --> GATE: hermetic re-verify",
        "STAGING --> COMPLETED: ff-merge & archive spec",
    ):
        print(f"    {edge}")
    print(f"    classDef active fill:#22c55e,stroke:#15803d,stroke-width:3px,color:#fff\n    class {curr} active\n```")


def cmd_graph(args: argparse.Namespace) -> int:
    """Render ASCII and optional Mermaid brigade dispatcher state graph."""
    repo_path = normalize_target_path(args.repo)
    state = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path).state
    curr = state.current_state.value if isinstance(state.current_state, CycleState) else str(state.current_state)
    open_c, res_c, stag_c = _read_core_ledger_counts(repo_path)
    print("\n" + "=" * 65 + "\n🏛️  EDGE BRIGADE — LIVE DISPATCHER & STATE GRAPH\n" + "=" * 65)
    print(f"📍 CURRENT STATE: [{curr}]\n🌿 BASE BRANCH:   {state.base_branch}")
    print(f"📊 LEDGER DEBT:   {open_c} Open | {res_c} Resolved | {stag_c} Stagnated")
    ticket = state.active_ticket
    if ticket:
        h_b = f"{ticket.health_before}%" if ticket.health_before is not None else "N/A"
        h_a = f"{ticket.health_after}%" if ticket.health_after is not None else "(in progress)"
        print(f"\n🎫 ACTIVE TICKET: {ticket.ticket_id} [{ticket.domain}]\n   Target:        {ticket.target_file}:{ticket.line_number}")
        print(f"   Branch:        {ticket.branch_name}\n   Rule:          {ticket.rule_id} ({ticket.severity})")
        print(f"   Health Trend:  {h_b} ➔ {h_a} (SLOC: {ticket.sloc_before or 'N/A'} ➔ {ticket.sloc_after or '(in progress)'})")
        print(f"   Attempts:      {ticket.attempt_count} / {ticket.max_attempts}")
    else:
        print("\n🎫 ACTIVE TICKET: None (System is IDLE)")
    print("\n🧑‍🍳 STATION ROSTER:")
    for role in (StationRole.SPEC_WRITER, StationRole.RESEARCHER, StationRole.SEAM_ARCHITECT, StationRole.CODER, StationRole.SURGEON, StationRole.EXAMINER, StationRole.QA_ENGINEER, StationRole.SPEC_CRITIC):
        s = state.stations.get(role.value)
        dot = "🟢" if s and s.status == "IDLE" else ("🟡" if s else "⚪")
        cid_s = f"({s.conversation_id[:12]}...)" if s and s.conversation_id else ""
        print(f"   {dot} {role.value.upper():<20} {s.name if s else 'Not registered'} {cid_s}")
    flow = "".join(f" ▶ [{s}]* ➔" if s == curr else f" [{s}] ➔" for s in ("IDLE", "TRIAGE", "SURGERY", "VERIFY", "GATE", "QA", "REVIEW", "STAGING", "COMPLETED"))
    print(f"\n🔄 PIPELINE FLOW (ASCII):\n  {flow.rstrip(' ➔')}")
    if getattr(args, "format", "all") in ("mermaid", "all"):
        _print_graph_mermaid(curr)
    print("=" * 65 + "\n")
    return 0
