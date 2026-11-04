#!/usr/bin/env python3
"""
CLI Interface for Edge Brigade.
Deterministic Michelin Station & State Machine Orchestrator.
"""

import sys
import os
import json
import argparse
from pathlib import Path
from typing import List, Optional

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import setup_utf8_console, normalize_target_path, toon_encode, run_command
setup_utf8_console()


try:
    from .models import StationRole, CycleState, ReviewFinding, Ticket
    from .fsm import BrigadeFSM
    from .stations import StationRegistry
    from .worktree import get_pool_status, is_treehouse_installed
    from .flight_recorder import FlightRecorder
    from .spec_critic import run_spec_critique, PRIMARY_CRITIC_MODEL, FALLBACK_CRITIC_MODEL
except ImportError:
    from tools.brigade.models import StationRole, CycleState, ReviewFinding, Ticket
    from tools.brigade.fsm import BrigadeFSM
    from tools.brigade.stations import StationRegistry
    from tools.brigade.worktree import get_pool_status, is_treehouse_installed
    from tools.brigade.flight_recorder import FlightRecorder
    from tools.brigade.spec_critic import run_spec_critique, PRIMARY_CRITIC_MODEL, FALLBACK_CRITIC_MODEL


def cmd_init(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    fsm.state.base_branch = args.base_branch
    fsm.save()
    print(f"✅ Brigade initialized at {repo_path}")
    print(f"   Base branch: {args.base_branch}")
    print(f"   State file:  {fsm.state_file}")
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    try:
        role = StationRole(args.role)
    except ValueError:
        print(f"❌ Invalid role '{args.role}'. Available roles: {[r.value for r in StationRole]}")
        return 1

    station = fsm.registry.register(role, args.conversation_id, args.name)
    fsm.save()
    print(f"✅ Registered station '{station.name}' [{station.role}]")
    print(f"   Conversation ID: {station.conversation_id}")
    return 0


def cmd_unregister(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    try:
        role = StationRole(args.role)
    except ValueError:
        print(f"❌ Invalid role '{args.role}'.")
        return 1

    if fsm.registry.unregister(role):
        fsm.save()
        print(f"✅ Unregistered station for role '{role.value}'")
        return 0
    else:
        print(f"⚠️ No station registered for role '{role.value}'")
        return 1


def cmd_stations(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    stations = fsm.state.stations
    print("\n=======================================================")
    print("🏛️  EDGE BRIGADE — REGISTERED STATIONS")
    print("=======================================================")
    if not stations:
        print("No stations currently registered.")
        print("Register stations with: brigade register <repo> --role <role> --conversation-id <id>")
    else:
        for role_key, station in stations.items():
            status_icon = "🟢" if station.status == "IDLE" else "🟡"
            print(f" {status_icon} [{station.role.upper()}] {station.name}")
            print(f"    Conversation ID: {station.conversation_id}")
            print(f"    Status:          {station.status}")
            print(f"    Last Active:     {station.last_active_at}")
            print("-------------------------------------------------------")
    return 0


def cmd_triage(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)

    whitelist = [w.strip() for w in args.whitelist.split(",")] if getattr(args, "whitelist", None) else None
    blacklist = [b.strip() for b in args.blacklist.split(",")] if getattr(args, "blacklist", None) else None
    transcript_path = Path(args.transcript) if getattr(args, "transcript", None) else None

    ticket = fsm.triage_next_ticket(
        track=args.track,
        target_domain=args.domain,
        whitelist=whitelist,
        blacklist=blacklist,
        transcript_path=transcript_path,
    )
    if not ticket:
        domain_msg = f" for domain '{args.domain}'" if args.domain else ""
        print(f"⚠️ No open debt items found or triage throttled in .edge/ledger/{args.track}.json{domain_msg}.")
        return 1

    h_b = f"{ticket.health_before}%" if ticket.health_before is not None else "N/A"
    sloc_b = f"{ticket.sloc_before} SLOC" if ticket.sloc_before is not None else ""

    print(f"\n🎯 TRIAGE COMPLETE: Ticket {ticket.ticket_id} Prepared")
    print(f"   Domain:          {ticket.domain}")
    print(f"   Target File:     {ticket.target_file}:{ticket.line_number}")
    print(f"   Rule:            {ticket.rule_id} ({ticket.severity})")
    print(f"   Branch:          {ticket.branch_name}")
    print(f"   Allowance:       +{ticket.scaffolding_allowance} lines")
    print(f"   Test Seam:       {ticket.test_seam_command}")
    print(f"   Baseline Health: {h_b} ({sloc_b})")
    print("\nState transitioned to TRIAGE. Next station: SURGEON.")
    return 0


def cmd_ticket(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    ticket = fsm.state.active_ticket
    if not ticket:
        print("No active ticket found. Run 'triage' first.")
        return 1

    if args.prompt:
        # Check flight recorder for zero-amnesia negative constraints block
        recorder = FlightRecorder(repo_path, ticket.ticket_id)
        alert_block = recorder.get_prompt_alert_block()

        # Generate prompt for current station / state
        curr = fsm.state.current_state
        print(f"\n--- PROMPT PAYLOAD FOR STATE [{curr.value}] ---")
        if alert_block:
            print(alert_block)
        if curr == CycleState.RED_TEST:
            print(StationRegistry.build_seam_architect_prompt(ticket, ticket.description or ticket.suggested_fix, repo_path=repo_path))
        elif curr == CycleState.SURGERY or curr == CycleState.TRIAGE:
            if getattr(ticket, "track", "core") == "feature":
                print(StationRegistry.build_coder_prompt(ticket, ticket.test_seam_command, repo_path=repo_path))
            else:
                print(StationRegistry.build_surgeon_prompt(ticket, fsm.state.base_branch, repo_path=repo_path))
        elif curr == CycleState.REVIEW:
            print("=== EXAMINER REVIEW PROMPT ===")
            print(StationRegistry.build_examiner_prompt(ticket, fsm.state.base_branch, repo_path=repo_path))
        elif curr == CycleState.POLISH:
            if getattr(ticket, "track", "core") == "feature":
                print(StationRegistry.build_coder_polish_prompt(ticket, fsm.state.review_findings, repo_path=repo_path))
            else:
                print(StationRegistry.build_polish_prompt(ticket, fsm.state.review_findings, repo_path=repo_path))
        elif curr == CycleState.STAGING:
            print(f"STAGING STATE: Run deterministic CLI delivery command:\nbrigade finish-slice {repo_path}")
        else:
            print(f"No prompt template defined for state {curr.value}.")
        print("--- END PROMPT PAYLOAD ---\n")
    else:
        fmt = getattr(args, "format", "toon")
        if fmt == "json":
            print(json.dumps(ticket.to_dict(), indent=2))
        else:
            print(toon_encode(ticket.to_dict()))

    return 0



def _dispatch_prompt(slug: str, ticket: Ticket, repo_path: Path, base_branch: str) -> str:
    dispatch = {
        "coder": lambda: StationRegistry.build_coder_prompt(ticket, ticket.test_seam_command or "pytest", repo_path=repo_path),
        "surgeon": lambda: StationRegistry.build_surgeon_prompt(ticket, base_branch, repo_path=repo_path),
        "examiner": lambda: StationRegistry.build_examiner_prompt(ticket, base_branch, repo_path=repo_path),
        "seam_architect": lambda: StationRegistry.build_seam_architect_prompt(ticket, ticket.description or ticket.suggested_fix, repo_path=repo_path),
        "seam": lambda: StationRegistry.build_seam_architect_prompt(ticket, ticket.description or ticket.suggested_fix, repo_path=repo_path),
        "researcher": lambda: StationRegistry.build_researcher_prompt(ticket, ticket.description or "Research topic", repo_path=repo_path),
        "spec_writer": lambda: StationRegistry.build_spec_writer_prompt(ticket, ticket.description or "User story", repo_path=repo_path),
        "qa_engineer": lambda: StationRegistry.build_qa_prompt(user_scenario_en=ticket.description or ticket.ticket_id, target_route="http://localhost:3000", repo_path=repo_path),
        "spec_critic": lambda: StationRegistry.load_station_rubric("spec-critic", repo_path=repo_path),
        "orchestrator": lambda: StationRegistry.load_station_rubric("orchestrator", repo_path=repo_path),
    }
    handler = dispatch.get(slug)
    if handler:
        return handler()
    return StationRegistry.load_station_rubric(slug, repo_path=repo_path)


def cmd_prompt(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    slug = args.role.lower().strip().replace("-", "_")

    ticket = fsm.state.active_ticket
    if getattr(args, "ticket", None) and ticket and ticket.ticket_id != args.ticket:
        ticket = None

    if not ticket:
        print(StationRegistry.load_station_rubric(slug, repo_path=repo_path))
        return 0

    alert_block = FlightRecorder(repo_path, ticket.ticket_id).get_prompt_alert_block()
    if alert_block:
        print(alert_block)

    print(_dispatch_prompt(slug, ticket, repo_path, fsm.state.base_branch))
    return 0


def cmd_add_finding(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    finding = ReviewFinding(
        axis=args.axis,
        severity=args.severity.upper(),
        file_path=args.file,
        rule=args.rule,
        description=args.desc,
        suggested_fix=args.fix or "Remediate finding in code.",
        line_number=args.line,
    )
    fsm.state.review_findings.append(finding)
    fsm.save()
    print(f"✅ Added {args.severity.upper()} finding ({args.axis}) in {args.file}")
    return 0


def cmd_clear_findings(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    count = len(fsm.state.review_findings)
    fsm.state.review_findings = []
    fsm.save()
    print(f"✅ Cleared {count} review findings.")
    return 0


def cmd_advance(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    prev = fsm.state.current_state
    success, next_state, message = fsm.advance(force=args.force)
    
    if success:
        print(f"🚀 STATE ADVANCED: [{prev.value}] ➔ [{next_state.value}]")
        print(f"   Result: {message}")
        return 0
    else:
        print(f"❌ STATE TRANSITION BLOCKED: Remained at [{prev.value}]")
        print(f"   Reason: {message}")
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    state = fsm.state

    fmt = getattr(args, "format", "human")
    if fmt in ("toon", "json"):
        data = {"brigade_status": state.to_dict()}
        if fmt == "json":
            print(json.dumps(data, indent=2))
        else:
            print(toon_encode(data))
        return 0


    state_icons = {
        CycleState.IDLE: "⚪ IDLE",
        CycleState.TRIAGE: "🔍 TRIAGE",
        CycleState.RED_TEST: "🔴 RED_TEST",
        CycleState.SURGERY: "🔪 SURGERY",
        CycleState.VERIFY: "🧪 VERIFY",
        CycleState.REVIEW: "🧐 REVIEW",
        CycleState.POLISH: "✨ POLISH",
        CycleState.GATE: "🚪 GATE",
        CycleState.STAGING: "🚢 STAGING",
        CycleState.COMPLETED: "🏆 COMPLETED",
        CycleState.BLOCKED: "🛑 BLOCKED",
        CycleState.PAUSED: "⏸️ PAUSED",
    }


    print("\n=======================================================")
    print("🎖️  EDGE BRIGADE — STATE MACHINE DASHBOARD")
    print("=======================================================")
    print(f"Repository:      {state.repo_path}")
    print(f"Base Branch:     {state.base_branch}")
    print(f"Active State:    {state_icons.get(state.current_state, str(state.current_state))}")
    print(f"Active Branch:   {state.active_branch or 'None'}")
    ticket = state.active_ticket
    print(f"Active Worktree: {state.active_worktree or (ticket.worktree_path if ticket else 'None (primary checkout)')}")

    print("\n📋 ACTIVE TICKET:")
    if ticket:
        print(f"   ID:          {ticket.ticket_id}")
        print(f"   Domain:      {ticket.domain}")
        print(f"   Target File: {ticket.target_file}:{ticket.line_number}")
        print(f"   Rule:        {ticket.rule_id} ({ticket.severity})")
        print(f"   Allowance:   +{ticket.scaffolding_allowance} lines")
        if ticket.escalation_reason:
            print(f"   ⚠️ ESCALATION: {ticket.escalation_reason} ({ticket.escalation_at})")
        if ticket.captain_decision:
            print(f"   👑 CAPTAIN DECISION: {ticket.captain_decision}")
    else:
        print("   No active ticket. (Run 'triage' to pick from radar)")

    print(f"\n🔍 REVIEW FINDINGS ({len(state.review_findings)}):")
    if state.review_findings:
        for f in state.review_findings:
            sev_badge = "🔴" if f.severity == "CRITICAL" else "🟡"
            print(f"   {sev_badge} [{f.axis.upper()}] {f.file_path}:{f.line_number or 'N/A'} - {f.rule}: {f.description}")
    else:
        print("   None recorded.")

    print(f"\n🏛️ STATIONS REGISTERED ({len(state.stations)}):")
    for r, s in state.stations.items():
        print(f"   - {r.upper()}: {s.name} (ID: {s.conversation_id[:8]}...) [{s.status}]")

    print("\n📜 RECENT TRANSITIONS:")
    if state.history:
        for log in state.history[-5:]:
            print(f"   - [{log.from_state} ➔ {log.to_state}]: {log.message}")
    else:
        print("   No transitions recorded yet.")
    print("=======================================================\n")
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    state = fsm.state
    curr = state.current_state.value if isinstance(state.current_state, CycleState) else str(state.current_state)
    ticket = state.active_ticket

    # Load ledger summary
    ledger_path = repo_path / ".edge" / "ledger" / "core.json"
    open_count = 0
    resolved_count = 0
    stagnated_count = 0
    if ledger_path.exists():
        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                ldata = json.load(f)
                items = ldata.get("items", [])
                open_count = sum(1 for i in items if i.get("status") == "OPEN")
                resolved_count = sum(1 for i in items if i.get("status") == "RESOLVED")
                stagnated_count = sum(1 for i in items if i.get("status") == "STAGNATED")
        except Exception:
            pass

    # Print ASCII State Board
    print("\n" + "=" * 65)
    print("🏛️  EDGE BRIGADE — LIVE DISPATCHER & STATE GRAPH")
    print("=" * 65)
    print(f"📍 CURRENT STATE: [{curr}]")
    print(f"🌿 BASE BRANCH:   {state.base_branch}")
    print(f"📊 LEDGER DEBT:   {open_count} Open | {resolved_count} Resolved | {stagnated_count} Stagnated")

    if ticket:
        h_b = f"{ticket.health_before}%" if ticket.health_before is not None else "N/A"
        h_a = f"{ticket.health_after}%" if ticket.health_after is not None else "(in progress)"
        sloc_b = str(ticket.sloc_before) if ticket.sloc_before is not None else "N/A"
        sloc_a = str(ticket.sloc_after) if ticket.sloc_after is not None else "(in progress)"
        print(f"\n🎫 ACTIVE TICKET: {ticket.ticket_id} [{ticket.domain}]")
        print(f"   Target:        {ticket.target_file}:{ticket.line_number}")
        print(f"   Branch:        {ticket.branch_name}")
        print(f"   Rule:          {ticket.rule_id} ({ticket.severity})")
        print(f"   Health Trend:  {h_b} ➔ {h_a} (SLOC: {sloc_b} ➔ {sloc_a})")
        print(f"   Attempts:      {ticket.attempt_count} / {ticket.max_attempts}")
    else:
        print("\n🎫 ACTIVE TICKET: None (System is IDLE)")

    print("\n🧑‍🍳 STATION ROSTER:")
    stations = state.stations
    for role in [
        StationRole.SPEC_WRITER,
        StationRole.RESEARCHER,
        StationRole.SEAM_ARCHITECT,
        StationRole.CODER,
        StationRole.SURGEON,
        StationRole.EXAMINER,
        StationRole.QA_ENGINEER,
        StationRole.SPEC_CRITIC,
    ]:
        s = stations.get(role.value)
        status_dot = "🟢" if s and s.status == "IDLE" else ("🟡" if s else "⚪")
        name_str = s.name if s else "Not registered"
        cid_str = f"({s.conversation_id[:12]}...)" if s and s.conversation_id else ""
        print(f"   {status_dot} {role.value.upper():<20} {name_str} {cid_str}")

    print("\n🔄 PIPELINE FLOW (ASCII):")
    states = ["IDLE", "TRIAGE", "SURGERY", "VERIFY", "REVIEW", "GATE", "STAGING", "COMPLETED"]
    flow_str = ""
    for s in states:
        if s == curr:
            flow_str += f" ▶ [{s}]* ➔"
        else:
            flow_str += f" [{s}] ➔"
    print(f"  {flow_str.rstrip(' ➔')}")

    if getattr(args, "format", "all") in ("mermaid", "all"):
        print("\n📊 MERMAID GRAPH:")
        print("```mermaid")
        print("stateDiagram-v2")
        print("    direction LR")
        print("    IDLE --> TRIAGE: triage (whitelist/blacklist)")
        print("    TRIAGE --> SURGERY: assign to Surgeon")
        print("    SURGERY --> VERIFY: test seam & tsc")
        print("    VERIFY --> REVIEW: vitest == 0")
        print("    REVIEW --> GATE: Standards PASS")
        print("    GATE --> STAGING: gate.py exit 0")
        print("    GATE --> STAGNATED: fail (attempts >= N)")
        print("    STAGING --> COMPLETED: squash-merge & ledger resolved")
        print(f"    classDef active fill:#22c55e,stroke:#15803d,stroke-width:3px,color:#fff")
        print(f"    class {curr} active")
        print("```")
    print("=" * 65 + "\n")
    return 0


def cmd_abort(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    force = getattr(args, "force", True)
    constraint = getattr(args, "constraint", None)
    fsm.abort(reason=args.reason, force=force, negative_constraint=constraint)
    print(f"🛑 Cycle aborted. Worktree returned to Treehouse pool, state reset to IDLE.")
    print(f"   Reason: {args.reason}")
    if constraint:
        print(f"   Negative Constraint: {constraint}")
    return 0


def cmd_escalate(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    if not fsm.state.active_ticket:
        print("⚠️ No active ticket to escalate. Brigade is currently IDLE.")
        return 1

    checkpoint = fsm.escalate(reason=args.reason)
    ticket = fsm.state.active_ticket
    print("\n=======================================================")
    print("🚨  EDGE BRIGADE — TICKET ESCALATED TO CAPTAIN")
    print("=======================================================")
    print(f"Ticket ID:     {ticket.ticket_id}")
    print(f"State Frozen:  [{checkpoint.fsm_state}]")
    print(f"Worktree:      {ticket.worktree_path or 'Primary'}")
    print(f"Reason:        {args.reason}")
    print(f"\nExecution is safely PAUSED. Worktree and uncommitted changes are preserved.")
    print("To resolve and release the ticket after decision, run:")
    print(f'   python tools/brigade/cli.py release {args.repo} --decision "<captain_decision>"')
    print("=======================================================\n")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    if fsm.state.current_state != CycleState.PAUSED:
        print(f"⚠️ Brigade is not paused (Current state: [{fsm.state.current_state.value}]).")
        return 1

    success, checkpoint, message = fsm.release(decision=args.decision)
    if not success:
        print(f"⚠️ Failed to release: {message}")
        return 1

    print("\n=======================================================")
    print("👑  EDGE BRIGADE — ESCALATION RESOLVED & RELEASED")
    print("=======================================================")
    print(f"Decision:       {args.decision}")
    print(f"Restored State: [{fsm.state.current_state.value}]")
    print(f"Active Branch:  {fsm.state.active_branch or 'None'}")
    print(f"Next Action:    {checkpoint.next_action if checkpoint else 'Continue'}")
    print("=======================================================\n")
    return 0


def cmd_worktree(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    action = getattr(args, "action", "status")

    if action == "lease":
        branch = getattr(args, "branch", None)
        if not branch:
            if fsm.state.active_ticket:
                branch = fsm.state.active_ticket.branch_name
            else:
                print("❌ --branch is required to lease a worktree when no active ticket is present.")
                return 1
        
        holder = getattr(args, "holder", "edge-brigade")
        ok, wt_path, err = acquire_worktree(fsm.target_repo, branch_name=branch, lease_holder=holder)
        if not ok:
            print(f"❌ Failed to acquire Treehouse worktree: {err}")
            return 1
        
        fsm.state.active_worktree = wt_path
        if fsm.state.active_ticket:
            fsm.state.active_ticket.worktree_path = wt_path
        fsm.save()

        print("\n=======================================================")
        print("🌳  TREEHOUSE WORKTREE LEASED")
        print("=======================================================")
        print(f"Repository:      {fsm.target_repo}")
        print(f"Branch:          {branch}")
        print(f"Worktree Path:   {wt_path}")
        print("=======================================================")
        print(f"\n👉 ZERO-TOUCH INVARIANT: Execute all file edits & tests inside:\n   cd {wt_path}\n")
        return 0

    elif action == "return":
        path_to_return = getattr(args, "path", None) or fsm.state.active_worktree
        if not path_to_return:
            if fsm.state.active_ticket and fsm.state.active_ticket.worktree_path:
                path_to_return = fsm.state.active_ticket.worktree_path
            else:
                print("❌ No active worktree recorded to return. Specify --path.")
                return 1

        force = getattr(args, "force", False)
        ok, msg = return_worktree(fsm.target_repo, path_to_return, force=force)
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

    # default: status
    print("\n=======================================================")
    print("🌳  TREEHOUSE WORKTREE STATUS")
    print("=======================================================")
    print(f"Repository:      {fsm.target_repo}")
    print(f"Active Worktree: {fsm.state.active_worktree or 'None (idle/no active lease)'}")

    ok, out, err = get_pool_status(fsm.target_repo)
    if ok:
        print("\n--- Treehouse Pool Status ---")
        print(out)
    else:
        print(f"\n⚠️ Could not query Treehouse status: {err}")
    print("=======================================================\n")
    return 0


def cmd_start_slice(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)

    expected_files = (
        [f.strip() for f in args.expected_files.split(",") if f.strip()]
        if getattr(args, "expected_files", None)
        else None
    )
    spec_path = getattr(args, "spec", None)

    ok, ticket, msg = fsm.start_slice(
        name=args.name,
        track=getattr(args, "track", "feature"),
        target_file=getattr(args, "target_file", ""),
        domain=getattr(args, "domain", ""),
        test_seam_command=getattr(args, "test_cmd", "npm run test:unit"),
        allow_schema_migration=getattr(args, "allow_migration", True),
        auto_lease_worktree=True,
        expected_files=expected_files,
        spec_path=spec_path,
    )
    if not ok:
        print(f"❌ {msg}")
        return 1

    print("\n=======================================================")
    print("🚀  EDGE BRIGADE — VERTICAL SLICE INITIATED")
    print("=======================================================")
    print(f"Ticket ID:       {ticket.ticket_id}")
    print(f"Initial State:   {fsm.state.current_state.value}")
    print(f"Track:           {ticket.track.upper()}")
    print(f"Domain:          {ticket.domain}")
    print(f"Branch:          {ticket.branch_name}")
    print(f"Target File:     {ticket.target_file}")
    if ticket.expected_files:
        print(f"Expected Files:  {', '.join(ticket.expected_files)}")
    if ticket.spec_path:
        print(f"Spec Path:       {ticket.spec_path}")
    print(f"Test Seam:       {ticket.test_seam_command}")
    print(f"Worktree Path:   {ticket.worktree_path or 'Primary (no treehouse)'}")
    print("=======================================================")
    if ticket.worktree_path:
        print(f"\n🛡️ ZERO-TOUCH INVARIANT: Coder/Surgeon MUST work strictly inside:")
        print(f"   cd {ticket.worktree_path}\n")
    return 0


def cmd_critique_spec(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    res = run_spec_critique(
        repo_path=repo_path,
        spec_path=args.spec,
        primary_model=getattr(args, "model", PRIMARY_CRITIC_MODEL),
        fallback_model=getattr(args, "fallback_model", FALLBACK_CRITIC_MODEL),
        timeout=getattr(args, "timeout", 180),
    )
    print("\n=======================================================")
    print("🐟  EDGE BRIGADE — SPEC CRITIC (GOLDFISH CRITIC)")
    print("=======================================================")
    print(f"Status:             {'SUCCESS' if res.success else 'FAILED'}")
    print(f"Model Used:         {res.model_used}")
    print(f"Fallback Triggered: {res.fallback_triggered}")
    if res.report_path:
        print(f"Report Path:        {res.report_path}")
    if res.summary:
        print(f"Summary:            {res.summary}")
    if res.error:
        print(f"Error:              {res.error}")
    print("=======================================================\n")
    return 0 if res.success else 1


def cmd_finish_slice(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    ok, msg = fsm.finish_slice()
    if not ok:
        print(f"❌ {msg}")
        return 1

    print("\n=======================================================")
    print("✅  EDGE BRIGADE — VERTICAL SLICE FINISHED")
    print("=======================================================")
    print(msg)
    print("=======================================================\n")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    checkpoint = fsm.pause(reason=args.reason)

    print("\n=======================================================")
    print("⏸️  EDGE BRIGADE — EXECUTION PAUSED SAFELY")
    print("=======================================================")
    print(f"Repository:       {fsm.target_repo}")
    print(f"Prior State:      [{checkpoint.fsm_state}]")
    print(f"Reason:           {checkpoint.reason}")
    print(f"Active Ticket:    {checkpoint.active_ticket.ticket_id if checkpoint.active_ticket else 'None'}")
    print(f"Active Branch:    {checkpoint.active_branch or 'None'}")
    print(f"WIP Commit SHA:   {checkpoint.wip_commit_sha or 'None'}")
    print(f"Uncommitted Work: {'Committed as WIP' if checkpoint.has_uncommitted_work else 'Clean'}")
    print(f"Checkpoint File:  {fsm.checkpoint_file}")
    print(f"\nNext Action:      {checkpoint.next_action}")
    print(f"\nTo resume in a new/clean session, run:")
    print(f"   python tools/brigade/cli.py resume {args.repo}")
    print("=======================================================\n")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    fsm = BrigadeFSM(repo_path)
    success, checkpoint, message = fsm.resume()

    if not success:
        print(f"⚠️ {message}")
        return 1

    print("\n=======================================================")
    print("▶️  EDGE BRIGADE — EXECUTION RESUMED")
    print("=======================================================")
    print(f"Repository:       {fsm.target_repo}")
    print(f"Restored State:   [{fsm.state.current_state.value}]")
    print(f"Active Branch:    {fsm.state.active_branch or 'None'}")
    ticket = fsm.state.active_ticket
    if ticket:
        print(f"Active Ticket:    {ticket.ticket_id} [{ticket.domain}]")
        print(f"Target File:      {ticket.target_file}:{ticket.line_number}")
        print(f"Rule:             {ticket.rule_id} ({ticket.severity})")
    print(f"\nNext Action:      {checkpoint.next_action if checkpoint else 'Continue pipeline'}")
    print("=======================================================\n")
    return 0


def cmd_check_heat(args: argparse.Namespace) -> int:
    transcript_path = Path(args.transcript)
    repo_path = normalize_target_path(getattr(args, "repo", "."))
    fsm = BrigadeFSM(repo_path)
    zone, tokens, recommendation = fsm.check_heat(transcript_path)

    zone_icons = {
        "GREEN": "🟢 GREEN ZONE (Optimal)",
        "YELLOW": "🟡 YELLOW ZONE (Drain & Freeze)",
        "RED": "🔴 RED ZONE (Emergency Checkpoint)",
    }

    print("\n=======================================================")
    print("🌡️  CONTEXT HEAT MONITOR")
    print("=======================================================")
    print(f"Transcript Path:  {transcript_path}")
    print(f"Estimated Tokens: {tokens:,}")
    print(f"Heat Status:      {zone_icons.get(zone.value if hasattr(zone, 'value') else str(zone), str(zone))}")
    print(f"\nPolicy Recommendation:")
    print(f"   {recommendation}")
    print("=======================================================\n")
    return 0


def cmd_distill(args: argparse.Namespace) -> int:
    from tools.distill.cli import main as distill_main
    distill_args = getattr(args, "distill_args", [])
    return distill_main(distill_args)

def cmd_qa_inspect(args: argparse.Namespace) -> int:
    from tools.brigade.qa_fiber import inspect_fiber
    repo_path = normalize_target_path(getattr(args, "repo", "."))
    res = inspect_fiber(
        query=args.query,
        repo_path_str=repo_path,
        log_frontier=args.frontier or bool(getattr(args, "issue", None)),
        issue=getattr(args, "issue", "") or "",
        category=getattr(args, "category", None)
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("success") else 1

    if not res.get("success"):
        print(f"❌ Fiber Inspection Failed: {res.get('error')}")
        return 1

    el = res["element"]
    loc = res.get("location")
    print("🎯 React Component Located Successfully:")
    print(f"   Query:       {res['query']}")
    print(f"   Component:   {res['component']}")
    if loc:
        print(f"   Source File: {loc['file']}:{loc['line']}")
    else:
        print("   Source File: (Could not resolve source file in repo)")
    print(f"   Element:     <{el['tag']}> \"{el['text']}\"")
    if el.get('classes'):
        print(f"   Classes:     {el['classes']}")
    print(f"   Hierarchy:   {' > '.join(res['hierarchy'][:4])}")

    if res.get("frontier"):
        f_res = res["frontier"]
        if f_res.get("success"):
            print(f"\n📋 Staged to frontier-axi:")
            print(f"   ID:    {f_res.get('id')}")
            print(f"   Title: {f_res.get('title')}")
            print(f"   Via:   {f_res.get('method')}")
        else:
            print(f"\n⚠️ Frontier Staging Failed: {f_res.get('error')}")

def cmd_prototype(args: argparse.Namespace) -> int:
    repo_path = normalize_target_path(args.repo)
    action = args.action

    if action == "serve":
        if not args.file:
            print("❌ --file is required for 'serve'. Example: --file .lavish/feature.html")
            return 1
        html_file = Path(args.file)
        if not html_file.is_absolute():
            html_file = repo_path / html_file
        if not html_file.exists():
            print(f"❌ HTML file not found: {html_file}")
            return 1

        from tools.common.paths import to_wsl_path
        wsl_path = to_wsl_path(html_file)
        cmd = f"lavish-axi {wsl_path}"
        ret, stdout, stderr = run_command(cmd, cwd=repo_path)
        print(stdout)
        if stderr:
            print(stderr, file=sys.stderr)
        return ret

    elif action == "poll":
        if not args.file:
            print("❌ --file is required for 'poll'. Example: --file .lavish/feature.html")
            return 1
        html_file = Path(args.file)
        if not html_file.is_absolute():
            html_file = repo_path / html_file

        from tools.common.paths import to_wsl_path
        wsl_path = to_wsl_path(html_file)
        cmd = f"lavish-axi poll {wsl_path}"
        if getattr(args, "agent_reply", None):
            import shlex
            cmd += f" --agent-reply {shlex.quote(args.agent_reply)}"

        ret, stdout, stderr = run_command(cmd, cwd=repo_path, timeout=3600)
        print(stdout)
        if stderr:
            print(stderr, file=sys.stderr)
        return ret

    elif action == "stop":
        ret, stdout, stderr = run_command("lavish-axi stop", cwd=repo_path)
        print(stdout)
        if stderr:
            print(stderr, file=sys.stderr)
        return ret

    elif action == "status":
        cmd = "python3 -c \"import json, os; p=os.path.expanduser('~/.lavish-axi/state.json'); s=json.load(open(p)) if os.path.exists(p) else {}; print(json.dumps([{'id': k, 'file': v.get('file'), 'status': v.get('status'), 'endedAt': v.get('endedAt'), 'endedBy': v.get('endedBy')} for k, v in s.get('sessions', {}).items()], indent=2))\""
        ret, stdout, stderr = run_command(cmd, cwd=repo_path)
        print(stdout)
        return ret

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="brigade",
        description="Edge Brigade: Deterministic Michelin Station & State Machine Orchestrator",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize brigade state in target repo")
    p_init.add_argument("repo", help="Path to target repository")
    p_init.add_argument("--base-branch", default="development", help="Base branch (default: development)")

    # register
    p_reg = subparsers.add_parser("register", help="Register a persistent station worker")
    p_reg.add_argument("repo", help="Path to target repository")
    p_reg.add_argument("--role", required=True, choices=[r.value for r in StationRole], help=f"Station role ({', '.join(r.value for r in StationRole)})")
    p_reg.add_argument("--conversation-id", required=True, help="Subagent conversation ID")
    p_reg.add_argument("--name", help="Human-readable station name")

    # unregister
    p_unreg = subparsers.add_parser("unregister", help="Unregister a station")
    p_unreg.add_argument("repo", help="Path to target repository")
    p_unreg.add_argument("--role", required=True, choices=[r.value for r in StationRole], help="Station role to unregister")

    # stations
    p_stat = subparsers.add_parser("stations", help="List registered stations")
    p_stat.add_argument("repo", help="Path to target repository")

    # triage
    p_triage = subparsers.add_parser("triage", help="Triage next debt item from radar ledger")
    p_triage.add_argument("repo", help="Path to target repository")
    p_triage.add_argument("--track", default="core", choices=["core", "ui"], help="Debt track")
    p_triage.add_argument("--domain", help="Filter by domain/module name (e.g. branches, bookings)")
    p_triage.add_argument("--whitelist", help="Comma-separated domains to allow (e.g. customers,branches)")
    p_triage.add_argument("--blacklist", help="Comma-separated domains to skip (e.g. bookings)")
    p_triage.add_argument("--transcript", help="Path to transcript file to check context heat before triaging")

    # ticket
    p_ticket = subparsers.add_parser("ticket", help="View active ticket or station prompt payload")
    p_ticket.add_argument("repo", help="Path to target repository")
    p_ticket.add_argument("--prompt", action="store_true", help="Print prompt payload for current station")
    p_ticket.add_argument("--format", choices=["toon", "json"], default="toon", help="Output format: 'toon' (default, token-frugal) or 'json'")

    # add-finding
    p_find = subparsers.add_parser("add-finding", help="Record a review finding")
    p_find.add_argument("repo", help="Path to target repository")
    p_find.add_argument("--axis", required=True, choices=["standards", "spec"], help="Review axis")
    p_find.add_argument("--severity", required=True, choices=["CRITICAL", "WARNING", "ADVISORY"], help="Severity")
    p_find.add_argument("--file", required=True, help="File path with finding")
    p_find.add_argument("--rule", required=True, help="Rule ID violated")
    p_find.add_argument("--desc", required=True, help="Description of finding")
    p_find.add_argument("--fix", help="Suggested remediation")
    p_find.add_argument("--line", type=int, help="Line number")

    # clear-findings
    p_clr = subparsers.add_parser("clear-findings", help="Clear review findings")
    p_clr.add_argument("repo", help="Path to target repository")

    # advance
    p_adv = subparsers.add_parser("advance", help="Execute guards and advance to next state")
    p_adv.add_argument("repo", help="Path to target repository")
    p_adv.add_argument("--force", action="store_true", help="Force state advance bypassing guard")

    # status
    p_status = subparsers.add_parser("status", help="Print current state card")
    p_status.add_argument("repo", help="Path to target repository")
    p_status.add_argument("--format", choices=["human", "toon", "json"], default="human", help="Output format: 'human' (colored dashboard), 'toon' (token-frugal), or 'json'")

    # graph
    p_graph = subparsers.add_parser("graph", help="Display visual live state graph and station roster")
    p_graph.add_argument("repo", help="Path to target repository")
    p_graph.add_argument("--format", choices=["ascii", "mermaid", "all"], default="all", help="Output format")

    # abort
    p_abort = subparsers.add_parser("abort", help="Abort current cycle and reset to IDLE")
    p_abort.add_argument("repo", help="Path to target repository")
    p_abort.add_argument("--reason", default="Manual abort", help="Reason for aborting")
    p_abort.add_argument("--force", action="store_true", default=True, help="Force worktree cleanup")
    p_abort.add_argument("--constraint", help="Explicit negative constraint to record in flight recorder")

    # escalate
    p_esc = subparsers.add_parser("escalate", help="Escalate active ticket to captain for decision/intervention")
    p_esc.add_argument("repo", help="Path to target repository")
    p_esc.add_argument("--reason", required=True, help="Reason for escalation / question for captain")

    # release
    p_rel = subparsers.add_parser("release", help="Release escalated ticket following captain decision")
    p_rel.add_argument("repo", help="Path to target repository")
    p_rel.add_argument("--decision", required=True, help="Captain's binding decision")

    # worktree
    p_wt = subparsers.add_parser("worktree", help="Inspect or manage Treehouse worktree pool")
    p_wt.add_argument("repo", nargs="?", default=".", help="Path to target repository (default: .)")
    p_wt.add_argument("--action", choices=["status", "lease", "return"], default="status", help="Worktree action (default: status)")
    p_wt.add_argument("--branch", help="Branch name for lease")
    p_wt.add_argument("--path", help="Worktree path for return")
    p_wt.add_argument("--force", action="store_true", help="Force return worktree")
    p_wt.add_argument("--holder", default="edge-brigade", help="Lease holder tag")

    # start-slice
    p_start = subparsers.add_parser("start-slice", help="Initiate a feature or refactor slice with an isolated Treehouse worktree")
    p_start.add_argument("repo", help="Path to target repository")
    p_start.add_argument("--name", required=True, help="Slice/feature name (e.g. staff-allocation, bundle-modal)")
    p_start.add_argument("--track", default="feature", choices=["feature", "core", "ui"], help="Slice track")
    p_start.add_argument("--target-file", default="", help="Primary target file (optional)")
    p_start.add_argument("--domain", default="", help="Domain module (e.g. bookings, staff)")
    p_start.add_argument("--test-cmd", default="npm run test:unit", help="Test seam command")
    p_start.add_argument("--allow-migration", action="store_true", default=True, help="Allow schema migrations")
    p_start.add_argument("--expected-files", help="Comma-separated expected files to create or modify")
    p_start.add_argument("--spec", help="Path to specification document")

    # prompt
    p_prompt = subparsers.add_parser("prompt", help="Compose and print 2-layer prompt for a station")
    p_prompt.add_argument("repo", help="Path to target repository")
    p_prompt.add_argument("--role", required=True, help="Station role slug (e.g. coder, surgeon, examiner, qa_engineer, orchestrator)")
    p_prompt.add_argument("--ticket", help="Optional ticket ID to bind")

    # critique-spec
    p_crit = subparsers.add_parser("critique-spec", help="Run advisory cross-provider Goldfish Spec Critic (Opus 5.5 -> Flash 3.8 fallback)")
    p_crit.add_argument("repo", help="Path to target repository")
    p_crit.add_argument("--spec", required=True, help="Path to specification document")
    p_crit.add_argument("--model", default=PRIMARY_CRITIC_MODEL, help=f"Primary critic model (default: {PRIMARY_CRITIC_MODEL})")
    p_crit.add_argument("--fallback-model", default=FALLBACK_CRITIC_MODEL, help=f"Fallback critic model (default: {FALLBACK_CRITIC_MODEL})")
    p_crit.add_argument("--timeout", type=int, default=180, help="Critique timeout in seconds (default: 180)")

    # finish-slice
    p_fin = subparsers.add_parser("finish-slice", help="Fast-forward merge slice into development, release worktree, and resolve ticket")
    p_fin.add_argument("repo", help="Path to target repository")

    # pause
    p_pause = subparsers.add_parser("pause", help="Safely pause brigade execution and create durable checkpoint")
    p_pause.add_argument("repo", help="Path to target repository")
    p_pause.add_argument("--reason", default="MANUAL_PAUSE", help="Reason for pausing (e.g. CONTEXT_LIMIT, HUMAN_PAUSE)")

    # resume
    p_resume = subparsers.add_parser("resume", help="Resume brigade execution from durable checkpoint")
    p_resume.add_argument("repo", help="Path to target repository")

    # check-heat
    p_heat = subparsers.add_parser("check-heat", help="Check context window token heat from transcript")
    p_heat.add_argument("transcript", help="Path to transcript.jsonl or logs directory")
    p_heat.add_argument("--repo", default=".", help="Path to target repository (default: .)")

    # distill
    p_distill = subparsers.add_parser("distill", help="Zero-token transcript harvester, candidate pool, and pattern miner")
    p_distill.add_argument("distill_args", nargs="*", help="Arguments forwarded to edge-distill CLI")
    # qa-inspect
    p_qa = subparsers.add_parser("qa-inspect", help="Deterministic React Fiber component locator & frontier staging")
    p_qa.add_argument("query", help="CSS selector (button.confirm), XPath (//button), or text (text:Giriş Yap)")
    p_qa.add_argument("repo", nargs="?", default=".", help="Path to target repository (default: .)")
    p_qa.add_argument("--issue", help="Description of UI anomaly")
    p_qa.add_argument("--category", choices=["contrast", "overflow", "layout", "visual-regression", "misalignment"], help="Anomaly category")
    p_qa.add_argument("--frontier", action="store_true", help="Stage finding into frontier-axi")
    p_qa.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # prototype
    p_proto = subparsers.add_parser("prototype", help="Lavish-axi interactive UI prototype bridge (serve, poll, stop, status)")
    p_proto.add_argument("repo", help="Path to target repository")
    p_proto.add_argument("--action", required=True, choices=["serve", "poll", "stop", "status"], help="Prototype action")
    p_proto.add_argument("--file", help="Path to .lavish/*.html prototype file (relative or absolute)")
    p_proto.add_argument("--agent-reply", help="Optional reply text to show in Lavish Editor when resuming poll")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "register": cmd_register,
        "unregister": cmd_unregister,
        "stations": cmd_stations,
        "triage": cmd_triage,
        "ticket": cmd_ticket,
        "add-finding": cmd_add_finding,
        "clear-findings": cmd_clear_findings,
        "advance": cmd_advance,
        "status": cmd_status,
        "graph": cmd_graph,
        "abort": cmd_abort,
        "escalate": cmd_escalate,
        "release": cmd_release,
        "worktree": cmd_worktree,
        "start-slice": cmd_start_slice,
        "finish-slice": cmd_finish_slice,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "check-heat": cmd_check_heat,
        "distill": cmd_distill,
        "qa-inspect": cmd_qa_inspect,
        "prototype": cmd_prototype,
        "critique-spec": cmd_critique_spec,
        "prompt": cmd_prompt,
    }

    func = commands.get(args.command)
    if func:
        return func(args)
    return 1



if __name__ == "__main__":
    sys.exit(main())
