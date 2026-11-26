"""FSM constants and monkeypatch-safe facade bridge."""

import os
from pathlib import Path
import sys
from typing import Any

from tools.brigade.worktree import is_treehouse_installed as _ORIG_IS_TREEHOUSE_INSTALLED
from tools.brigade.worktree import is_worktree_backend_available

GREEN_HEAT_THRESHOLD: int = 45_000
YELLOW_HEAT_THRESHOLD: int = 75_000
VERIFICATION_TIMEOUT_SECONDS: int = 300


def call_facade(name: str, default: Any) -> Any:
    """Resolves monkeypatchable module attributes from tools.brigade.fsm when loaded."""
    facade = sys.modules.get("tools.brigade.fsm")
    return getattr(facade, name, default) if facade is not None else default


def should_lease_worktree(repo_path: Path) -> bool:
    """Resolve worktree leasing while honoring legacy fsm.is_treehouse_installed mocks and EDGE_WORKTREE_BACKEND."""
    fsm_mod = sys.modules.get("tools.brigade.fsm")
    fsm_treehouse = getattr(fsm_mod, "is_treehouse_installed", None) if fsm_mod else None
    if fsm_treehouse is not None and fsm_treehouse is not _ORIG_IS_TREEHOUSE_INSTALLED:
        return bool(fsm_treehouse())
    backend_pref = os.environ.get("EDGE_WORKTREE_BACKEND", "").strip().lower()
    if backend_pref == "none":
        return False
    return bool(call_facade("is_worktree_backend_available", is_worktree_backend_available)(repo_path))
