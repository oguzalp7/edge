"""Unified CLI parser builder and lazy subcommand dispatcher."""

import argparse
import importlib
from typing import Dict, Tuple

from tools.brigade.cli_ops.parser_core import (
    register_escalation_parsers,
    register_pipeline_parsers,
    register_station_parsers,
    register_worktree_slice_parsers,
)
from tools.brigade.cli_ops.parser_extra import (
    register_qa_tier_parsers,
    register_refactor_parsers,
    register_ship_audit_parsers,
)

COMMAND_MAP: Dict[str, Tuple[str, str]] = {
    "init": ("tools.brigade.cli_ops.station_cmds", "cmd_init"),
    "register": ("tools.brigade.cli_ops.station_cmds", "cmd_register"),
    "unregister": ("tools.brigade.cli_ops.station_cmds", "cmd_unregister"),
    "stations": ("tools.brigade.cli_ops.station_cmds", "cmd_stations"),
    "triage": ("tools.brigade.cli_ops.station_cmds", "cmd_triage"),
    "ticket": ("tools.brigade.cli_ops.ticket_cmds", "cmd_ticket"),
    "prompt": ("tools.brigade.cli_ops.ticket_cmds", "cmd_prompt"),
    "add-finding": ("tools.brigade.cli_ops.review_cmds", "cmd_add_finding"),
    "clear-findings": ("tools.brigade.cli_ops.review_cmds", "cmd_clear_findings"),
    "seal-review": ("tools.brigade.cli_ops.review_cmds", "cmd_seal_review"),
    "prepare-ship": ("tools.brigade.cli_ops.ship_cmds", "cmd_prepare_ship"),
    "smoke-routes": ("tools.brigade.cli_ops.ship_cmds", "cmd_smoke_routes"),
    "security-audit": ("tools.brigade.cli_ops.ship_cmds", "cmd_security_audit"),
    "advance": ("tools.brigade.cli_ops.lifecycle_cmds", "cmd_advance"),
    "abort": ("tools.brigade.cli_ops.lifecycle_cmds", "cmd_abort"),
    "escalate": ("tools.brigade.cli_ops.lifecycle_cmds", "cmd_escalate"),
    "release": ("tools.brigade.cli_ops.lifecycle_cmds", "cmd_release"),
    "pause": ("tools.brigade.cli_ops.lifecycle_cmds", "cmd_pause"),
    "resume": ("tools.brigade.cli_ops.lifecycle_cmds", "cmd_resume"),
    "status": ("tools.brigade.cli_ops.status_cmds", "cmd_status"),
    "graph": ("tools.brigade.cli_ops.status_cmds", "cmd_graph"),
    "worktree": ("tools.brigade.cli_ops.worktree_cmds", "cmd_worktree"),
    "check-heat": ("tools.brigade.cli_ops.worktree_cmds", "cmd_check_heat"),
    "start-slice": ("tools.brigade.cli_ops.slice_cmds", "cmd_start_slice"),
    "finish-slice": ("tools.brigade.cli_ops.slice_cmds", "cmd_finish_slice"),
    "critique-spec": ("tools.brigade.cli_ops.slice_cmds", "cmd_critique_spec"),
    "confirm-merge": ("tools.brigade.cli_ops.slice_cmds", "cmd_confirm_merge"),
    "create-refactor-ticket": ("tools.brigade.cli_ops.refactor_cmds", "cmd_create_refactor_ticket"),
    "seal-refactor": ("tools.brigade.cli_ops.refactor_cmds", "cmd_seal_refactor"),
    "distill": ("tools.brigade.cli_ops.qa_tier_cmds", "cmd_distill"),
    "qa-inspect": ("tools.brigade.cli_ops.qa_tier_cmds", "cmd_qa_inspect"),
    "prototype": ("tools.brigade.cli_ops.qa_tier_cmds", "cmd_prototype"),
    "tier": ("tools.brigade.cli_ops.qa_tier_cmds", "cmd_tier"),
}


def build_parser() -> argparse.ArgumentParser:
    """Build full Edge Brigade argument parser across all subcommand groups."""
    parser = argparse.ArgumentParser(prog="brigade", description="Edge Brigade: Deterministic Michelin Station & State Machine Orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_station_parsers(subparsers)
    register_pipeline_parsers(subparsers)
    register_escalation_parsers(subparsers)
    register_worktree_slice_parsers(subparsers)
    register_refactor_parsers(subparsers)
    register_qa_tier_parsers(subparsers)
    register_ship_audit_parsers(subparsers)
    return parser


def dispatch_command(command: str, args: argparse.Namespace) -> int:
    """Lazily import and execute the selected subcommand handler."""
    entry = COMMAND_MAP.get(command)
    if not entry:
        return 1
    from tools.tracker.models import TrackerAuthError

    mod_path, fn_name = entry
    func = getattr(importlib.import_module(mod_path), fn_name)
    try:
        return int(func(args))
    except TrackerAuthError as exc:
        print(f"Error: {exc}")
        return exc.exit_code
