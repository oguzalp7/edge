#!/usr/bin/env python3
"""
RED Unit & Contract Tests for Session 1 Slice 1:
Cross-OS Environment (tools/common/env.py), Lazy Package Init,
Session-Gated Fail-Open Dispatcher (hooks/dispatch.py),
Polyglot Launcher (hooks/dispatch.cmd), hooks.json, and .gitattributes.
"""

import ast
import glob
import importlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Hermetic Helpers & Fixtures
# ---------------------------------------------------------------------------


def _load_env_module():
    return importlib.import_module("tools.common.env")


def _load_dispatch_module():
    dispatch_path = REPO_ROOT / "hooks" / "dispatch.py"
    assert dispatch_path.is_file(), f"Expected hooks/dispatch.py at {dispatch_path}"
    spec = importlib.util.spec_from_file_location("edge_hooks_dispatch_under_test", dispatch_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_guard_module():
    return importlib.import_module("tools.brigade.orchestrator_guard")


def _clear_edge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "PLUGIN_ROOT",
        "EDGE_PLUGIN_ROOT",
        "PLUGIN_DATA",
        "EDGE_HOME",
        "EDGE_ANTIGRAVITY_DIR",
        "GEMINI_BRAIN_ROOT",
        "EDGE_ACTIVE_STATIONS_FILE",
        "EDGE_ACTIVE_SESSIONS_DIR",
        "EDGE_WSL_DISTRO",
        "EDGE_HOOKS",
        "EDGE_AFK",
        "EDGE_AFK_MODE",
        "NO_MISTAKES",
        "NO_MISTAKES_RUN",
        "NO_MISTAKES_STEP",
        "WSL_DISTRO_NAME",
        "USERPROFILE",
    ):
        monkeypatch.delenv(key, raising=False)


def _isolate_runtime_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Dict[str, Path]:
    _clear_edge_env(monkeypatch)
    edge_home = tmp_path / "edge_home"
    antigravity_dir = tmp_path / "antigravity"
    stations_file = antigravity_dir / "edge_active_stations.json"
    sessions_dir = antigravity_dir / "edge_active_sessions"
    plugin_data = tmp_path / "plugin_data"

    edge_home.mkdir(parents=True, exist_ok=True)
    antigravity_dir.mkdir(parents=True, exist_ok=True)
    plugin_data.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PLUGIN_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("EDGE_HOME", str(edge_home))
    monkeypatch.setenv("EDGE_ANTIGRAVITY_DIR", str(antigravity_dir))
    monkeypatch.setenv("EDGE_ACTIVE_STATIONS_FILE", str(stations_file))
    monkeypatch.setenv("EDGE_ACTIVE_SESSIONS_DIR", str(sessions_dir))

    guard = sys.modules.get("tools.brigade.orchestrator_guard")
    if guard is not None:
        monkeypatch.setattr(guard, "ACTIVE_STATIONS_FILE", stations_file, raising=False)

    return {
        "edge_home": edge_home,
        "antigravity_dir": antigravity_dir,
        "stations_file": stations_file,
        "sessions_dir": sessions_dir,
        "plugin_data": plugin_data,
    }


def _write_transcript(path: Path, steps: Iterable[Dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for step in steps:
            fh.write(json.dumps(step) + "\n")
    return path


def _run_dispatch_in_process(
    dispatch_mod: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    monkeypatch.setattr(sys, "argv", [str(REPO_ROOT / "hooks" / "dispatch.py"), mode])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    capsys.readouterr()
    try:
        dispatch_mod.main()
    except SystemExit as exc:
        assert exc.code in (None, 0), f"dispatch.main exited with non-zero code {exc.code}"
    captured = capsys.readouterr()
    assert captured.out.strip(), f"Expected JSON output on stdout, got stderr={captured.err!r}"
    return json.loads(captured.out.strip())


def _make_subprocess_env(paths: Dict[str, Path], extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    clean_env = os.environ.copy()
    for key in (
        "EDGE_HOOKS",
        "EDGE_AFK",
        "EDGE_AFK_MODE",
        "EDGE_WSL_DISTRO",
        "NO_MISTAKES",
        "NO_MISTAKES_RUN",
        "NO_MISTAKES_STEP",
        "WSL_DISTRO_NAME",
        "USERPROFILE",
    ):
        clean_env.pop(key, None)
    clean_env.update(
        {
            "PLUGIN_ROOT": str(REPO_ROOT),
            "PLUGIN_DATA": str(paths["plugin_data"]),
            "EDGE_HOME": str(paths["edge_home"]),
            "EDGE_ANTIGRAVITY_DIR": str(paths["antigravity_dir"]),
            "EDGE_ACTIVE_STATIONS_FILE": str(paths["stations_file"]),
            "EDGE_ACTIVE_SESSIONS_DIR": str(paths["sessions_dir"]),
        }
    )
    if extra:
        clean_env.update(extra)
    return clean_env


def _patch_proc_version(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    import builtins

    real_read_text = Path.read_text
    real_open = builtins.open

    def fake_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if str(self) == "/proc/version":
            return content
        return real_read_text(self, *args, **kwargs)

    def fake_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if str(file) == "/proc/version":
            return io.StringIO(content)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    monkeypatch.setattr(builtins, "open", fake_open)


# ---------------------------------------------------------------------------
# Group A: tools/common/env.py — OS Detection, MachineConfig, Split-Brain, Paths
# ---------------------------------------------------------------------------


def test_machine_config_defaults_serialization_and_atomic_persistence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    env = _load_env_module()

    default_cfg = env.MachineConfig()
    assert default_cfg.schema_version == "1.0"
    assert default_cfg.os_mode == ""
    assert default_cfg.hooks_mode == "session"
    assert default_cfg.install_profile == "core"
    assert default_cfg.wsl_distro == ""
    assert default_cfg.persona_tone == "technical"

    cfg_path = env.get_machine_config_path()
    assert cfg_path == paths["edge_home"] / "machine.json"

    custom = env.MachineConfig(
        os_mode="linux",
        hooks_mode="strict",
        install_profile="full",
        wsl_distro="Arch",
        persona_tone="technical",
        updated_at="2026-11-26T00:00:00Z",
    )
    as_dict = custom.to_dict()
    assert as_dict["hooks_mode"] == "strict"
    assert as_dict["install_profile"] == "full"

    saved_path = env.save_machine_config(custom)
    assert saved_path == cfg_path
    assert cfg_path.is_file()
    leftovers = [p.name for p in cfg_path.parent.iterdir() if ".tmp" in p.name]
    assert leftovers == [], f"Atomic write left temporary files behind: {leftovers}"

    loaded = env.load_machine_config()
    assert loaded.os_mode == "linux"
    assert loaded.hooks_mode == "strict"
    assert loaded.install_profile == "full"
    assert loaded.wsl_distro == "Arch"

    partial = env.MachineConfig.from_dict({"hooks_mode": "off", "unknown_future_field": 123})
    assert partial.hooks_mode == "off"
    assert partial.install_profile == "core"


def test_load_machine_config_corrupt_and_non_dict_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_runtime_paths(monkeypatch, tmp_path)
    env = _load_env_module()

    missing_path = tmp_path / "does_not_exist.json"
    cfg_missing = env.load_machine_config(missing_path)
    assert cfg_missing.hooks_mode == "session"
    assert cfg_missing.install_profile == "core"

    corrupt_path = tmp_path / "corrupt_machine.json"
    corrupt_path.write_text("{not-valid-json", encoding="utf-8")
    cfg_corrupt = env.load_machine_config(corrupt_path)
    assert cfg_corrupt.hooks_mode == "session"
    assert cfg_corrupt.schema_version == "1.0"

    list_path = tmp_path / "list_machine.json"
    list_path.write_text('["unexpected", "array"]', encoding="utf-8")
    cfg_list = env.load_machine_config(list_path)
    assert cfg_list.hooks_mode == "session"
    assert cfg_list.wsl_distro == ""


def test_is_wsl_and_detect_os_mode_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_runtime_paths(monkeypatch, tmp_path)
    env = _load_env_module()

    # 1. Windows host (even if WSL_DISTRO_NAME happens to exist in env)
    monkeypatch.setattr(env.os, "name", "nt")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert env.is_wsl() is False
    assert env.detect_os_mode() == "windows"

    # 2. macOS
    monkeypatch.setattr(env.os, "name", "posix")
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setattr(env.sys, "platform", "darwin")
    _patch_proc_version(monkeypatch, "Darwin Kernel Version 24.0.0")
    assert env.is_wsl() is False
    assert env.detect_os_mode() == "macos"

    # 3. WSL via WSL_DISTRO_NAME
    monkeypatch.setattr(env.sys, "platform", "linux")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Debian")
    _patch_proc_version(monkeypatch, "Linux version 6.6.0-generic")
    assert env.is_wsl() is True
    assert env.detect_os_mode() == "wsl"

    # 4. WSL via /proc/version when WSL_DISTRO_NAME is unset
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    _patch_proc_version(monkeypatch, "Linux version 5.15.167.4-microsoft-standard-WSL2")
    assert env.is_wsl() is True
    assert env.detect_os_mode() == "wsl"

    # 5. Native Linux (not WSL)
    _patch_proc_version(monkeypatch, "Linux version 6.8.0-45-generic (buildd@ubuntu)")
    assert env.is_wsl() is False
    assert env.detect_os_mode() == "linux"


def test_get_plugin_root_and_edge_home_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_edge_env(monkeypatch)
    env = _load_env_module()

    p_root = tmp_path / "plugin_root_a"
    e_root = tmp_path / "plugin_root_b"
    p_root.mkdir()
    e_root.mkdir()

    monkeypatch.setenv("PLUGIN_ROOT", str(p_root))
    monkeypatch.setenv("EDGE_PLUGIN_ROOT", str(e_root))
    assert env.get_plugin_root() == p_root

    monkeypatch.delenv("PLUGIN_ROOT", raising=False)
    assert env.get_plugin_root() == e_root

    monkeypatch.delenv("EDGE_PLUGIN_ROOT", raising=False)
    assert env.get_plugin_root() == REPO_ROOT

    custom_home = tmp_path / "custom_edge_home"
    monkeypatch.setenv("EDGE_HOME", str(custom_home))
    assert env.get_edge_home() == custom_home

    monkeypatch.delenv("EDGE_HOME", raising=False)
    assert env.get_edge_home() == Path.home() / ".edge"


def test_get_wsl_distro_precedence_and_empty_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_runtime_paths(monkeypatch, tmp_path)
    env = _load_env_module()

    # Empty-string default: ZERO hardcoded "Ubuntu-24.04"
    assert env.get_wsl_distro() == ""

    # Fallback 3: WSL_DISTRO_NAME
    monkeypatch.setenv("WSL_DISTRO_NAME", "FedoraLinux-40")
    assert env.get_wsl_distro() == "FedoraLinux-40"

    # Fallback 2: machine.json wsl_distro overrides WSL_DISTRO_NAME
    env.save_machine_config(env.MachineConfig(wsl_distro="Debian"))
    assert env.get_wsl_distro() == "Debian"

    # Fallback 1: EDGE_WSL_DISTRO overrides machine.json
    monkeypatch.setenv("EDGE_WSL_DISTRO", "NixOS")
    assert env.get_wsl_distro() == "NixOS"


def test_cache_python_executable_writes_plugin_data_and_edge_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    env = _load_env_module()

    fake_py = r"C:\Python312\python.exe"
    env.cache_python_executable(fake_py)

    pd_cache = paths["plugin_data"] / "python_exe.txt"
    eh_cache = paths["edge_home"] / "python_exe.txt"
    assert pd_cache.read_text(encoding="utf-8").strip() == fake_py
    assert eh_cache.read_text(encoding="utf-8").strip() == fake_py

    # Default exe_path uses sys.executable and works when PLUGIN_DATA is unset
    monkeypatch.delenv("PLUGIN_DATA", raising=False)
    env.cache_python_executable()
    assert eh_cache.read_text(encoding="utf-8").strip() == sys.executable


def test_wsl_split_brain_prevention_prefers_windows_host_antigravity_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_edge_env(monkeypatch)
    env = _load_env_module()

    fake_home = tmp_path / "wsl_home"
    wsl_agy = fake_home / ".gemini" / "antigravity"
    wsl_agy.mkdir(parents=True)
    # Decoy stations file in WSL home must lose to Windows host /mnt/<d>/Users/*
    (wsl_agy / "edge_active_stations.json").write_text("{}", encoding="utf-8")

    sim_mnt = tmp_path / "mnt"
    (sim_mnt / "c" / "Users" / "Public" / ".gemini" / "antigravity").mkdir(parents=True)
    (sim_mnt / "c" / "Users" / "Default" / ".gemini" / "antigravity").mkdir(parents=True)
    (sim_mnt / "c" / "Users" / "All Users" / ".gemini" / "antigravity").mkdir(parents=True)
    win_bob = sim_mnt / "d" / "Users" / "bob" / ".gemini" / "antigravity"
    win_bob.mkdir(parents=True)
    win_alice = sim_mnt / "d" / "Users" / "alice" / ".gemini" / "antigravity"
    (win_alice / "brain").mkdir(parents=True)
    (win_alice / "edge_active_stations.json").write_text("{}", encoding="utf-8")

    RealPath = type(Path())

    class FakePath(RealPath):  # type: ignore[misc, valid-type]
        @staticmethod
        def home() -> Path:
            return fake_home

        def __new__(cls, *args: Any, **kwargs: Any) -> Path:
            p = RealPath(*args, **kwargs)
            s = p.as_posix()
            if s == "/mnt" or s.startswith("/mnt/"):
                return RealPath(tmp_path, s.lstrip("/"))
            return p

    real_glob = glob.glob

    def fake_glob(pattern: str, *args: Any, **kwargs: Any) -> Any:
        if pattern.startswith("/mnt/"):
            pattern = str(tmp_path / pattern.lstrip("/"))
        return real_glob(pattern, *args, **kwargs)

    monkeypatch.setattr(env, "Path", FakePath, raising=False)
    monkeypatch.setattr(glob, "glob", fake_glob)
    monkeypatch.setattr(env, "is_wsl", lambda: True)
    monkeypatch.setattr(env, "detect_os_mode", lambda: "wsl")

    # Case 1: USERPROFILE env set (via WSLENV) selects matching Windows user dir
    monkeypatch.setenv("USERPROFILE", r"D:\Users\bob")
    resolved_via_userprofile = env.get_antigravity_data_dir()
    assert resolved_via_userprofile == win_bob
    assert resolved_via_userprofile != wsl_agy

    # Case 2: USERPROFILE unset -> scans /mnt/[a-z]/Users/*, excludes Public/Default/All Users, prefers brain/stations
    monkeypatch.delenv("USERPROFILE", raising=False)
    resolved_via_scan = env.get_antigravity_data_dir()
    assert resolved_via_scan == win_alice
    assert resolved_via_scan != wsl_agy

    # Case 3: No Windows /mnt/*/Users/* candidates exist -> falls back to WSL home
    shutil.rmtree(sim_mnt)
    resolved_fallback = env.get_antigravity_data_dir()
    assert resolved_fallback == wsl_agy

    # Case 4: Non-WSL mode uses Path.home() / ".gemini" / "antigravity"
    monkeypatch.setattr(env, "is_wsl", lambda: False)
    monkeypatch.setattr(env, "detect_os_mode", lambda: "linux")
    assert env.get_antigravity_data_dir() == wsl_agy

    # Case 5: EDGE_ANTIGRAVITY_DIR overrides everything
    override_dir = tmp_path / "explicit_agy"
    monkeypatch.setenv("EDGE_ANTIGRAVITY_DIR", str(override_dir))
    assert env.get_antigravity_data_dir() == override_dir


def test_active_sessions_dir_colocated_with_active_stations_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_edge_env(monkeypatch)
    env = _load_env_module()

    shared_agy = tmp_path / "shared_antigravity"
    shared_agy.mkdir(parents=True)
    monkeypatch.setenv("EDGE_ANTIGRAVITY_DIR", str(shared_agy))

    stations_path = env.get_active_stations_path()
    sessions_dir = env.get_active_sessions_dir()
    brain_dir = env.get_brain_dir()

    assert stations_path == shared_agy / "edge_active_stations.json"
    assert sessions_dir == shared_agy / "edge_active_sessions"
    assert brain_dir == shared_agy / "brain"
    assert sessions_dir.parent == stations_path.parent

    # Env overrides
    custom_stations = tmp_path / "custom_stations.json"
    custom_sessions = tmp_path / "custom_sessions"
    custom_brain = tmp_path / "custom_brain"
    monkeypatch.setenv("EDGE_ACTIVE_STATIONS_FILE", str(custom_stations))
    monkeypatch.setenv("EDGE_ACTIVE_SESSIONS_DIR", str(custom_sessions))
    monkeypatch.setenv("GEMINI_BRAIN_ROOT", str(custom_brain))

    assert env.get_active_stations_path() == custom_stations
    assert env.get_active_sessions_dir() == custom_sessions
    assert env.get_brain_dir() == custom_brain


def test_resolve_host_path_across_all_os_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_runtime_paths(monkeypatch, tmp_path)
    env = _load_env_module()

    # Windows mode
    monkeypatch.setattr(env, "detect_os_mode", lambda: "windows")
    monkeypatch.setenv("EDGE_WSL_DISTRO", "Ubuntu-24.04")
    win_drive = str(env.resolve_host_path("/mnt/d/work/repo/file.py")).replace("\\", "/")
    assert re.fullmatch(r"[Dd]:/work/repo/file\.py", win_drive), f"Unexpected drive mapping: {win_drive}"

    win_unc = str(env.resolve_host_path("/home/alice/repo")).replace("\\", "/")
    assert win_unc in (
        "//wsl.localhost/Ubuntu-24.04/home/alice/repo",
        "//wsl$/Ubuntu-24.04/home/alice/repo",
    ), f"Unexpected UNC mapping: {win_unc}"

    # When wsl_distro is empty, Windows mode must not inject a hardcoded distro
    monkeypatch.delenv("EDGE_WSL_DISTRO", raising=False)
    win_no_distro = str(env.resolve_host_path("/home/alice/repo")).replace("\\", "/")
    assert "Ubuntu-24.04" not in win_no_distro

    win_native = str(env.resolve_host_path(r"C:\Users\alice\proj")).replace("\\", "/")
    assert win_native == "C:/Users/alice/proj" or win_native == r"C:\Users\alice\proj".replace("\\", "/")

    # WSL mode
    monkeypatch.setattr(env, "detect_os_mode", lambda: "wsl")
    assert env.resolve_host_path(r"C:\Users\alice\transcript.jsonl").as_posix() == "/mnt/c/Users/alice/transcript.jsonl"
    assert env.resolve_host_path("D:/Projects/edge").as_posix() == "/mnt/d/Projects/edge"
    assert env.resolve_host_path(r"\\wsl.localhost\Ubuntu-24.04\home\alice\repo").as_posix() == "/home/alice/repo"
    assert env.resolve_host_path(r"\\wsl$\Debian\home\alice\repo").as_posix() == "/home/alice/repo"
    assert env.resolve_host_path("/home/alice/repo").as_posix() == "/home/alice/repo"

    # macOS & native Linux keep paths unchanged
    for native_mode, sample in (("macos", "/Users/alice/repo"), ("linux", "/home/alice/repo")):
        monkeypatch.setattr(env, "detect_os_mode", lambda m=native_mode: m)
        assert env.resolve_host_path(sample).as_posix() == sample


# ---------------------------------------------------------------------------
# Group B: Lazy / Stdlib-Only Import & INV-ORCH-HOOK-LATENCY
# ---------------------------------------------------------------------------


def _collect_ast_imports(tree: ast.AST, top_level_only: bool = False) -> Set[str]:
    imported: Set[str] = set()
    nodes: Iterable[ast.AST] = tree.body if (top_level_only and isinstance(tree, ast.Module)) else ast.walk(tree)
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                imported.add(f"<relative:{'.' * node.level}{node.module or ''}>")
            elif node.module:
                imported.add(node.module)
    return imported


def _collect_non_docstring_string_literals(tree: ast.AST) -> Iterable[str]:
    docstring_nodes: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstring_nodes.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstring_nodes:
            yield node.value


def test_env_and_dispatch_ast_stdlib_only_and_no_forbidden_literals() -> None:
    env_path = REPO_ROOT / "tools" / "common" / "env.py"
    dispatch_path = REPO_ROOT / "hooks" / "dispatch.py"
    assert env_path.is_file(), f"Missing {env_path}"
    assert dispatch_path.is_file(), f"Missing {dispatch_path}"

    stdlib_names = sys.stdlib_module_names
    forbidden_prefixes = (
        "tools.tracker",
        "tools.brigade.tasks_bridge",
        "tools.brigade.ship_tracker",
        "tools.common.runner",
        "tools.common.fs",
        "tools.common.toon",
        "yaml",
    )
    forbidden_literals = ("tools.tracker", "tasks_bridge", "ship_tracker", "yaml", "gh-axi")

    # 1. tools/common/env.py: 100% stdlib-only, ZERO tools.common.* or relative imports
    env_src = env_path.read_text(encoding="utf-8")
    env_tree = ast.parse(env_src, filename=str(env_path))
    env_imports = _collect_ast_imports(env_tree, top_level_only=False)
    for mod in env_imports:
        assert not mod.startswith("<relative:"), f"env.py must not use relative imports: {mod}"
        assert not mod.startswith("tools."), f"env.py must not import tools.* ({mod})"
        root_pkg = mod.split(".")[0]
        assert root_pkg in stdlib_names, f"env.py imported non-stdlib module: {mod}"

    # 2. hooks/dispatch.py: top-level stdlib-only, zero forbidden imports or literals
    disp_src = dispatch_path.read_text(encoding="utf-8")
    disp_tree = ast.parse(disp_src, filename=str(dispatch_path))

    for mod in _collect_ast_imports(disp_tree, top_level_only=True):
        assert not mod.startswith("<relative:"), f"dispatch.py must not use top-level relative imports: {mod}"
        root_pkg = mod.split(".")[0]
        assert root_pkg in stdlib_names or mod in ("tools.common.env", "tools.common"), (
            f"dispatch.py top-level import must be stdlib-only, found: {mod}"
        )

    all_disp_imports = _collect_ast_imports(disp_tree, top_level_only=False)
    allowed_non_stdlib = {"tools.common.env", "tools.brigade.orchestrator_guard", "tools.brigade"}
    for mod in all_disp_imports:
        assert not any(mod == p or mod.startswith(p + ".") for p in forbidden_prefixes), (
            f"dispatch.py must never import {mod}"
        )
        root_pkg = mod.split(".")[0]
        if root_pkg not in stdlib_names:
            assert mod in allowed_non_stdlib, f"Unexpected non-stdlib import in dispatch.py: {mod}"

    for lit in _collect_non_docstring_string_literals(disp_tree):
        low = lit.lower()
        for bad in forbidden_literals:
            assert bad not in low, f"Forbidden literal {bad!r} found in hooks/dispatch.py: {lit!r}"
        assert not re.search(r"(?<![a-z0-9_-])gh(?:-axi)?(?![a-z0-9_-])", low), (
            f"Forbidden gh/gh-axi CLI literal in hooks/dispatch.py: {lit!r}"
        )


def test_tools_common_init_lazy_pep562_no_eager_runner_import() -> None:
    probe_code = (
        "import json, sys; "
        "import tools.common.env as env; "
        "print(json.dumps({"
        "'runner': 'tools.common.runner' in sys.modules, "
        "'toon': 'tools.common.toon' in sys.modules, "
        "'fs': 'tools.common.fs' in sys.modules, "
        "'subprocess': 'subprocess' in sys.modules, "
        "'has_env': hasattr(env, 'detect_os_mode')"
        "}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe_code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(proc.stdout.strip())
    assert info["has_env"] is True
    assert info["runner"] is False, "importing tools.common.env eagerly loaded tools.common.runner"
    assert info["toon"] is False, "importing tools.common.env eagerly loaded tools.common.toon"
    assert info["fs"] is False, "importing tools.common.env eagerly loaded tools.common.fs"
    assert info["subprocess"] is False, "importing tools.common.env eagerly loaded subprocess"

    # Backward-compatible lazy exports on tools.common must still resolve cleanly
    reexport_code = (
        "from tools.common import ("
        "normalize_target_path, to_wsl_path, is_wsl_path, "
        "run_command, setup_utf8_console, toon_encode, toon_dumps"
        "); "
        "assert callable(normalize_target_path) and callable(run_command) and callable(toon_dumps)"
    )
    subprocess.run([sys.executable, "-c", reexport_code], cwd=str(REPO_ROOT), check=True)


def test_dispatch_vanilla_payload_never_imports_guard_or_runner_and_is_fast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    dispatch_path = REPO_ROOT / "hooks" / "dispatch.py"
    assert dispatch_path.is_file(), f"Missing {dispatch_path}"

    tp = _write_transcript(
        tmp_path / "vanilla_tp.jsonl",
        [{"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "fix src/app.ts"}],
    )
    payload = {
        "conversationId": "vanilla-latency-1",
        "lastUserInput": "fix src/app.ts",
        "transcriptPath": str(tp),
        "toolCall": {"name": "write_file", "args": {"Path": "src/app.ts", "Content": "x"}},
    }

    # 1. Subprocess sys.modules proof: orchestrator_guard / runner / tracker / yaml never imported
    probe_script = (
        "import importlib.util, io, json, sys; "
        f"spec = importlib.util.spec_from_file_location('d', {str(dispatch_path)!r}); "
        "mod = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(mod); "
        "sys.argv = ['dispatch.py', 'pre_tool']; "
        f"sys.stdin = io.StringIO({json.dumps(json.dumps(payload))}); "
        "buf = io.StringIO(); orig_stdout = sys.stdout; sys.stdout = buf; "
        "\ntry:\n mod.main()\nexcept SystemExit:\n pass\nfinally:\n sys.stdout = orig_stdout\n"
        "result = {"
        "'out': json.loads(buf.getvalue().strip()), "
        "'guard': 'tools.brigade.orchestrator_guard' in sys.modules, "
        "'runner': 'tools.common.runner' in sys.modules, "
        "'tracker': 'tools.tracker' in sys.modules, "
        "'yaml': 'yaml' in sys.modules"
        "}; "
        "print(json.dumps(result))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe_script],
        cwd=str(REPO_ROOT),
        env=_make_subprocess_env(paths),
        capture_output=True,
        text=True,
        check=True,
    )
    res = json.loads(proc.stdout.strip())
    assert res["out"] == {"decision": "allow"}
    assert res["guard"] is False, "Vanilla dispatch imported orchestrator_guard"
    assert res["runner"] is False, "Vanilla dispatch imported tools.common.runner"
    assert res["tracker"] is False, "Vanilla dispatch imported tools.tracker"
    assert res["yaml"] is False, "Vanilla dispatch imported yaml"

    # 2. In-process INV-ORCH-HOOK-LATENCY check (< 50ms)
    dispatch_mod = _load_dispatch_module()
    t0 = time.perf_counter()
    enforced, _ = dispatch_mod.should_enforce_hooks(payload)
    out = _run_dispatch_in_process(dispatch_mod, monkeypatch, capsys, "pre_tool", payload)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert enforced is False
    assert out == {"decision": "allow"}
    assert elapsed_ms < 50.0, f"In-process vanilla hook dispatch took {elapsed_ms:.2f}ms (>= 50ms)"


# ---------------------------------------------------------------------------
# Group C: hooks/dispatch.py Session-Gating Matrix & Fail-Open Error Boundary
# ---------------------------------------------------------------------------


def test_vanilla_user_explicit_chat_and_generic_tool_output_passthrough(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    dispatch = _load_dispatch_module()

    # Transcript has normal USER_EXPLICIT + GENERIC tool output & PLANNER_RESPONSE mentioning /edge-orchestrator
    tp = _write_transcript(
        tmp_path / "vanilla_with_generic_mention.jsonl",
        [
            {"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "fix src/app.ts"},
            {
                "step_index": 1,
                "type": "GENERIC",
                "source": "MODEL",
                "content": "Read file skills/edge-orchestrator/SKILL.md: run /edge-orchestrator to start",
            },
            {
                "step_index": 2,
                "type": "PLANNER_RESPONSE",
                "source": "MODEL",
                "content": "You could invoke /edge-orchestrator if needed, fixing src/app.ts directly.",
            },
        ],
    )

    cid = "vanilla-chat-001"
    for tool_call in (
        {"name": "write_file", "args": {"Path": "src/app.ts", "Content": "export const x = 1;"}},
        {"name": "read_file", "args": {"Path": "src/app.ts"}},
        {"name": "run_command", "args": {"CommandLine": 'wsl bash -c "echo $FOO"'}},
    ):
        payload = {
            "conversationId": cid,
            "lastUserInput": "fix src/app.ts",
            "transcriptPath": str(tp),
            "toolCall": tool_call,
        }
        enforced, _ = dispatch.should_enforce_hooks(payload)
        assert enforced is False, f"Vanilla chat with GENERIC mention must NOT arm hooks: {tool_call}"
        res = _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_tool", payload)
        assert res == {"decision": "allow"}
        assert "overwrite" not in res

    # PostToolUse must return {} with ZERO station/session/brigade file side-effects
    repo_dir = tmp_path / "fake_repo"
    repo_dir.mkdir()
    post_payload = {
        "conversationId": cid,
        "lastUserInput": "fix src/app.ts",
        "transcriptPath": str(tp),
        "cwd": str(repo_dir),
        "toolCall": {"name": "invoke_subagent", "args": {"Role": "Coder", "Prompt": "help"}},
        "toolResponse": {"conversationId": "child-sub-999"},
    }
    post_res = _run_dispatch_in_process(dispatch, monkeypatch, capsys, "post_tool", post_payload)
    assert post_res == {}
    assert not paths["stations_file"].exists(), "Vanilla post_tool must not write edge_active_stations.json"
    assert not paths["sessions_dir"].exists() or not any(paths["sessions_dir"].iterdir())
    assert not (repo_dir / ".edge" / "brigade.json").exists()

    # PreInvocation must inject zero steps
    pre_inv_res = _run_dispatch_in_process(
        dispatch,
        monkeypatch,
        capsys,
        "pre_invocation",
        {"conversationId": cid, "lastUserInput": "fix src/app.ts", "transcriptPath": str(tp)},
    )
    assert pre_inv_res == {"injectSteps": []}


@pytest.mark.parametrize(
    "trigger_input",
    [
        "/edge-orchestrator build auth feature",
        "please run /edge-orchestrator now",
        "<skill_name>edge-orchestrator</skill_name>",
        "[edge_orchestrator] start session",
    ],
)
def test_orchestrator_activation_turn1_last_user_input_persists_marker_and_enforces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    trigger_input: str,
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    dispatch = _load_dispatch_module()

    cid = "orch-turn1-cid"
    tp = _write_transcript(
        tmp_path / "orch_turn1.jsonl",
        [{"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": trigger_input}],
    )
    base_payload = {
        "conversationId": cid,
        "lastUserInput": trigger_input,
        "transcriptPath": str(tp),
    }

    enforced, _ = dispatch.should_enforce_hooks(base_payload)
    assert enforced is True
    assert (paths["sessions_dir"] / f"{cid}.json").is_file(), "Must persist session marker in edge_active_sessions/"

    res_write = _run_dispatch_in_process(
        dispatch,
        monkeypatch,
        capsys,
        "pre_tool",
        {**base_payload, "toolCall": {"name": "write_file", "args": {"Path": "src/app.ts", "Content": "x"}}},
    )
    assert res_write["decision"] == "deny"

    res_read = _run_dispatch_in_process(
        dispatch,
        monkeypatch,
        capsys,
        "pre_tool",
        {**base_payload, "toolCall": {"name": "read_file", "args": {"Path": "src/app.ts"}}},
    )
    assert res_read["decision"] == "deny"

    res_inv = _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_invocation", base_payload)
    assert len(res_inv.get("injectSteps", [])) >= 1
    assert "EDGE ORCHESTRATOR ENFORCED" in json.dumps(res_inv)


def test_orchestrator_activation_turn5_transcript_user_input_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    dispatch = _load_dispatch_module()

    cid = "orch-turn5-cid"
    tp = _write_transcript(
        tmp_path / "orch_turn5.jsonl",
        [
            {"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "explain architecture"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "source": "MODEL", "content": "Sure, reading..."},
            {"step_index": 2, "type": "GENERIC", "source": "MODEL", "content": "readme summary"},
            {"step_index": 3, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "now let's plan"},
            {"step_index": 4, "type": "PLANNER_RESPONSE", "source": "MODEL", "content": "ready"},
            {"step_index": 5, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "/edge-orchestrator implement slice"},
        ],
    )
    # lastUserInput absent/empty on a subsequent tool call inside Turn 5
    payload = {
        "conversationId": cid,
        "lastUserInput": "",
        "transcriptPath": str(tp),
        "toolCall": {"name": "write_file", "args": {"Path": "src/feature.ts", "Content": "x"}},
    }
    enforced, _ = dispatch.should_enforce_hooks(payload)
    assert enforced is True
    assert (paths["sessions_dir"] / f"{cid}.json").is_file()

    res_write = _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_tool", payload)
    assert res_write["decision"] == "deny"

    res_inv = _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_invocation", payload)
    assert "EDGE ORCHESTRATOR ENFORCED" in json.dumps(res_inv)


def test_subsequent_turn_stays_enforced_via_persistent_session_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    dispatch = _load_dispatch_module()

    cid = "orch-persisted-cid"
    paths["sessions_dir"].mkdir(parents=True, exist_ok=True)
    (paths["sessions_dir"] / f"{cid}.json").write_text(json.dumps({"conversationId": cid}), encoding="utf-8")

    # Later turn has normal lastUserInput with NO /edge-orchestrator token anywhere
    tp = _write_transcript(
        tmp_path / "later_turn.jsonl",
        [{"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "continue implementation"}],
    )
    payload = {
        "conversationId": cid,
        "lastUserInput": "continue implementation",
        "transcriptPath": str(tp),
        "toolCall": {"name": "write_file", "args": {"Path": "src/service.ts", "Content": "code"}},
    }
    enforced, _ = dispatch.should_enforce_hooks(payload)
    assert enforced is True

    res = _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_tool", payload)
    assert res["decision"] == "deny"


def test_dispatch_cli_from_external_cwd_resolves_plugin_root_and_enforces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    external_cwd = tmp_path / "external_workspace"
    external_cwd.mkdir()

    tp = _write_transcript(
        tmp_path / "ext_cwd_orch.jsonl",
        [{"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "/edge-orchestrator go"}],
    )
    payload = {
        "conversationId": "ext-cwd-orch-1",
        "lastUserInput": "/edge-orchestrator go",
        "transcriptPath": str(tp),
        "toolCall": {"name": "write_file", "args": {"Path": "src/app.ts", "Content": "x"}},
    }
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "dispatch.py"), "pre_tool"],
        cwd=str(external_cwd),
        env=_make_subprocess_env(paths),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip())["decision"] == "deny"


def test_station_gating_registered_and_token_vs_vanilla_system_subagent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    dispatch = _load_dispatch_module()

    # 1. Registered station in edge_active_stations.json -> enforced
    reg_cid = "station-reg-coder"
    paths["stations_file"].write_text(
        json.dumps(
            {
                "version": "1.0",
                "sessions": {},
                "stations": {
                    reg_cid: {
                        "conversationId": reg_cid,
                        "role": "CODER",
                        "canonicalRole": "CODER",
                        "parentConversationId": "orch-parent",
                        "status": "IDLE",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    res_reg = _run_dispatch_in_process(
        dispatch,
        monkeypatch,
        capsys,
        "pre_tool",
        {
            "conversationId": reg_cid,
            "toolCall": {"name": "write_file", "args": {"Path": "tests/test_x.py", "Content": "x"}},
        },
    )
    assert res_reg["decision"] == "deny", "Registered CODER station must be blocked by Test Immutability Guard"

    # 2. Unregistered station with explicit [edge-station:<role>] token -> enforced
    tp_edge_station = _write_transcript(
        tmp_path / "edge_station.jsonl",
        [
            {
                "step_index": 0,
                "source": "SYSTEM",
                "type": "SYSTEM_MESSAGE",
                "content": "[Message] content=[edge-station:EXAMINER] You are the EXAMINER station. Review diff.",
            }
        ],
    )
    payload_edge_station = {
        "conversationId": "unreg-edge-examiner",
        "transcriptPath": str(tp_edge_station),
        "toolCall": {"name": "write_file", "args": {"Path": "src/app.ts", "Content": "x"}},
    }
    enforced_st, _ = dispatch.should_enforce_hooks(payload_edge_station)
    assert enforced_st is True
    res_st = _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_tool", payload_edge_station)
    assert res_st["decision"] == "deny"

    # 3. Vanilla SYSTEM subagent & vanilla swarm WITHOUT registration or [edge-station:] token -> pass-through!
    tp_vanilla_sub = _write_transcript(
        tmp_path / "vanilla_subagent.jsonl",
        [
            {
                "step_index": 0,
                "source": "SYSTEM",
                "type": "SYSTEM_MESSAGE",
                "content": "[Message] content=[swarm] new board message #1 @coder You are helping debug src/app.ts.",
            }
        ],
    )
    payload_vanilla_sub = {
        "conversationId": "unreg-vanilla-swarm-1",
        "transcriptPath": str(tp_vanilla_sub),
        "toolCall": {"name": "write_file", "args": {"Path": "src/app.ts", "Content": "x"}},
    }
    enforced_vs, _ = dispatch.should_enforce_hooks(payload_vanilla_sub)
    assert enforced_vs is False, "Vanilla SYSTEM/swarm subagent without [edge-station:] must NOT be gated"
    assert _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_tool", payload_vanilla_sub) == {
        "decision": "allow"
    }
    assert _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_invocation", payload_vanilla_sub) == {
        "injectSteps": []
    }


def test_kill_switch_env_and_machine_config_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_runtime_paths(monkeypatch, tmp_path)
    env = _load_env_module()
    dispatch = _load_dispatch_module()

    tp = _write_transcript(
        tmp_path / "kill_tp.jsonl",
        [{"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "/edge-orchestrator run"}],
    )
    payload = {
        "conversationId": "kill-switch-cid",
        "lastUserInput": "/edge-orchestrator run",
        "transcriptPath": str(tp),
        "toolCall": {"name": "write_file", "args": {"Path": "src/app.ts", "Content": "x"}},
    }

    # 1. EDGE_HOOKS=off overrides even strict machine.json + explicit trigger
    env.save_machine_config(env.MachineConfig(hooks_mode="strict"))
    monkeypatch.setenv("EDGE_HOOKS", "off")
    enforced, _ = dispatch.should_enforce_hooks(payload)
    assert enforced is False
    assert _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_tool", payload) == {"decision": "allow"}
    assert _run_dispatch_in_process(dispatch, monkeypatch, capsys, "post_tool", payload) == {}
    assert _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_invocation", payload) == {"injectSteps": []}

    # 2. machine.json hooks_mode="off"
    monkeypatch.delenv("EDGE_HOOKS", raising=False)
    env.save_machine_config(env.MachineConfig(hooks_mode="off"))
    enforced2, _ = dispatch.should_enforce_hooks(payload)
    assert enforced2 is False
    assert _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_tool", payload) == {"decision": "allow"}
    assert _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_invocation", payload) == {"injectSteps": []}


def test_strict_mode_machine_config_and_afk_and_no_mistakes_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_runtime_paths(monkeypatch, tmp_path)
    env = _load_env_module()
    dispatch = _load_dispatch_module()

    tp = _write_transcript(
        tmp_path / "strict_tp.jsonl",
        [{"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "edit src/app.ts"}],
    )
    plain_payload = {
        "conversationId": "strict-plain-cid",
        "lastUserInput": "edit src/app.ts",
        "transcriptPath": str(tp),
        "toolCall": {"name": "write_file", "args": {"Path": "src/app.ts", "Content": "x"}},
    }

    # 1. machine.json hooks_mode="strict" enforces even vanilla USER_EXPLICIT chat
    env.save_machine_config(env.MachineConfig(hooks_mode="strict"))
    enforced_strict, _ = dispatch.should_enforce_hooks(plain_payload)
    assert enforced_strict is True
    res_strict = _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_tool", plain_payload)
    assert res_strict["decision"] == "deny"

    # 2. NO_MISTAKES=1 exempts even under hooks_mode="strict"
    monkeypatch.setenv("NO_MISTAKES", "1")
    enforced_nm, _ = dispatch.should_enforce_hooks(plain_payload)
    assert enforced_nm is False
    assert _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_tool", plain_payload) == {"decision": "allow"}
    assert _run_dispatch_in_process(dispatch, monkeypatch, capsys, "pre_invocation", plain_payload) == {
        "injectSteps": []
    }
    monkeypatch.delenv("NO_MISTAKES", raising=False)

    # 3. EDGE_AFK=1 enforces under default session mode
    env.save_machine_config(env.MachineConfig(hooks_mode="session"))
    monkeypatch.setenv("EDGE_AFK", "1")
    enforced_afk, _ = dispatch.should_enforce_hooks(plain_payload)
    assert enforced_afk is True
    res_afk = _run_dispatch_in_process(
        dispatch,
        monkeypatch,
        capsys,
        "pre_tool",
        {
            "conversationId": "afk-cid-1",
            "toolCall": {"name": "invoke_subagent", "args": {"Role": "CODER", "Prompt": "code"}},
        },
    )
    assert res_afk["decision"] == "deny"


def test_dispatch_fail_open_error_boundary_on_exception_and_bad_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    dispatch = _load_dispatch_module()

    # 1. Forced internal exception must still exit 0 and return valid fail-open JSON
    def _boom(_payload: Dict[str, Any]) -> Tuple[bool, str]:
        raise RuntimeError("simulated internal crash")

    monkeypatch.setattr(dispatch, "should_enforce_hooks", _boom)

    expected = {
        "pre_tool": {"decision": "allow"},
        "post_tool": {},
        "pre_invocation": {"injectSteps": []},
    }
    for mode, want in expected.items():
        got = _run_dispatch_in_process(dispatch, monkeypatch, capsys, mode, {"conversationId": "err-1"})
        assert got == want

    # 2. Malformed stdin JSON in subprocess must exit 0 with valid fail-open JSON
    for mode, want in expected.items():
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "hooks" / "dispatch.py"), mode],
            cwd=str(REPO_ROOT),
            env=_make_subprocess_env(paths),
            input="{corrupt-json",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"dispatch.py {mode} failed on corrupt stdin: stderr={proc.stderr!r}"
        assert json.loads(proc.stdout.strip()) == want


# ---------------------------------------------------------------------------
# Group D: Minimal orchestrator_guard.py Seams & Station Token
# ---------------------------------------------------------------------------


def test_orchestrator_guard_portability_seams_and_station_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    env = _load_env_module()
    guard = _load_guard_module()
    monkeypatch.setattr(guard, "ACTIVE_STATIONS_FILE", paths["stations_file"], raising=False)

    # 1. get_active_stations_path delegates to env.get_active_stations_path()
    assert guard.get_active_stations_path() == paths["stations_file"]

    # 2. to_wsl_path delegates to env.resolve_host_path (empty -> Path(""))
    assert guard.to_wsl_path("") == Path("")
    monkeypatch.setattr(env, "detect_os_mode", lambda: "windows")
    if hasattr(guard, "detect_os_mode"):
        monkeypatch.setattr(guard, "detect_os_mode", lambda: "windows")
    win_res = str(guard.to_wsl_path(r"C:\Users\alice\transcript.jsonl")).replace("\\", "/")
    assert not win_res.startswith("/mnt/"), f"Windows mode must not convert C:\\ to /mnt/c: {win_res}"

    monkeypatch.setattr(env, "detect_os_mode", lambda: "wsl")
    if hasattr(guard, "detect_os_mode"):
        monkeypatch.setattr(guard, "detect_os_mode", lambda: "wsl")
    assert guard.to_wsl_path(r"C:\Users\alice\transcript.jsonl").as_posix() == "/mnt/c/Users/alice/transcript.jsonl"

    # 3. _check_no_mistakes_transcript resolves transcriptPath via to_wsl_path
    nm_tp = tmp_path / "nm_mapped_transcript.jsonl"
    _write_transcript(
        nm_tp,
        [{"step_index": 0, "source": "USER_EXPLICIT", "content": "pipeline-attestation run"}],
    )
    monkeypatch.setattr(guard, "to_wsl_path", lambda raw: nm_tp if raw == r"Z:\fake\transcript.jsonl" else Path(raw))
    assert guard._check_no_mistakes_transcript({"transcriptPath": r"Z:\fake\transcript.jsonl"}) is not None

    # 4. _handle_run_command_wsl_guard skips on native macos/linux
    for native_os in ("macos", "linux"):
        monkeypatch.setattr(env, "detect_os_mode", lambda m=native_os: m)
        if hasattr(guard, "detect_os_mode"):
            monkeypatch.setattr(guard, "detect_os_mode", lambda m=native_os: m)
        assert guard._handle_run_command_wsl_guard("run_command", {"CommandLine": "wsl --list"}) is None

    # 5. Station spawn token [edge-station:<ROLE>] attached for swarm add & invoke_subagent, NOT browser
    res_swarm = guard.handle_pre_tool(
        {
            "conversationId": "orch-token-parent",
            "toolCall": {"name": "swarm", "args": {"action": "add", "name": "coder", "brief": "Implement Slice 1"}},
        }
    )
    assert res_swarm.get("decision") == "allow"
    assert "[edge-station:CODER]" in res_swarm.get("overwrite", {}).get("brief", "")

    res_inv = guard.handle_pre_tool(
        {
            "conversationId": "orch-token-parent",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"Role": "Examiner", "TypeName": "self", "Prompt": "Review diff"},
            },
        }
    )
    assert res_inv.get("decision") == "allow"
    assert "[edge-station:EXAMINER]" in res_inv.get("overwrite", {}).get("Prompt", "")

    res_browser = guard.handle_pre_tool(
        {
            "conversationId": "orch-token-parent",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"TypeName": "browser", "Role": "Browser Automation Subagent", "Prompt": "Open page"},
            },
        }
    )
    assert res_browser.get("decision") == "allow"
    assert "[edge-station:" not in json.dumps(res_browser)


# ---------------------------------------------------------------------------
# Group E: hooks.json + .gitattributes + hooks/dispatch.cmd Contracts & Live sh
# ---------------------------------------------------------------------------


def test_root_hooks_json_cross_os_schema_contract() -> None:
    hooks_json_path = REPO_ROOT / "hooks.json"
    raw = hooks_json_path.read_text(encoding="utf-8")
    assert "/home/oguz" not in raw
    assert "oguz_" not in raw
    assert not re.search(r"(?i)\bwsl(?:\.exe)?\b", raw)

    data = json.loads(raw)
    guard_cfg = data["edge-orchestrator-guard"]

    pre_cmd = guard_cfg["PreToolUse"][0]["hooks"][0]["command"]
    post_cmd = guard_cfg["PostToolUse"][0]["hooks"][0]["command"]
    inv_cmd = guard_cfg["PreInvocation"][0]["command"]

    assert pre_cmd == 'cd . && "hooks/dispatch.cmd" pre_tool'
    assert post_cmd == 'cd . && "hooks/dispatch.cmd" post_tool'
    assert inv_cmd == 'cd . && "hooks/dispatch.cmd" pre_invocation'
    assert guard_cfg["PreInvocation"][0]["type"] == "command"
    assert guard_cfg["PreInvocation"][0]["timeout"] == 30


def test_gitattributes_enforces_lf_for_dispatch_cmd_and_sh() -> None:
    ga_path = REPO_ROOT / ".gitattributes"
    assert ga_path.is_file(), f"Missing root .gitattributes at {ga_path}"
    lines = [ln.strip() for ln in ga_path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert any("hooks/dispatch.cmd" in ln and "eol=lf" in ln for ln in lines), (
        ".gitattributes must enforce 'hooks/dispatch.cmd text eol=lf'"
    )
    assert any("*.sh" in ln and "eol=lf" in ln for ln in lines), (
        ".gitattributes must enforce '*.sh text eol=lf'"
    )


def test_dispatch_cmd_lf_executable_zero_labels_nul_probes_cache_no_wsl() -> None:
    cmd_path = REPO_ROOT / "hooks" / "dispatch.cmd"
    assert cmd_path.is_file(), f"Missing polyglot launcher at {cmd_path}"

    raw_bytes = cmd_path.read_bytes()
    assert b"\r\n" not in raw_bytes and b"\r" not in raw_bytes, "hooks/dispatch.cmd must use LF-only line endings"

    if os.name == "posix":
        mode = os.stat(cmd_path).st_mode
        assert bool(mode & stat.S_IXUSR), "hooks/dispatch.cmd must have +x executable bit on POSIX"

    text = raw_bytes.decode("utf-8")
    assert not re.search(r"(?im)\bwsl(?:\.exe)?\b", text), "hooks/dispatch.cmd must not contain any wsl fallback"

    # Extract Windows batch block between polyglot ': << ... CMDBLOCK' header and 'CMDBLOCK'
    m = re.search(r"^:\s*<<\s*['\"]?CMDBLOCK['\"]?\n(.*?)^CMDBLOCK\s*$", text, re.MULTILINE | re.DOTALL)
    assert m is not None, "hooks/dispatch.cmd must use ': << CMDBLOCK' ... 'CMDBLOCK' polyglot structure"
    win_block = m.group(1)

    assert not re.search(r"(?im)\bgoto\b", win_block), "Windows branch must have ZERO 'goto' statements"
    assert not re.search(r"(?im)\bcall\s+:", win_block), "Windows branch must have ZERO 'call :label' statements"
    assert not re.search(r"(?m)^\s*:[A-Za-z0-9_.-]+", win_block), "Windows branch must have ZERO ':label' lines"
    assert "python_exe.txt" in win_block, "Windows branch must check cached python_exe.txt first"

    probe_lines = [
        ln for ln in win_block.splitlines() if ("import sys" in ln or re.search(r"(?i)\bwhere\s+uv\b", ln))
    ]
    assert probe_lines, "Windows branch must include runtime probes"
    for pln in probe_lines:
        assert "<nul" in pln, f"Windows probe must attach <nul so stdin JSON is not consumed: {pln!r}"


@pytest.mark.skipif(os.name == "nt" or shutil.which("sh") is None, reason="POSIX sh required")
def test_dispatch_cmd_live_posix_sh_execution_vanilla_off_and_empty_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _isolate_runtime_paths(monkeypatch, tmp_path)
    cmd_path = REPO_ROOT / "hooks" / "dispatch.cmd"
    assert cmd_path.is_file(), f"Missing {cmd_path}"

    tp = _write_transcript(
        tmp_path / "sh_vanilla.jsonl",
        [{"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "fix src/app.ts"}],
    )
    vanilla_payload = {
        "conversationId": "sh-vanilla-1",
        "lastUserInput": "fix src/app.ts",
        "transcriptPath": str(tp),
        "toolCall": {"name": "write_file", "args": {"Path": "src/app.ts", "Content": "x"}},
    }

    # (a) Live vanilla execution across pre_tool, post_tool, pre_invocation
    expected_vanilla = {
        "pre_tool": {"decision": "allow"},
        "post_tool": {},
        "pre_invocation": {"injectSteps": []},
    }
    base_env = _make_subprocess_env(paths)
    for mode, want in expected_vanilla.items():
        proc = subprocess.run(
            ["sh", "-c", f'cd . && "hooks/dispatch.cmd" {mode}'],
            cwd=str(REPO_ROOT),
            env=base_env,
            input=json.dumps(vanilla_payload),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"sh dispatch.cmd {mode} failed: stderr={proc.stderr!r}"
        assert json.loads(proc.stdout.strip()) == want

    # (b) EDGE_HOOKS=off even with /edge-orchestrator trigger -> allow + exit 0
    off_payload = {
        "conversationId": "sh-off-1",
        "lastUserInput": "/edge-orchestrator start",
        "transcriptPath": str(tp),
        "toolCall": {"name": "write_file", "args": {"Path": "src/app.ts", "Content": "x"}},
    }
    proc_off = subprocess.run(
        ["sh", "-c", 'cd . && "hooks/dispatch.cmd" pre_tool'],
        cwd=str(REPO_ROOT),
        env=_make_subprocess_env(paths, {"EDGE_HOOKS": "off"}),
        input=json.dumps(off_payload),
        capture_output=True,
        text=True,
    )
    assert proc_off.returncode == 0, proc_off.stderr
    assert json.loads(proc_off.stdout.strip()) == {"decision": "allow"}

    # (c) Empty PATH="" (no Python / uv found) -> fail-open JSON + exit 0
    sh_bin = shutil.which("sh") or "/bin/sh"
    for mode, want in expected_vanilla.items():
        proc_no_py = subprocess.run(
            [sh_bin, "-c", f'cd . && "hooks/dispatch.cmd" {mode}'],
            cwd=str(REPO_ROOT),
            env=_make_subprocess_env(paths, {"PATH": ""}),
            input=json.dumps(vanilla_payload),
            capture_output=True,
            text=True,
        )
        assert proc_no_py.returncode == 0, f"empty PATH fail-open failed for {mode}: stderr={proc_no_py.stderr!r}"
        assert json.loads(proc_no_py.stdout.strip()) == want


def test_utf8_bom_transcript_handled_by_dispatch_and_role_detection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_runtime_paths(monkeypatch, tmp_path)
    dispatch_mod = _load_dispatch_module()
    role_mod = importlib.import_module("tools.brigade.guard.role_detection")

    bom_tp = tmp_path / "bom_transcript.jsonl"
    line0 = json.dumps(
        {"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "/edge-orchestrator start"}
    )
    bom_tp.write_bytes(b"\xef\xbb\xbf" + (line0 + "\n").encode("utf-8"))

    enforced, reason = dispatch_mod.should_enforce_hooks(
        {"conversationId": "bom-cid-dispatch", "transcriptPath": str(bom_tp)}
    )
    assert enforced is True
    assert reason == "transcript_user_trigger"

    role, source = role_mod.detect_session_role(
        {"conversationId": "bom-cid-role", "transcriptPath": str(bom_tp)}
    )
    assert role == "ORCHESTRATOR"
    assert source == "transcript_root"
