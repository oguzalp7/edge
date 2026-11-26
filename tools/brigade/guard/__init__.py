"""Stdlib-only submodules for the Edge Brigade lifecycle guard."""

import importlib
from typing import Any

_EXPORTS = {
    "detect_session_role": ("tools.brigade.guard.role_detection", "detect_session_role"),
    "handle_pre_tool": ("tools.brigade.guard.pre_tool", "handle_pre_tool"),
    "handle_post_tool": ("tools.brigade.guard.lifecycle_handlers", "handle_post_tool"),
    "handle_pre_invocation": ("tools.brigade.guard.lifecycle_handlers", "handle_pre_invocation"),
}


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        mod_name, attr = _EXPORTS[name]
        return getattr(importlib.import_module(mod_name), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
