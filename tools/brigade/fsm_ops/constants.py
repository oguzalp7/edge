"""FSM constants and monkeypatch-safe facade bridge."""

import sys
from typing import Any

GREEN_HEAT_THRESHOLD: int = 45_000
YELLOW_HEAT_THRESHOLD: int = 75_000
VERIFICATION_TIMEOUT_SECONDS: int = 300


def call_facade(name: str, default: Any) -> Any:
    """Resolves monkeypatchable module attributes from tools.brigade.fsm when loaded."""
    facade = sys.modules.get("tools.brigade.fsm")
    return getattr(facade, name, default) if facade is not None else default
