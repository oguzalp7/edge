"""Companion unit tests for tools/common/env.py configuration and path resolution."""

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.common import env  # noqa: E402


def test_machine_config_roundtrip_and_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    edge_home = tmp_path / "edge_home"
    agy_dir = tmp_path / "agy_dir"
    monkeypatch.setenv("EDGE_HOME", str(edge_home))
    monkeypatch.setenv("EDGE_ANTIGRAVITY_DIR", str(agy_dir))

    cfg = env.MachineConfig(os_mode="linux", hooks_mode="session", install_profile="core", wsl_distro="")
    saved = env.save_machine_config(cfg)
    assert saved == edge_home / "machine.json"
    loaded = env.load_machine_config(saved)
    assert loaded.os_mode == "linux"
    assert loaded.hooks_mode == "session"

    assert env.get_antigravity_data_dir() == agy_dir
    assert env.get_brain_dir() == agy_dir / "brain"
    assert env.get_active_stations_path() == agy_dir / "edge_active_stations.json"
    assert env.get_active_sessions_dir() == agy_dir / "edge_active_sessions"


def test_resolve_host_path_empty_and_wsl_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    assert env.resolve_host_path("") == Path("")
    monkeypatch.setattr(env, "detect_os_mode", lambda: "wsl")
    assert env.resolve_host_path(r"D:\repo\file.py").as_posix() == "/mnt/d/repo/file.py"
