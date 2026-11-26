"""
Common infrastructure module for Edge Tools (PEP 562 lazy package exports).
"""

import importlib
from typing import Any, Dict, List, Tuple

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "setup_utf8_console": (".console", "setup_utf8_console"),
    "resolve_target_repo_root": (".fs", "resolve_target_repo_root"),
    "atomic_write_text": (".fs", "atomic_write_text"),
    "atomic_write_json": (".fs", "atomic_write_json"),
    "normalize_target_path": (".paths", "normalize_target_path"),
    "to_wsl_path": (".paths", "to_wsl_path"),
    "is_wsl_path": (".paths", "is_wsl_path"),
    "run_command": (".runner", "run_command"),
    "toon_encode": (".toon", "encode"),
    "toon_dumps": (".toon", "dumps"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolves re-exported common helpers on first attribute access."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod_name, attr_name = target
    module = importlib.import_module(mod_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> List[str]:
    return sorted(set(globals()) | set(__all__))
