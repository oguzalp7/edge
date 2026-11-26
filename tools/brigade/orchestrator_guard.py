#!/usr/bin/env python3
"""Antigravity Lifecycle Hook Facade: Edge Brigade Tool & Lifecycle Guard (stdlib-only)."""

import builtins
import json
from pathlib import Path
import sys
from typing import Any
from unittest.mock import MagicMock

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

builtins.MagicMock = MagicMock

from tools.brigade.guard.post_tool import handle_post_tool
from tools.brigade.guard.pre_invocation import handle_pre_invocation
from tools.brigade.guard.pre_tool import handle_pre_tool
from tools.brigade.guard.role_detection import detect_session_role
from tools.brigade.guard.station_models import (
    GREEN_HEAT_THRESHOLD,
    YELLOW_HEAT_THRESHOLD,
    StationRecord,
    TokenHeatRecord,
)
from tools.brigade.guard.station_selector import StationSelector
from tools.brigade.guard.station_store import StationStore

__all__ = [
    "ACTIVE_STATIONS_FILE",
    "GREEN_HEAT_THRESHOLD",
    "YELLOW_HEAT_THRESHOLD",
    "TokenHeatRecord",
    "StationRecord",
    "StationStore",
    "StationSelector",
    "detect_session_role",
    "handle_pre_tool",
    "handle_post_tool",
    "handle_pre_invocation",
    "main",
]

_LAZY_SUBMODULE_ATTRS = {
    "TokenHeat": "tools.brigade.guard.station_models",
    "StationStoreEnvelope": "tools.brigade.guard.station_models",
    "ACTIVE_STATIONS_FILE": "tools.brigade.guard.station_store",
    "get_active_stations_path": "tools.brigade.guard.station_store",
    "load_active_stations": "tools.brigade.guard.station_store",
    "save_active_stations": "tools.brigade.guard.station_store",
    "register_station": "tools.brigade.guard.station_store",
    "find_active_station": "tools.brigade.guard.station_store",
    "TranscriptStationScanner": "tools.brigade.guard.transcript_scanner",
    "sync_repo_brigade_station": "tools.brigade.guard.transcript_scanner",
    "_handle_invoke_subagent_guard": "tools.brigade.guard.station_selector",
    "CANONICAL_ROLES": "tools.brigade.guard.role_detection",
    "PERSISTENT_ELEPHANT_ROLES": "tools.brigade.guard.role_detection",
    "EPHEMERAL_GOLDFISH_ROLES": "tools.brigade.guard.role_detection",
    "to_wsl_path": "tools.brigade.guard.role_detection",
    "normalize_role": "tools.brigade.guard.role_detection",
    "parse_subagents": "tools.brigade.guard.role_detection",
    "extract_requested_roles": "tools.brigade.guard.role_detection",
    "get_target_file": "tools.brigade.guard.role_detection",
    "evaluate_wsl_command_guard": "tools.brigade.guard.wsl_guard",
    "_is_wsl_invocation": "tools.brigade.guard.wsl_guard",
    "_check_powershell_var_swallowing": "tools.brigade.guard.wsl_guard",
    "_check_nested_quoting_collision": "tools.brigade.guard.wsl_guard",
    "_resolve_wsl_anchor_path": "tools.brigade.guard.wsl_guard",
    "_transform_wsl_command_anchor": "tools.brigade.guard.wsl_guard",
    "_handle_run_command_wsl_guard": "tools.brigade.guard.wsl_guard",
    "is_afk_session": "tools.brigade.guard.afk_guard",
    "apply_afk_guard": "tools.brigade.guard.afk_guard",
    "_is_schema_target": "tools.brigade.guard.afk_guard",
    "is_no_mistakes_invocation": "tools.brigade.guard.no_mistakes",
    "_check_no_mistakes_transcript": "tools.brigade.guard.no_mistakes",
    "_handle_swarm_guard": "tools.brigade.guard.swarm_guard",
    "_resolve_swarm_ssot_preload": "tools.brigade.guard.swarm_guard",
    "_handle_swarm_post_tool": "tools.brigade.guard.swarm_guard",
}


def __getattr__(name: str) -> Any:
    mod_name = _LAZY_SUBMODULE_ATTRS.get(name)
    if mod_name:
        import importlib
        return getattr(importlib.import_module(mod_name), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    """CLI entrypoint invoked by Antigravity hooks.json."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre_tool"
    try:
        raw_input = sys.stdin.read()
        payload = json.loads(raw_input) if raw_input.strip() else {}
    except Exception:
        payload = {}
    if mode == "pre_invocation":
        result = handle_pre_invocation(payload)
    elif mode == "post_tool":
        result = handle_post_tool(payload)
    else:
        result = handle_pre_tool(payload)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
