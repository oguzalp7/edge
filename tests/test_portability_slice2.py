#!/usr/bin/env python3
"""
RED Contract Tests for Session 1 — Slice 2:
OS-Agnostic rules/AGENTS.md + coding_standards.md & Runtime Hardcode Cleanup
across paths.py, runner.py, backends.py, fsm.py, harvester.py, session_miner.py, and gnhf/shim.py.
"""

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _read_text(rel_path: str) -> str:
    target = REPO_ROOT / rel_path
    assert target.is_file(), f"Missing expected file: {rel_path}"
    return target.read_text(encoding="utf-8")


def _clean_wsl_env(tmp_path: Path) -> Dict[str, str]:
    clean = os.environ.copy()
    for key in ("EDGE_WSL_DISTRO", "WSL_DISTRO_NAME"):
        clean.pop(key, None)
    clean["EDGE_HOME"] = str(tmp_path / "empty_edge_home")
    return clean


# ---------------------------------------------------------------------------
# 1. tools/common/paths.py Portability Contracts
# ---------------------------------------------------------------------------


def test_paths_no_hardcoded_ubuntu_distro_and_empty_default(tmp_path: Path) -> None:
    src = _read_text("tools/common/paths.py")
    assert "Ubuntu-24.04" not in src, "tools/common/paths.py must not hardcode Ubuntu-24.04"

    proc = subprocess.run(
        [sys.executable, "-c", "import json; from tools.common import paths; print(json.dumps(paths.WSL_DISTRO))"],
        cwd=str(REPO_ROOT),
        env=_clean_wsl_env(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(proc.stdout.strip()) == ""


def test_paths_is_wsl_path_and_multi_drive_and_arbitrary_distro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.common import env as env_mod
    from tools.common import paths as paths_mod

    # 1. is_wsl_path(/home/alice/repo) is False on native Linux, True on Windows or WSL
    monkeypatch.setattr(paths_mod.os, "name", "posix")
    monkeypatch.setattr(env_mod, "is_wsl", lambda: False)
    if hasattr(paths_mod, "is_wsl"):
        monkeypatch.setattr(paths_mod, "is_wsl", lambda: False)
    assert paths_mod.is_wsl_path("/home/alice/repo") is False

    monkeypatch.setattr(env_mod, "is_wsl", lambda: True)
    if hasattr(paths_mod, "is_wsl"):
        monkeypatch.setattr(paths_mod, "is_wsl", lambda: True)
    assert paths_mod.is_wsl_path("/home/alice/repo") is True

    from pathlib import PosixPath

    monkeypatch.setattr(paths_mod.os, "name", "nt")
    monkeypatch.setattr(paths_mod, "Path", PosixPath)
    assert paths_mod.is_wsl_path("/home/alice/repo") is True

    # 2. normalize_target_path supports any drive letter /mnt/<d>/... under Windows
    norm_d = str(paths_mod.normalize_target_path("/mnt/d/work/nonexistent_repo")).replace("\\", "/").lower()
    norm_e = str(paths_mod.normalize_target_path("/mnt/e/datasets")).replace("\\", "/").lower()
    assert norm_d == "d:/work/nonexistent_repo"
    assert norm_e == "e:/datasets"

    # 3. normalize_target_path(/home/...) with empty WSL_DISTRO must not inject Ubuntu-24.04 or blank UNC
    monkeypatch.setattr(paths_mod, "WSL_DISTRO", "", raising=False)
    monkeypatch.setattr(env_mod, "get_wsl_distro", lambda: "")
    no_distro_home = str(paths_mod.normalize_target_path("/home/alice/nonexistent_repo")).replace("\\", "/")
    assert "Ubuntu-24.04" not in no_distro_home
    assert "//wsl.localhost//" not in no_distro_home

    # 4. to_wsl_path strips any UNC distro prefix (case-insensitive) and translates any Windows drive
    assert paths_mod.to_wsl_path(r"\\wsl.localhost\Debian\home\alice\repo") == "/home/alice/repo"
    assert paths_mod.to_wsl_path(r"\\WSL.LOCALHOST\Ubuntu-22.04\home\alice\repo") == "/home/alice/repo"
    assert paths_mod.to_wsl_path(r"\\wsl$\Fedora\home\alice\repo") == "/home/alice/repo"
    assert paths_mod.to_wsl_path(r"E:\Projects\edge") == "/mnt/e/Projects/edge"


# ---------------------------------------------------------------------------
# 2. tools/common/runner.py & tools/tracker/backends.py WSL Dispatch Matrix
# ---------------------------------------------------------------------------


def test_runner_and_backends_no_hardcoded_distro_and_native_linux_passthrough(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner_src = _read_text("tools/common/runner.py")
    backends_src = _read_text("tools/tracker/backends.py")
    assert "Ubuntu-24.04" not in runner_src
    assert "Ubuntu-24.04" not in backends_src

    from tools.common import env as env_mod
    from tools.common import paths as paths_mod
    from tools.common import runner
    from tools.tracker import backends

    # Native Linux: /home/alice/repo MUST NOT dispatch through wsl
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(env_mod, "is_wsl", lambda: False)
    if hasattr(paths_mod, "is_wsl"):
        monkeypatch.setattr(paths_mod, "is_wsl", lambda: False)

    assert backends.needs_wsl_dispatch("/home/alice/repo") is False

    # Inside WSL: already in Linux, MUST NOT dispatch through wsl
    monkeypatch.setattr(env_mod, "is_wsl", lambda: True)
    if hasattr(paths_mod, "is_wsl"):
        monkeypatch.setattr(paths_mod, "is_wsl", lambda: True)
    assert backends.needs_wsl_dispatch("/home/alice/repo") is False

    # Verify runner.run_command executes directly without wsl on native Linux
    captured_runner: List[Any] = []

    def fake_sub_run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_runner.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(env_mod, "is_wsl", lambda: False)
    if hasattr(paths_mod, "is_wsl"):
        monkeypatch.setattr(paths_mod, "is_wsl", lambda: False)
    monkeypatch.setattr(runner.subprocess, "run", fake_sub_run)

    rc, out, _ = runner.run_command(["echo", "hi"], cwd=str(tmp_path))
    assert (rc, out) == (0, "ok")
    assert captured_runner[-1][0] == ["echo", "hi"]

    rc_home, out_home, _ = runner.run_command(["echo", "hi"], cwd="/home/alice/repo")
    assert (rc_home, out_home) == (0, "ok")
    assert captured_runner[-1][0] == ["echo", "hi"]


def test_runner_and_backends_omit_dash_d_when_wsl_distro_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tools.common import env as env_mod
    from tools.common import paths as paths_mod
    from tools.common import runner
    from tools.tracker import backends

    monkeypatch.delenv("EDGE_WSL_DISTRO", raising=False)
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setenv("EDGE_HOME", str(tmp_path / "no_machine_cfg"))

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(paths_mod, "WSL_DISTRO", "", raising=False)
    monkeypatch.setattr(runner, "WSL_DISTRO", "", raising=False)
    monkeypatch.setattr(backends, "WSL_DISTRO", "", raising=False)
    monkeypatch.setattr(env_mod, "get_wsl_distro", lambda: "")
    for mod in (runner, backends, paths_mod):
        if hasattr(mod, "get_wsl_distro"):
            monkeypatch.setattr(mod, "get_wsl_distro", lambda: "")

    # Keep PosixPath instantiation happy under mocked os.name="nt"
    from pathlib import PosixPath

    monkeypatch.setattr(paths_mod, "Path", PosixPath)
    monkeypatch.setattr(runner, "Path", PosixPath)
    monkeypatch.setattr(backends, "Path", PosixPath)

    captured: List[List[str]] = []

    def fake_sub_run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if isinstance(cmd, list):
            captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_sub_run)
    monkeypatch.setattr(backends.subprocess, "run", fake_sub_run)

    # 1. Empty distro: ZERO "-d" flag in runner & backends
    rc, _, _ = runner.run_command(["pytest", "-q"], cwd="/home/alice/repo")
    assert rc == 0
    assert captured[-1][:3] == ["wsl", "bash", "-c"]
    assert "-d" not in captured[-1][:3]

    assert backends.binary_exists("gh-axi", cwd="/home/alice/repo") is True
    assert captured[-1] == ["wsl", "which", "gh-axi"]

    rc_b, _, _ = backends.run_tracker_cmd(["gh", "issue", "list"], cwd="/home/alice/repo")
    assert rc_b == 0
    assert captured[-1][:3] == ["wsl", "bash", "-c"]
    assert "-d" not in captured[-1][:3]

    # 2. Explicit distro: includes ["-d", "Debian"]
    monkeypatch.setenv("EDGE_WSL_DISTRO", "Debian")
    monkeypatch.setattr(paths_mod, "WSL_DISTRO", "Debian", raising=False)
    monkeypatch.setattr(runner, "WSL_DISTRO", "Debian", raising=False)
    monkeypatch.setattr(backends, "WSL_DISTRO", "Debian", raising=False)
    monkeypatch.setattr(env_mod, "get_wsl_distro", lambda: "Debian")
    for mod in (runner, backends, paths_mod):
        if hasattr(mod, "get_wsl_distro"):
            monkeypatch.setattr(mod, "get_wsl_distro", lambda: "Debian")

    assert backends.binary_exists("gh", cwd="/home/alice/repo") is True
    assert captured[-1] == ["wsl", "-d", "Debian", "which", "gh"]

    rc_d, _, _ = runner.run_command(["pytest", "-q"], cwd="/home/alice/repo")
    assert rc_d == 0
    assert captured[-1][:5] == ["wsl", "-d", "Debian", "bash", "-c"]


# ---------------------------------------------------------------------------
# 3. tools/brigade/fsm.py (_run_radar_rescan) Portability Contract
# ---------------------------------------------------------------------------


def test_fsm_run_radar_rescan_no_hardcodes_and_cross_os_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for fsm_rel in ("tools/brigade/fsm.py", "tools/brigade/fsm_ops/staging_archive.py"):
        fsm_src = _read_text(fsm_rel)
        assert "oguz" not in fsm_src.lower(), f"{fsm_rel} must not contain hardcoded user 'oguz'"
        assert "Ubuntu-24.04" not in fsm_src, f"{fsm_rel} must not hardcode Ubuntu-24.04"

    from tools.brigade import fsm as fsm_mod
    from tools.common import env as env_mod
    from tools.common import paths as paths_mod

    captured: List[Tuple[List[str], Any]] = []

    def fake_run_command(cmd: List[str], cwd: Any = None, **kwargs: Any) -> Tuple[int, str, str]:
        captured.append((cmd, cwd))
        return 0, "", ""

    monkeypatch.setattr(fsm_mod, "run_command", fake_run_command)

    instance = object.__new__(fsm_mod.BrigadeFSM)

    # Case A: Native Linux (/home/alice/repo) uses sys.executable directly, NOT WSL python3
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(env_mod, "is_wsl", lambda: False)
    if hasattr(paths_mod, "is_wsl"):
        monkeypatch.setattr(paths_mod, "is_wsl", lambda: False)

    instance.target_repo = Path("/home/alice/repo")
    instance._run_radar_rescan()
    cmd_linux, cwd_linux = captured[-1]
    assert cmd_linux[0] == sys.executable
    assert Path(cmd_linux[1]).name == "cli.py"
    assert cmd_linux[2:] == ["scan", "/home/alice/repo"]
    assert cwd_linux == Path("/home/alice/repo")

    from pathlib import PosixPath

    # Case B: Native Windows (D:\work\repo) uses sys.executable directly
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(fsm_mod, "Path", PosixPath)
    monkeypatch.setattr(paths_mod, "Path", PosixPath)
    instance.target_repo = PosixPath("D:/work/repo")
    instance._run_radar_rescan()
    cmd_win, _ = captured[-1]
    assert cmd_win[0] == sys.executable
    assert cmd_win[2] == "scan"

    # Case C: Windows targeting WSL UNC (\\wsl.localhost\Debian\home\alice\repo) translates via to_wsl_path
    unc_target = PosixPath(r"\\wsl.localhost\Debian\home\alice\repo")
    instance.target_repo = unc_target
    instance._run_radar_rescan()
    cmd_wsl, _ = captured[-1]
    assert cmd_wsl[0] == "python3"
    assert cmd_wsl[1].endswith("/tools/radar/cli.py")
    assert not cmd_wsl[1].startswith("C:")
    assert cmd_wsl[2:] == ["scan", "/home/alice/repo"]


# ---------------------------------------------------------------------------
# 4. distill/harvester.py, distill/session_miner.py, gnhf/shim.py Cleanup
# ---------------------------------------------------------------------------


def test_distill_and_gnhf_no_oguz_hardcodes_and_dynamic_discovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for rel in (
        "tools/distill/harvester.py",
        "tools/distill/harvester_discovery.py",
        "tools/distill/session_miner.py",
        "tools/distill/session_paths.py",
        "tools/gnhf/shim.py",
    ):
        src = _read_text(rel)
        assert "oguz" not in src.lower(), f"{rel} must not contain hardcoded 'oguz' path"

    # 1. harvester_discovery.default_brain_roots uses env.get_brain_dir() / GEMINI_BRAIN_ROOT
    from tools.distill.harvester_discovery import default_brain_roots

    fake_home = tmp_path / "home"
    fake_agy = tmp_path / "agy_shared"
    env_brain = tmp_path / "explicit_brain"
    (fake_home / ".gemini" / "antigravity" / "brain").mkdir(parents=True)
    (fake_agy / "brain").mkdir(parents=True)
    env_brain.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setenv("EDGE_ANTIGRAVITY_DIR", str(fake_agy))
    monkeypatch.setenv("GEMINI_BRAIN_ROOT", str(env_brain))

    roots_env = default_brain_roots()
    assert env_brain in roots_env

    monkeypatch.delenv("GEMINI_BRAIN_ROOT", raising=False)
    roots_shared = default_brain_roots()
    assert (fake_agy / "brain") in roots_shared or (fake_home / ".gemini" / "antigravity" / "brain") in roots_shared

    # 2. session_miner discovers brain roots via get_brain_dir() / Path.home() without oguz hardcodes
    from tools.distill import session_miner

    importlib.reload(session_miner)
    assert all("oguz" not in str(p).lower() for p in session_miner.DEFAULT_BRAIN_ROOTS)
    resolved_miner_roots = session_miner.SessionMiner._resolve_default_roots()
    assert any(p.resolve() == (fake_agy / "brain").resolve() for p in resolved_miner_roots) or any(
        p.resolve() == (fake_home / ".gemini" / "antigravity" / "brain").resolve() for p in resolved_miner_roots
    )

    # 3. tools/gnhf/shim.py resolves ~/.local/bin/agy dynamically via Path.home()
    from tools.gnhf import shim

    importlib.reload(shim)
    assert all("oguz" not in loc.lower() for loc in shim._KNOWN_AGY_LOCATIONS)
    local_agy = fake_home / ".local" / "bin" / "agy"
    local_agy.parent.mkdir(parents=True, exist_ok=True)
    local_agy.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    importlib.reload(shim)
    assert shim._find_real_agy() == str(local_agy)


# ---------------------------------------------------------------------------
# 5. rules/AGENTS.md & coding_standards.md Portability + Session 2 Token Parity
# ---------------------------------------------------------------------------


def test_rules_agents_md_and_coding_standards_portable_and_preserve_tokens() -> None:
    agents_text = _read_text("rules/AGENTS.md")
    standards_text = _read_text("coding_standards.md")

    for rel, content in (("rules/AGENTS.md", agents_text), ("coding_standards.md", standards_text)):
        low = content.lower()
        assert "oguz" not in low, f"{rel} must not contain user-specific 'oguz' paths"
        assert "file:///" not in low, f"{rel} must not contain local file:/// links"
        assert "Ubuntu-24.04" not in content, f"{rel} must not hardcode Ubuntu-24.04"

    # Rule 0 must be Cross-OS Runtime Doctrine (NOT mandatory WSL2-only)
    agents_low = agents_text.lower()
    assert "cross-os" in agents_low or ("windows" in agents_low and "macos" in agents_low and "linux" in agents_low), (
        "rules/AGENTS.md Rule 0 must describe Cross-OS Runtime Doctrine (windows/wsl/macos/linux)"
    )
    assert "machine.json" in agents_text, "rules/AGENTS.md Rule 0 should reference ~/.edge/machine.json"
    assert "istisnasiz" not in agents_low.replace("\u0307", "").replace("ı", "i")

    # Rule 0.1 must use portable workspace placeholders
    assert "<repo-root>" in agents_text and "<worktree-path>" in agents_text

    # Rule 3 playbook links must be relative and resolve to real files in repo
    expected_playbooks = (
        "rules/context-system.md",
        "rules/refactor.md",
        "rules/feature.md",
        "rules/playbooks/pause-safely.md",
        "rules/playbooks/session-pickup.md",
        "rules/playbooks/swarm-vs-brigade.md",
    )
    for rel_link in expected_playbooks:
        assert rel_link in agents_text, f"rules/AGENTS.md missing portable link {rel_link}"
        assert (REPO_ROOT / rel_link).is_file(), f"Target playbook does not exist: {rel_link}"

    # Preserved Session 2 tokens (must stay aligned with tests/test_tracker_docs_ontology.py)
    for required_tok in (
        "tools/tracker/",
        ".edge/issues/",
        "tasks-axi",
        "frontier-axi",
        ".edge/stations/",
        "swarm-vs-brigade.md",
        "gh-axi",
        "EDGE_TRACKER=local",
    ):
        assert required_tok in agents_text, f"rules/AGENTS.md dropped Session 2 token: {required_tok}"
    assert "soft-deprecated" in agents_low or "soft deprecated" in agents_low

    # coding_standards.md Section 2 must describe Cross-OS Execution & Path Normalization
    standards_low = standards_text.lower()
    assert "wsl2-first" not in standards_low, "coding_standards.md Section 2 must no longer say WSL2-First"
    assert "cross-os" in standards_low
    assert "tools.common.env" in standards_text and "tools.common.paths" in standards_text
