"""Lazy symbol forwarding and CLI I/O helpers for tools.brigade.cli_ops."""

import importlib
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional


def resolve_symbol(attr_name: str, module_path: str, symbol_name: Optional[str] = None) -> Any:
    """Resolve symbol honoring active unittest.mock patches on tools.brigade.cli."""
    facade = sys.modules.get("tools.brigade.cli")
    if facade is not None and attr_name in facade.__dict__:
        return facade.__dict__[attr_name]
    mod = importlib.import_module(module_path)
    return getattr(mod, symbol_name or attr_name)


def parse_param_pairs(raw_params: Optional[List[str]]) -> Dict[str, str]:
    """Parse key=value CLI argument list into a dictionary."""
    parsed: Dict[str, str] = {}
    for item in raw_params or []:
        if "=" in str(item):
            key, val = str(item).split("=", 1)
            if key.strip():
                parsed[key.strip()] = val.strip()
    return parsed


def resolve_cli_out_path(repo_path: Path, out_arg: Optional[str]) -> Optional[Path]:
    """Resolve optional --out file path relative to repo_path."""
    if not out_arg:
        return None
    if Path(out_arg).is_absolute():
        return resolve_symbol("normalize_target_path", "tools.common")(out_arg)
    return repo_path / out_arg


def write_atomic_text(out_path: Path, content: str) -> None:
    """Atomically write UTF-8 text via sibling .tmp rename."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, out_path)
