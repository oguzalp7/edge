#!/usr/bin/env python3
"""CLI Interface Facade for Edge Brigade."""

import importlib
from pathlib import Path
import sys
from typing import Any, Dict, Tuple

_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from tools.common import setup_utf8_console

setup_utf8_console()

from tools.brigade.cli_ops.parser import COMMAND_MAP, build_parser, dispatch_command

_EXTRA_EXPORTS: Dict[str, Tuple[str, str]] = {
    "BrigadeFSM": ("tools.brigade.fsm", "BrigadeFSM"),
    "StationRegistry": ("tools.brigade.stations", "StationRegistry"),
    "FlightRecorder": ("tools.brigade.flight_recorder", "FlightRecorder"),
    "run_spec_critique": ("tools.brigade.spec_critic", "run_spec_critique"),
    "PRIMARY_CRITIC_MODEL": ("tools.brigade.spec_critic", "PRIMARY_CRITIC_MODEL"),
    "FALLBACK_CRITIC_MODEL": ("tools.brigade.spec_critic", "FALLBACK_CRITIC_MODEL"),
    "get_tier_status": ("tools.brigade.tier", "get_tier_status"),
    "switch_tier": ("tools.brigade.tier", "switch_tier"),
    "format_tier_card": ("tools.brigade.tier", "format_tier_card"),
    "prepare_ship_payload": ("tools.brigade.ship_prep", "prepare_ship_payload"),
    "format_ship_output": ("tools.brigade.ship_prep", "format_ship_output"),
    "discover_project_routes": ("tools.brigade.smoke_routes", "discover_project_routes"),
    "run_route_smoke_scan": ("tools.brigade.smoke_routes", "run_route_smoke_scan"),
    "triage_smoke_failures": ("tools.brigade.smoke_routes", "triage_smoke_failures"),
    "format_smoke_report": ("tools.brigade.smoke_routes", "format_smoke_report"),
    "run_security_audit": ("tools.brigade.security_audit", "run_security_audit"),
    "triage_security_findings": ("tools.brigade.security_audit", "triage_security_findings"),
    "format_security_report": ("tools.brigade.security_audit", "format_security_report"),
    "acquire_worktree": ("tools.brigade.worktree", "acquire_worktree"),
    "return_worktree": ("tools.brigade.worktree", "return_worktree"),
    "get_pool_status": ("tools.brigade.worktree", "get_pool_status"),
    "is_treehouse_installed": ("tools.brigade.worktree", "is_treehouse_installed"),
    "is_worktree_backend_available": ("tools.brigade.worktree", "is_worktree_backend_available"),
    "prune_worktrees": ("tools.brigade.worktree", "prune_worktrees"),
    "run_command": ("tools.common", "run_command"),
    "normalize_target_path": ("tools.common", "normalize_target_path"),
    "toon_encode": ("tools.common", "toon_encode"),
    "StationRole": ("tools.brigade.models", "StationRole"),
    "CycleState": ("tools.brigade.models", "CycleState"),
    "ReviewFinding": ("tools.brigade.models", "ReviewFinding"),
    "Ticket": ("tools.brigade.models", "Ticket"),
    "ExaminerReceipt": ("tools.brigade.models", "ExaminerReceipt"),
}
_CMD_EXPORTS: Dict[str, Tuple[str, str]] = {fn_name: (mod_path, fn_name) for mod_path, fn_name in COMMAND_MAP.values()}


def __getattr__(name: str) -> Any:
    target = _CMD_EXPORTS.get(name) or _EXTRA_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target[0]), target[1])


def main() -> int:
    """Parse Edge Brigade CLI arguments and dispatch subcommand."""
    args = build_parser().parse_args()
    return dispatch_command(args.command, args)


if __name__ == "__main__":
    sys.exit(main())
