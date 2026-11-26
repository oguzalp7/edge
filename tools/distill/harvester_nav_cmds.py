"""
Shell command wrapper peeling and read/search call classification helpers.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.distill.harvester_signals import READ_SEARCH_TOOLS, SEARCH_ONLY_TOOLS

READ_SEARCH_CMDS = {"rg", "grep", "find", "git grep", "ls", "tree"}
SEARCH_ONLY_CMDS = {"rg", "grep", "find", "git grep"}
_WSL_VALUE_FLAGS = {"--cd", "-d", "--distribution", "-u", "--user"}


def _extract_tool_file_path(args: Dict[str, Any]) -> str:
    if not isinstance(args, dict):
        return ""
    raw = args.get("Path") or args.get("AbsolutePath") or args.get("TargetFile") or ""
    return str(raw).replace("\\", "/").strip()


def _peel_wsl_prefix(tokens: List[str]) -> List[str]:
    idx = 1
    while idx < len(tokens):
        tok = tokens[idx]
        if tok in _WSL_VALUE_FLAGS:
            idx += 2
        elif tok.startswith("-"):
            idx += 1
        else:
            break
    return tokens[idx:]


def _peel_command_wrappers(tokens: List[str]) -> List[str]:
    while tokens:
        head = Path(tokens[0].strip("'\"")).name.lower()
        if head == "wsl":
            tokens = _peel_wsl_prefix(tokens)
        elif head in ("bash", "sh", "zsh") and len(tokens) >= 2 and tokens[1] in ("-c", "-lc"):
            tokens = [tokens[2].lstrip("'\"")] + tokens[3:] if len(tokens) > 2 else []
        elif head == "env":
            tokens = [t for t in tokens[1:] if "=" not in t]
        else:
            break
    return tokens


def _segment_command_verb(segment: str) -> Optional[str]:
    tokens = _peel_command_wrappers(segment.strip().split())
    if not tokens:
        return None
    verb0 = Path(tokens[0].strip("'\"")).name.lower()
    if verb0 == "git" and len(tokens) > 1:
        verb1 = tokens[1].strip("'\"").lower()
        return "git grep" if verb1 == "grep" else f"git {verb1}"
    return verb0


def _classify_run_command(cmd: str) -> Tuple[bool, bool]:
    if not cmd:
        return False, False
    is_read = False
    is_search = False
    for seg in re.split(r"\s*(?:&&|\|\||[;|])\s*", cmd):
        verb = _segment_command_verb(seg)
        if verb in READ_SEARCH_CMDS:
            is_read = True
        if verb in SEARCH_ONLY_CMDS:
            is_search = True
    return is_read, is_search


def _is_read_or_search_call(tc: Dict[str, Any]) -> bool:
    tname = tc.get("name", "")
    if tname in READ_SEARCH_TOOLS:
        return True
    if tname == "run_command":
        return _classify_run_command(str(tc.get("args", {}).get("CommandLine", "")))[0]
    return False


def _is_search_only_call(tc: Dict[str, Any]) -> bool:
    tname = tc.get("name", "")
    if tname in SEARCH_ONLY_TOOLS:
        return True
    if tname == "run_command":
        return _classify_run_command(str(tc.get("args", {}).get("CommandLine", "")))[1]
    return False
