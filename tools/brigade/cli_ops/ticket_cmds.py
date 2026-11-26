"""Ticket inspection and two-layer station prompt composition commands."""

import argparse
import json
from pathlib import Path
from typing import Any

from tools.brigade.cli_ops._facade import resolve_symbol
from tools.brigade.models import CycleState, Ticket
from tools.common import normalize_target_path, toon_encode


def _resolve_state_prompt(fsm: Any, ticket: Ticket, repo_path: Path) -> str:
    reg = resolve_symbol("StationRegistry", "tools.brigade.stations")
    curr = fsm.state.current_state
    is_feature = getattr(ticket, "track", "core") == "feature"
    if curr == CycleState.RED_TEST:
        return reg.build_seam_architect_prompt(ticket, ticket.description or ticket.suggested_fix, repo_path=repo_path)
    if curr in (CycleState.SURGERY, CycleState.TRIAGE):
        return reg.build_coder_prompt(ticket, ticket.test_seam_command, repo_path=repo_path) if is_feature else reg.build_surgeon_prompt(ticket, fsm.state.base_branch, repo_path=repo_path)
    if curr == CycleState.GATE:
        ui_note = " + UI diff_image.py (<= 0.15%)" if getattr(ticket, "track", "core") == "ui" else ""
        return f"GATE STATE: Run deterministic verification (tools/gate.py{ui_note}) via:\nbrigade advance {repo_path}"
    if curr == CycleState.REVIEW:
        return "=== EXAMINER 3-AXIS REVIEW PROMPT ===\n" + reg.build_examiner_prompt(ticket, fsm.state.base_branch, repo_path=repo_path)
    if curr == CycleState.POLISH:
        return reg.build_coder_polish_prompt(ticket, fsm.state.review_findings, repo_path=repo_path) if is_feature else reg.build_polish_prompt(ticket, fsm.state.review_findings, repo_path=repo_path)
    if curr == CycleState.QA:
        target_route = f"/{ticket.domain.replace('_', '-')}"
        body = reg.build_qa_prompt(
            ticket=ticket, user_scenario_en=ticket.description or f"Verify UI parity and user flows for {ticket.domain}",
            target_route=target_route, lavish_path=getattr(ticket, "lavish_path", None), repo_path=repo_path,
        )
        return "=== QA ENGINEER E2E / LAVISH PARITY PROMPT ===\n" + body
    if curr == CycleState.STAGING:
        return f"STAGING STATE: Run deterministic CLI delivery command:\nbrigade finish-slice {repo_path}"
    return f"No prompt template defined for state {curr.value}."


def _print_ticket_prompt(fsm: Any, ticket: Ticket, repo_path: Path) -> None:
    recorder_cls = resolve_symbol("FlightRecorder", "tools.brigade.flight_recorder")
    alert_block = recorder_cls(repo_path, ticket.ticket_id).get_prompt_alert_block()
    print(f"\n--- PROMPT PAYLOAD FOR STATE [{fsm.state.current_state.value}] ---")
    if alert_block:
        print(alert_block)
    print(_resolve_state_prompt(fsm, ticket, repo_path))
    print("--- END PROMPT PAYLOAD ---\n")


def cmd_ticket(args: argparse.Namespace) -> int:
    """View active ticket payload or current station prompt."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    ticket = fsm.state.active_ticket
    if not ticket:
        print("No active ticket found. Run 'triage' first.")
        return 1
    if args.prompt:
        _print_ticket_prompt(fsm, ticket, repo_path)
        if fsm.state.stations:
            reg = resolve_symbol("StationRegistry", "tools.brigade.stations")
            print("\n" + reg.format_kitchen_roster(fsm.state.stations))
    else:
        fmt = getattr(args, "format", "toon")
        print(json.dumps(ticket.to_dict(), indent=2) if fmt == "json" else toon_encode(ticket.to_dict()))
    return 0


def _dispatch_prompt(slug: str, ticket: Ticket, repo_path: Path, base_branch: str) -> str:
    reg = resolve_symbol("StationRegistry", "tools.brigade.stations")
    dispatch = {
        "coder": lambda: reg.build_coder_prompt(ticket, ticket.test_seam_command or "pytest", repo_path=repo_path),
        "surgeon": lambda: reg.build_surgeon_prompt(ticket, base_branch, repo_path=repo_path),
        "examiner": lambda: reg.build_examiner_prompt(ticket, base_branch, repo_path=repo_path),
        "seam_architect": lambda: reg.build_seam_architect_prompt(ticket, ticket.description or ticket.suggested_fix, repo_path=repo_path),
        "seam": lambda: reg.build_seam_architect_prompt(ticket, ticket.description or ticket.suggested_fix, repo_path=repo_path),
        "researcher": lambda: reg.build_researcher_prompt(ticket, ticket.description or "Research topic", repo_path=repo_path),
        "spec_writer": lambda: reg.build_spec_writer_prompt(ticket, ticket.description or "User story", repo_path=repo_path),
        "qa_engineer": lambda: reg.build_qa_prompt(user_scenario_en=ticket.description or ticket.ticket_id, target_route="http://localhost:3000", repo_path=repo_path),
        "spec_critic": lambda: reg.load_station_rubric("spec-critic", repo_path=repo_path),
        "orchestrator": lambda: reg.load_station_rubric("orchestrator", repo_path=repo_path),
    }
    handler = dispatch.get(slug)
    return handler() if handler else reg.load_station_rubric(slug, repo_path=repo_path)


def cmd_prompt(args: argparse.Namespace) -> int:
    """Compose and print 2-layer prompt for a station."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    reg = resolve_symbol("StationRegistry", "tools.brigade.stations")
    slug = args.role.lower().strip().replace("-", "_")
    ticket = fsm.state.active_ticket
    if getattr(args, "ticket", None) and ticket and ticket.ticket_id != args.ticket:
        ticket = None
    if not ticket:
        print(reg.load_station_rubric(slug, repo_path=repo_path))
    else:
        recorder_cls = resolve_symbol("FlightRecorder", "tools.brigade.flight_recorder")
        alert_block = recorder_cls(repo_path, ticket.ticket_id).get_prompt_alert_block()
        if alert_block:
            print(alert_block)
        print(_dispatch_prompt(slug, ticket, repo_path, fsm.state.base_branch))
    if fsm.state.stations:
        print("\n" + reg.format_kitchen_roster(fsm.state.stations))
    return 0
