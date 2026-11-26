"""Station initialization, registration, listing, and debt triage CLI commands."""

import argparse
from pathlib import Path

from tools.brigade.cli_ops._facade import resolve_symbol
from tools.brigade.models import StationRole
from tools.common import normalize_target_path


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize brigade state in target repository."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    fsm.state.base_branch = args.base_branch
    fsm.save()
    print(f"✅ Brigade initialized at {repo_path}")
    print(f"   Base branch: {args.base_branch}")
    print(f"   State file:  {fsm.state_file}")
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    """Register a persistent station worker in brigade state."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    try:
        role = StationRole(args.role)
    except ValueError:
        print(f"❌ Invalid role '{args.role}'. Available roles: {[r.value for r in StationRole]}")
        return 1
    model = getattr(args, "model", "flash") or "flash"
    station = fsm.registry.register(role, args.conversation_id, args.name, model=model)
    fsm.save()
    print(f"✅ Registered station '{station.name}' [{station.role}] (model: {station.model})")
    print(f"   Conversation ID: {station.conversation_id}")
    print(f"   Model:           {station.model}")
    return 0


def cmd_unregister(args: argparse.Namespace) -> int:
    """Unregister a station worker by role."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    try:
        role = StationRole(args.role)
    except ValueError:
        print(f"❌ Invalid role '{args.role}'.")
        return 1
    if fsm.registry.unregister(role):
        fsm.save()
        print(f"✅ Unregistered station for role '{role.value}'")
        return 0
    print(f"⚠️ No station registered for role '{role.value}'")
    return 1


def cmd_stations(args: argparse.Namespace) -> int:
    """Print registered kitchen stations."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    stations = fsm.state.stations
    print("\n=======================================================")
    print("🏛️  EDGE BRIGADE — REGISTERED STATIONS")
    print("=======================================================")
    if not stations:
        print("No stations currently registered.")
        print("Register stations with: brigade register <repo> --role <role> --conversation-id <id>")
        return 0
    for station in stations.values():
        icon = "🟢" if station.status == "IDLE" else "🟡"
        print(f" {icon} [{station.role.upper()}] {station.name} [model: {station.model}]")
        print(f"    Conversation ID: {station.conversation_id}")
        print(f"    Status:          {station.status}")
        print(f"    Model:           {station.model}")
        print(f"    Last Active:     {station.last_active_at}")
        print("-------------------------------------------------------")
    return 0


def cmd_triage(args: argparse.Namespace) -> int:
    """Triage next debt item from radar ledger."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    whitelist = [w.strip() for w in args.whitelist.split(",")] if getattr(args, "whitelist", None) else None
    blacklist = [b.strip() for b in args.blacklist.split(",")] if getattr(args, "blacklist", None) else None
    transcript_path = Path(args.transcript) if getattr(args, "transcript", None) else None
    ticket = fsm.triage_next_ticket(
        track=args.track, target_domain=args.domain,
        whitelist=whitelist, blacklist=blacklist, transcript_path=transcript_path,
    )
    if not ticket:
        domain_msg = f" for domain '{args.domain}'" if args.domain else ""
        print(f"⚠️ No open debt items found or triage throttled in .edge/ledger/{args.track}.json{domain_msg}.")
        return 1
    h_b = f"{ticket.health_before}%" if ticket.health_before is not None else "N/A"
    sloc_b = f"{ticket.sloc_before} SLOC" if ticket.sloc_before is not None else ""
    print(f"\n🎯 TRIAGE COMPLETE: Ticket {ticket.ticket_id} Prepared")
    print(f"   Domain:          {ticket.domain}\n   Target File:     {ticket.target_file}:{ticket.line_number}")
    print(f"   Rule:            {ticket.rule_id} ({ticket.severity})\n   Branch:          {ticket.branch_name}")
    print(f"   Allowance:       +{ticket.scaffolding_allowance} lines\n   Test Seam:       {ticket.test_seam_command}")
    print(f"   Baseline Health: {h_b} ({sloc_b})\n\nState transitioned to TRIAGE. Next station: SURGEON.")
    return 0
