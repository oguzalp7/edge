"""
Edge Brigade: Michelin Station & Deterministic State Machine Engine
Inspired by Lauren Tan's (Poteto) Brigade de Cuisine (pstack)
and Dexter Horthy's 12-Factor Agents (Factor 8: Own Your Control Flow).
"""

import importlib
from typing import Any, Dict, List, Tuple

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "StationRole": (".models", "StationRole"),
    "BrigadeState": (".models", "BrigadeState"),
    "CycleState": (".models", "CycleState"),
    "Ticket": (".models", "Ticket"),
    "BrigadeFSM": (".fsm", "BrigadeFSM"),
    "StationRegistry": (".stations", "StationRegistry"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolves re-exported Brigade symbols on first attribute access."""
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
