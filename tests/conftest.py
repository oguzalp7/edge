"""Shared pytest fixtures for hermetic edge test isolation."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_edge_worktree_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Isolate EDGE_HOME to a temp directory and disable live worktree leasing by default."""
    edge_home = tmp_path_factory.mktemp("edge_home")
    monkeypatch.setenv("EDGE_HOME", str(edge_home))
    monkeypatch.setenv("EDGE_WORKTREE_BACKEND", "none")
