#!/usr/bin/env python3
"""
Hermetic RED Contract Tests for Session 3 — Slice 2.3:
Cross-OS lavish-axi prototype bridge (tools/brigade/prototype.py),
Windows .cmd/.bat node shim unwrapping (BatBadBut prevention),
npx/HTML artifact fallback, pure-Python session state reading, and CLI wiring.
"""

import argparse
import ast
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Hermetic Helpers
# ---------------------------------------------------------------------------


def _load_prototype():
    return importlib.import_module("tools.brigade.prototype")


def _same_path(actual: str, expected: Path) -> bool:
    return os.path.normcase(os.path.realpath(actual)) == os.path.normcase(os.path.realpath(str(expected)))


def _make_fake_windows_npm_shim(tmp_path: Path, name: str, rel_script: str) -> Dict[str, Path]:
    bin_dir = tmp_path / "npm_bin"
    script_path = bin_dir / rel_script
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("console.log('ok');\n", encoding="utf-8")

    node_exe = bin_dir / "node.exe"
    node_exe.write_text("fake-node", encoding="utf-8")

    cmd_path = bin_dir / f"{name}.cmd"
    win_rel = rel_script.replace("/", "\\")
    cmd_path.write_text(
        "@ECHO off\r\n"
        "GOTO :start\r\n"
        ":start\r\n"
        f'"%~dp0\\node.exe" "%~dp0\\{win_rel}" %*\r\n',
        encoding="utf-8",
    )
    return {"bin_dir": bin_dir, "cmd": cmd_path, "script": script_path, "node": node_exe}


# ---------------------------------------------------------------------------
# 1. Windows .cmd/.bat Node Shim Unwrapping (BatBadBut Prevention)
# ---------------------------------------------------------------------------


def test_resolve_safe_node_argv_unwraps_windows_cmd_and_bat_shims(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proto = _load_prototype()
    shim = _make_fake_windows_npm_shim(tmp_path, "lavish-axi", "node_modules/lavish-axi/bin/cli.js")
    npx_shim = _make_fake_windows_npm_shim(tmp_path, "npx", "node_modules/npm/bin/npx-cli.js")

    # POSIX returns binary as-is
    with monkeypatch.context() as mp:
        mp.setattr(proto.os, "name", "posix")
        assert proto.resolve_safe_node_argv("/usr/local/bin/lavish-axi") == ["/usr/local/bin/lavish-axi"]
        assert proto.resolve_safe_node_argv(str(shim["cmd"])) == [str(shim["cmd"])]

    # Windows unwraps .cmd / .bat into [node.exe, target_script.js]
    with monkeypatch.context() as mp:
        mp.setattr(proto.os, "name", "nt")
        unwrapped = proto.resolve_safe_node_argv(str(shim["cmd"]), which_fn=lambda _n: str(shim["node"]))
        assert _same_path(unwrapped[0], shim["node"])
        assert _same_path(unwrapped[1], shim["script"])

        # .bat variant referencing %dp0% without tilde also unwraps cleanly
        bat_path = shim["bin_dir"] / "custom.bat"
        bat_path.write_text(
            '@echo off\r\n"%_prog%" "%dp0%\\node_modules\\npm\\bin\\npx-cli.js" %*\r\n',
            encoding="utf-8",
        )
        unwrapped_bat = proto.resolve_safe_node_argv(str(bat_path), which_fn=lambda _n: str(shim["node"]))
        assert _same_path(unwrapped_bat[0], shim["node"])
        assert _same_path(unwrapped_bat[1], npx_shim["script"])

        # Unresolvable .cmd without target script degrades safely to [cmd_path]
        broken_cmd = tmp_path / "broken.cmd"
        broken_cmd.write_text("@echo off\r\necho missing\r\n", encoding="utf-8")
        assert proto.resolve_safe_node_argv(str(broken_cmd), which_fn=lambda _n: str(shim["node"])) == [str(broken_cmd)]


# ---------------------------------------------------------------------------
# 2. Command Resolution Chain (lavish-axi -> npx -> artifact) & Path Formatting
# ---------------------------------------------------------------------------


def test_resolve_lavish_command_precedence_and_path_formatting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proto = _load_prototype()
    shim = _make_fake_windows_npm_shim(tmp_path, "lavish-axi", "node_modules/lavish-axi/bin/cli.js")
    npx_shim = _make_fake_windows_npm_shim(tmp_path, "npx", "node_modules/npm/bin/npx-cli.js")

    # 1. Direct lavish-axi CLI found (unwrapped on Windows) + fallback to npx
    with monkeypatch.context() as mp:
        mp.setattr(proto.os, "name", "nt")
        mode_cli, argv_cli = proto.resolve_lavish_command(
            which_fn=lambda name: str(shim["cmd"]) if name == "lavish-axi" else (str(shim["node"]) if name == "node" else None)
        )
        assert mode_cli == "cli"
        assert _same_path(argv_cli[0], shim["node"])
        assert _same_path(argv_cli[1], shim["script"])

        # 2. Fallback to npx --yes lavish-axi
        mode_npx, argv_npx = proto.resolve_lavish_command(
            which_fn=lambda name: str(npx_shim["cmd"]) if name == "npx" else (str(npx_shim["node"]) if name == "node" else None)
        )
        assert mode_npx == "npx"
        assert argv_npx[-2:] == ["--yes", "lavish-axi"]
        assert _same_path(argv_npx[0], npx_shim["node"])

    # 3. Neither lavish-axi nor npx -> artifact fallback
    mode_art, argv_art = proto.resolve_lavish_command(which_fn=lambda _name: None)
    assert mode_art == "artifact"
    assert argv_art == []

    # 4. format_prototype_cli_arg keeps native paths on Windows/macOS/Linux and translates UNC WSL paths on Windows
    monkeypatch.setattr(proto, "detect_os_mode", lambda: "windows")
    win_html = "C:/work/app/.lavish/login.html"
    assert proto.format_prototype_cli_arg(win_html) == win_html
    assert proto.format_prototype_cli_arg("//wsl.localhost/Ubuntu/home/alice/app/.lavish/login.html") == (
        "/home/alice/app/.lavish/login.html"
    )

    monkeypatch.setattr(proto, "detect_os_mode", lambda: "macos")
    mac_html = tmp_path / ".lavish" / "login.html"
    assert proto.format_prototype_cli_arg(mac_html) == str(mac_html)


# ---------------------------------------------------------------------------
# 3. execute_prototype_action, Pure-Python State Reader & CLI Wiring
# ---------------------------------------------------------------------------


def test_execute_prototype_action_shell_false_metachar_safety_and_artifact_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proto = _load_prototype()
    repo = tmp_path / "repo"
    lavish_dir = repo / ".lavish"
    lavish_dir.mkdir(parents=True)
    html_file = lavish_dir / "dashboard.html"
    html_file.write_text("<h1>Dashboard</h1>", encoding="utf-8")

    # 1. Missing / nonexistent file errors preserved (TestBrigadeCLIPrototype parity)
    rc_miss, _, err_miss = proto.execute_prototype_action(repo, "serve", None)
    assert rc_miss == 1 and err_miss
    rc_nofile, _, err_nofile = proto.execute_prototype_action(repo, "serve", ".lavish/missing.html")
    assert rc_nofile == 1 and err_nofile
    rc_poll_miss, _, _ = proto.execute_prototype_action(repo, "poll", None)
    assert rc_poll_miss == 1

    # 2. With Windows .cmd shim: list-form args, shell=False, metacharacters in --agent-reply intact
    shim = _make_fake_windows_npm_shim(tmp_path, "lavish-axi", "node_modules/lavish-axi/bin/cli.js")
    captured: List[Dict[str, Any]] = []

    def fake_subprocess_run(cmd, **kwargs):
        captured.append({"cmd": cmd, "kwargs": kwargs})
        return subprocess.CompletedProcess(cmd, 0, '{"session_ended": false}', "")

    with monkeypatch.context() as mp:
        mp.setattr(proto.os, "name", "nt")
        mp.setattr(proto, "detect_os_mode", lambda: "windows")
        mp.setattr(
            shutil,
            "which",
            lambda name: str(shim["cmd"]) if name == "lavish-axi" else (str(shim["node"]) if name == "node" else None),
        )
        mp.setattr(subprocess, "run", fake_subprocess_run)

        reply_payload = "Updated spacing && borders | contrast > 4.5 ^ 100% done"
        rc_poll, out_poll, _ = proto.execute_prototype_action(repo, "poll", ".lavish/dashboard.html", reply_payload)
        assert rc_poll == 0
        assert "session_ended" in out_poll
        assert len(captured) == 1
        invoked_cmd = captured[0]["cmd"]
        assert isinstance(invoked_cmd, list), "Prototype execution must use list-form argv, never shell strings"
        assert not captured[0]["kwargs"].get("shell", False)
        assert _same_path(invoked_cmd[0], shim["node"])
        assert "--agent-reply" in invoked_cmd
        reply_idx = invoked_cmd.index("--agent-reply") + 1
        assert invoked_cmd[reply_idx] == reply_payload

    # 3. Artifact fallback when neither lavish-axi nor npx exists (exit 0, file:// URI + human approval guidance)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    captured.clear()

    rc_art, out_art, err_art = proto.execute_prototype_action(repo, "serve", ".lavish/dashboard.html")
    assert rc_art == 0, err_art
    assert captured == [], "Artifact fallback must not spawn subprocesses"
    assert "file://" in out_art
    assert "ask_question" in out_art.lower() or "approval" in out_art.lower()

    rc_art_stop, _, _ = proto.execute_prototype_action(repo, "stop")
    assert rc_art_stop == 0

    # 4. cmd_prototype CLI delegation works seamlessly
    brigade_cli = importlib.import_module("tools.brigade.cli")
    rc_cli = brigade_cli.cmd_prototype(
        argparse.Namespace(repo=str(repo), action="serve", file=".lavish/dashboard.html", agent_reply=None)
    )
    assert rc_cli == 0


def test_read_lavish_sessions_pure_python_without_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proto = _load_prototype()
    state_dir = tmp_path / ".lavish-axi"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "state.json"

    assert proto.read_lavish_sessions(state_file) == []

    state_file.write_text(
        json.dumps(
            {
                "sessions": {
                    "sess-1": {
                        "file": "/work/.lavish/ui.html",
                        "status": "ended",
                        "endedAt": "2026-11-25T10:00:00Z",
                        "endedBy": "user",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    sessions = proto.read_lavish_sessions(state_file)
    assert len(sessions) == 1
    assert sessions[0]["id"] == "sess-1"
    assert sessions[0]["status"] == "ended"
    assert sessions[0]["endedBy"] == "user"

    # action="status" via execute_prototype_action reads Path.home()/.lavish-axi/state.json with 0 subprocess spawns
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("status action must not spawn python3 -c")),
    )
    rc_st, out_st, _ = proto.execute_prototype_action(tmp_path, "status")
    assert rc_st == 0
    parsed = json.loads(out_st)
    assert len(parsed) == 1 and parsed[0]["id"] == "sess-1"


# ---------------------------------------------------------------------------
# 4. Module Hygiene & Complexity Gate
# ---------------------------------------------------------------------------


def test_prototype_module_hygiene_sloc_cc_and_ontology_header() -> None:
    from tools.gate_cc import compute_source_max_cc, count_source_sloc

    proto_path = REPO_ROOT / "tools" / "brigade" / "prototype.py"
    assert proto_path.is_file(), "Missing tools/brigade/prototype.py"
    src = proto_path.read_text(encoding="utf-8")

    assert count_source_sloc(src, ".py") <= 180
    max_cc, fn_name = compute_source_max_cc(src, ".py")
    assert max_cc <= 10, f"prototype.py max CC exceeded 10: {fn_name}={max_cc}"

    top_30 = "\n".join(src.splitlines()[:30])
    for tag in ("@intent", "@concepts", "@invariants"):
        assert tag in top_30, f"prototype.py missing {tag} in top 30 lines"

    stdlib_names = sys.stdlib_module_names
    tree = ast.parse(src, filename=str(proto_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in stdlib_names or top == "tools"
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            top = node.module.split(".")[0]
            assert top in stdlib_names or top == "tools"
