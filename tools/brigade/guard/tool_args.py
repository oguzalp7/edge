"""Tool argument parsing and WSL path normalization helpers (stdlib-only)."""

import json
from pathlib import Path
from typing import Any, Dict, List


def to_wsl_path(p_str: str) -> Path:
    """Convert host paths into runtime Path objects via cross-OS env helper."""
    if not p_str:
        return Path("")
    from tools.common import env as _edge_env

    return _edge_env.resolve_host_path(p_str)


def parse_subagents(raw_subagents: Any) -> List[Dict[str, Any]]:
    """Parse Subagents list or JSON string into list of dicts."""
    if isinstance(raw_subagents, list):
        return raw_subagents
    if isinstance(raw_subagents, str) and raw_subagents.strip():
        try:
            parsed = json.loads(raw_subagents)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def extract_requested_roles(args: dict) -> List[str]:
    """Extract role names from Role or Subagents invoke_subagent args."""
    roles = [str(args.get("Role") or args.get("role")).strip()] if (args.get("Role") or args.get("role")) else []
    for sa in parse_subagents(args.get("Subagents") or args.get("subagents")):
        if isinstance(sa, dict) and sa.get("Role"):
            roles.append(str(sa["Role"]).strip())
    return roles


def get_target_file(args: dict) -> str:
    """Extract normalized lowercase target file path from tool args."""
    val = args.get("Path") or args.get("path") or args.get("TargetFile") or args.get("target_file") or args.get("file_path") or ""
    return str(val).replace("\\", "/").lower()
