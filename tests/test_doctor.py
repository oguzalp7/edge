#!/usr/bin/env python3
"""
RED Contract Tests for Session 1 — Slice 3:
tools/doctor/ (models, checks, cli, __main__), root README.md,
and Phase 0 Ontology Alignment (CONTEXT.md + docs/*/DOMAIN.md).
"""

import ast
from dataclasses import is_dataclass
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Hermetic Helpers
# ---------------------------------------------------------------------------


def _isolate_doctor_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Dict[str, Path]:
    for key in (
        "PLUGIN_ROOT",
        "EDGE_PLUGIN_ROOT",
        "PLUGIN_DATA",
        "EDGE_HOME",
        "EDGE_ANTIGRAVITY_DIR",
        "EDGE_ACTIVE_STATIONS_FILE",
        "EDGE_ACTIVE_SESSIONS_DIR",
        "EDGE_WSL_DISTRO",
        "WSL_DISTRO_NAME",
    ):
        monkeypatch.delenv(key, raising=False)

    edge_home = tmp_path / "edge_home"
    plugin_data = tmp_path / "plugin_data"
    edge_home.mkdir(parents=True, exist_ok=True)
    plugin_data.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PLUGIN_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("EDGE_HOME", str(edge_home))
    return {"edge_home": edge_home, "plugin_data": plugin_data}


def _make_healthy_plugin_tree(root: Path) -> Path:
    hooks_dir = root / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (root / "hooks.json").write_text((REPO_ROOT / "hooks.json").read_text(encoding="utf-8"), encoding="utf-8")
    (hooks_dir / "dispatch.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    cmd_path = hooks_dir / "dispatch.cmd"
    cmd_path.write_bytes(b": << 'CMDBLOCK'\n@echo off\nCMDBLOCK\nexit 0\n")
    if os.name == "posix":
        os.chmod(cmd_path, 0o755)
    return root


def _is_hooks_healthy(result: Any) -> bool:
    if isinstance(result, tuple):
        return bool(result[0])
    if isinstance(result, dict):
        return bool(result.get("ok", result.get("healthy", False)))
    return bool(getattr(result, "ok", getattr(result, "healthy", False)))


def _unpack_capability_matrix(result: Any) -> Tuple[List[Dict[str, Any]], str]:
    if isinstance(result, tuple) and len(result) == 2:
        raw_entries, profile = result
    elif isinstance(result, dict):
        raw_entries = result.get("capabilities", [])
        profile = result.get("recommended_profile", "")
    else:
        raw_entries = getattr(result, "capabilities", [])
        profile = getattr(result, "recommended_profile", "")

    norm_entries: List[Dict[str, Any]] = []
    for item in raw_entries:
        if hasattr(item, "to_dict"):
            norm_entries.append(item.to_dict())
        elif isinstance(item, dict):
            norm_entries.append(item)
        else:
            norm_entries.append(vars(item))
    return norm_entries, str(profile)


def _make_probes(models_mod: Any, available_names: Iterable[str]) -> Dict[str, Any]:
    avail_set = set(available_names)
    all_tools = (
        "python",
        "git",
        "node",
        "uv",
        "gh",
        "gh-axi",
        "treehouse",
        "lavish-axi",
        "chrome-devtools-axi",
        "chrome-dev-tools-axi",
        "wsl",
    )
    probes: Dict[str, Any] = {}
    for name in all_tools:
        is_avail = name in avail_set
        probes[name] = models_mod.ToolProbeResult(
            name=name,
            available=is_avail,
            path=f"/usr/bin/{name}" if is_avail else "",
            version="1.0.0" if is_avail else "",
        )
    return probes


# ---------------------------------------------------------------------------
# 1. tools/doctor/ Module Hygiene, SLOC, Stdlib-Only, Ontology Headers
# ---------------------------------------------------------------------------


def test_doctor_module_hygiene_sloc_stdlib_and_ontology_headers() -> None:
    doctor_dir = REPO_ROOT / "tools" / "doctor"
    expected_files = ("__init__.py", "__main__.py", "models.py", "checks.py", "cli.py")
    stdlib_names = sys.stdlib_module_names

    for fname in expected_files:
        fpath = doctor_dir / fname
        assert fpath.is_file(), f"Missing tools/doctor/{fname}"
        text = fpath.read_text(encoding="utf-8")
        lines = text.splitlines()
        assert len(lines) <= 300, f"tools/doctor/{fname} exceeds 300 lines ({len(lines)})"
        assert "oguz" not in text.lower(), f"tools/doctor/{fname} leaked 'oguz'"
        assert "Ubuntu-24.04" not in text, f"tools/doctor/{fname} hardcoded Ubuntu-24.04"

        tree = ast.parse(text, filename=str(fpath))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top in stdlib_names or top == "tools", (
                        f"Non-stdlib import {alias.name!r} in tools/doctor/{fname}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                top = node.module.split(".")[0]
                assert top in stdlib_names or top == "tools", (
                    f"Non-stdlib import {node.module!r} in tools/doctor/{fname}"
                )

    for core_fname in ("models.py", "checks.py", "cli.py"):
        head = "\n".join((doctor_dir / core_fname).read_text(encoding="utf-8").splitlines()[:30])
        for tag in ("@intent", "@concepts", "@invariants"):
            assert tag in head, f"tools/doctor/{core_fname} missing {tag} in top 30 lines"


def test_doctor_models_dataclasses_and_serialization() -> None:
    models = importlib.import_module("tools.doctor.models")
    for cls_name in ("ToolProbeResult", "CapabilityEntry", "DoctorReport"):
        cls = getattr(models, cls_name, None)
        assert cls is not None and is_dataclass(cls), f"tools.doctor.models.{cls_name} must be a dataclass"
        assert hasattr(cls, "to_dict"), f"{cls_name} must define to_dict()"

    probe = models.ToolProbeResult(name="git", available=True, path="/usr/bin/git", version="2.43.0")
    d = probe.to_dict()
    assert d["name"] == "git"
    assert d["available"] is True


# ---------------------------------------------------------------------------
# 2. checks.py: probe_binary, check_hooks_health, build_capability_matrix
# ---------------------------------------------------------------------------


def test_probe_binary_available_missing_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = importlib.import_module("tools.doctor.checks")

    # 1. Available binary with version extraction
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}" if name == "git" else None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "git version 2.43.0\n", ""),
    )
    ok_res = checks.probe_binary("git")
    assert ok_res.available is True
    assert "2.43.0" in ok_res.version

    # 2. Missing binary
    miss_res = checks.probe_binary("treehouse")
    assert miss_res.available is False

    # 3. subprocess.TimeoutExpired handled gracefully without raising
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/slowtool")

    def raise_timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=3)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    timeout_res = checks.probe_binary("slowtool")
    assert timeout_res is not None
    assert isinstance(timeout_res.to_dict(), dict)


def test_check_hooks_health_valid_and_broken_cases(tmp_path: Path) -> None:
    checks = importlib.import_module("tools.doctor.checks")

    # 1. Healthy plugin tree passes (both REPO_ROOT and isolated healthy copy)
    assert _is_hooks_healthy(checks.check_hooks_health(REPO_ROOT)) is True

    healthy_copy = _make_healthy_plugin_tree(tmp_path / "healthy")
    assert _is_hooks_healthy(checks.check_hooks_health(healthy_copy)) is True

    # 2. Corrupt hooks.json fails cleanly
    corrupt_json_root = _make_healthy_plugin_tree(tmp_path / "corrupt_json")
    (corrupt_json_root / "hooks.json").write_text("{corrupt", encoding="utf-8")
    assert _is_hooks_healthy(checks.check_hooks_health(corrupt_json_root)) is False

    # 3. Missing hooks/dispatch.cmd fails cleanly
    missing_cmd_root = _make_healthy_plugin_tree(tmp_path / "missing_cmd")
    (missing_cmd_root / "hooks" / "dispatch.cmd").unlink()
    assert _is_hooks_healthy(checks.check_hooks_health(missing_cmd_root)) is False

    # 4. Missing hooks/dispatch.py fails cleanly
    missing_py_root = _make_healthy_plugin_tree(tmp_path / "missing_py")
    (missing_py_root / "hooks" / "dispatch.py").unlink()
    assert _is_hooks_healthy(checks.check_hooks_health(missing_py_root)) is False

    # 5. Non-executable shim or CRLF endings on POSIX fails cleanly
    if os.name == "posix":
        noexec_root = _make_healthy_plugin_tree(tmp_path / "noexec_cmd")
        os.chmod(noexec_root / "hooks" / "dispatch.cmd", 0o644)
        assert _is_hooks_healthy(checks.check_hooks_health(noexec_root)) is False

        crlf_root = _make_healthy_plugin_tree(tmp_path / "crlf_cmd")
        (crlf_root / "hooks" / "dispatch.cmd").write_bytes(b": << 'CMDBLOCK'\r\n@echo off\r\nCMDBLOCK\r\n")
        os.chmod(crlf_root / "hooks" / "dispatch.cmd", 0o755)
        assert _is_hooks_healthy(checks.check_hooks_health(crlf_root)) is False


def test_build_capability_matrix_lite_core_full_and_browser_aliases() -> None:
    models = importlib.import_module("tools.doctor.models")
    checks = importlib.import_module("tools.doctor.checks")

    # 1. Lite: python + git only
    lite_entries, lite_profile = _unpack_capability_matrix(
        checks.build_capability_matrix(_make_probes(models, ("python", "git")))
    )
    assert lite_profile == "lite"
    assert lite_entries, "Capability matrix must return entries"
    lite_statuses = [str(e.get("status", "")).lower() for e in lite_entries]
    assert all(s in ("native", "passive", "unavailable") for s in lite_statuses)
    assert any(s in ("passive", "unavailable") for s in lite_statuses)

    # 2. Core: python + git + uv + gh + node (no treehouse/lavish/browser-axi)
    core_entries, core_profile = _unpack_capability_matrix(
        checks.build_capability_matrix(_make_probes(models, ("python", "git", "uv", "gh", "node")))
    )
    assert core_profile == "core"
    assert len(core_entries) == len(lite_entries)

    # 3. Full: complete toolchain including chrome-devtools-axi
    full_entries, full_profile = _unpack_capability_matrix(
        checks.build_capability_matrix(
            _make_probes(
                models,
                ("python", "git", "uv", "node", "gh", "gh-axi", "treehouse", "lavish-axi", "chrome-devtools-axi"),
            )
        )
    )
    assert full_profile == "full"
    assert all(
        str(e.get("status", "")).lower() == "native"
        for e in full_entries
        if "wsl" not in json.dumps(e).lower()
    )

    # 4. Alias spelling chrome-dev-tools-axi also resolves Full + native browser capability
    alias_entries, alias_profile = _unpack_capability_matrix(
        checks.build_capability_matrix(
            _make_probes(
                models,
                ("python", "git", "uv", "node", "gh", "gh-axi", "treehouse", "lavish-axi", "chrome-dev-tools-axi"),
            )
        )
    )
    assert alias_profile == "full"
    browser_rows = [
        e for e in alias_entries if "browser" in json.dumps(e).lower() or "chrome" in json.dumps(e).lower()
    ]
    assert browser_rows and all(str(r.get("status", "")).lower() == "native" for r in browser_rows)


# ---------------------------------------------------------------------------
# 3. CLI (--json, --init, python3 -m tools.doctor)
# ---------------------------------------------------------------------------


def test_doctor_cli_json_healthy_and_broken_hooks_exit_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_doctor_env(monkeypatch, tmp_path)
    doctor_cli = importlib.import_module("tools.doctor.cli")

    # 1. Healthy worktree -> exit 0 + valid DoctorReport JSON
    capsys.readouterr()
    rc_ok = doctor_cli.main(["--json"])
    out_ok = capsys.readouterr().out.strip()
    assert rc_ok == 0
    report = json.loads(out_ok)
    assert report["os_mode"] in ("windows", "wsl", "macos", "linux")
    assert report["recommended_profile"] in ("lite", "core", "full")
    assert "tools" in report and "capabilities" in report

    # 2. Broken hooks root -> exit 1 + valid JSON
    broken_root = _make_healthy_plugin_tree(tmp_path / "broken_plugin")
    (broken_root / "hooks.json").write_text("{invalid", encoding="utf-8")
    monkeypatch.setenv("PLUGIN_ROOT", str(broken_root))
    capsys.readouterr()
    rc_bad = doctor_cli.main(["--json"])
    out_bad = capsys.readouterr().out.strip()
    assert rc_bad == 1
    bad_report = json.loads(out_bad)
    assert isinstance(bad_report, dict)

    # 3. Human-readable output (without --json) exits 0 on healthy root
    monkeypatch.setenv("PLUGIN_ROOT", str(REPO_ROOT))
    capsys.readouterr()
    rc_human = doctor_cli.main([])
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert out_human.strip()

    # 4. python3 -m tools.doctor --json subprocess
    sub_env = os.environ.copy()
    sub_env["PLUGIN_ROOT"] = str(REPO_ROOT)
    sub_env["EDGE_HOME"] = str(tmp_path / "sub_edge_home")
    sub_env["PLUGIN_DATA"] = str(tmp_path / "sub_plugin_data")
    proc = subprocess.run(
        [sys.executable, "-m", "tools.doctor", "--json"],
        cwd=str(REPO_ROOT),
        env=sub_env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip())["recommended_profile"] in ("lite", "core", "full")


def test_doctor_cli_direct_script_invocation_without_pythonpath(tmp_path: Path) -> None:
    sub_env = os.environ.copy()
    sub_env.pop("PYTHONPATH", None)
    sub_env["PLUGIN_ROOT"] = str(REPO_ROOT)
    sub_env["EDGE_HOME"] = str(tmp_path / "script_edge_home")
    sub_env["PLUGIN_DATA"] = str(tmp_path / "script_plugin_data")
    external_cwd = tmp_path / "outside_cwd"
    external_cwd.mkdir()

    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "doctor" / "cli.py"), "--json"],
        cwd=str(external_cwd),
        env=sub_env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout.strip())
    assert parsed["os_mode"] in ("windows", "wsl", "macos", "linux")
    assert parsed["recommended_profile"] in ("lite", "core", "full")


def test_doctor_cli_init_writes_machine_json_and_caches_python_hermetically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _isolate_doctor_env(monkeypatch, tmp_path)
    doctor_cli = importlib.import_module("tools.doctor.cli")
    env_mod = importlib.import_module("tools.common.env")

    capsys.readouterr()
    rc = doctor_cli.main(
        [
            "--init",
            "--hooks-mode",
            "strict",
            "--profile",
            "full",
            "--wsl-distro",
            "Debian",
            "--json",
        ]
    )
    out = capsys.readouterr().out.strip()
    assert rc == 0
    parsed = json.loads(out)
    assert isinstance(parsed, dict)

    cfg_file = paths["edge_home"] / "machine.json"
    assert cfg_file.is_file(), "doctor --init must atomically create machine.json inside EDGE_HOME"
    leftovers = [p.name for p in paths["edge_home"].iterdir() if ".tmp" in p.name]
    assert leftovers == []

    loaded = env_mod.load_machine_config(cfg_file)
    assert loaded.hooks_mode == "strict"
    assert loaded.install_profile == "full"
    assert loaded.wsl_distro == "Debian"

    # Must cache sys.executable via cache_python_executable()
    edge_py_cache = paths["edge_home"] / "python_exe.txt"
    plugin_py_cache = paths["plugin_data"] / "python_exe.txt"
    assert edge_py_cache.is_file()
    assert plugin_py_cache.is_file()
    assert edge_py_cache.read_text(encoding="utf-8").strip() == sys.executable
    assert plugin_py_cache.read_text(encoding="utf-8").strip() == sys.executable


# ---------------------------------------------------------------------------
# 4. Root README.md & Phase 0 Ontology Alignment
# ---------------------------------------------------------------------------


def test_root_readme_cross_os_guide_and_no_hardcodes() -> None:
    readme_path = REPO_ROOT / "README.md"
    assert readme_path.is_file(), f"Missing root README.md at {readme_path}"
    text = readme_path.read_text(encoding="utf-8")
    low = text.lower()

    assert "oguz" not in low, "README.md must not contain hardcoded 'oguz' paths"
    assert "c:/users/oguz" not in low and "c:\\users\\oguz" not in low

    for token in ("winget", "brew", "apt", "wsl", "doctor", "--init", "edge_hooks=off"):
        assert token in low, f"README.md missing expected cross-OS section/token: {token!r}"
    for tier in ("lite", "core", "full"):
        assert re.search(rf"\b{tier}\b", low), f"README.md missing install profile tier: {tier!r}"


def test_slice3_ontology_alignment_and_zero_code_leaks() -> None:
    from tools.drift.models import matches_tracked_paths, parse_canonical_domain_doc, parse_context_glossary
    from tools.drift.scanner import validate_ontology

    context_text = (REPO_ROOT / "CONTEXT.md").read_text(encoding="utf-8-sig")
    context_globs, context_concepts = parse_context_glossary(context_text)

    # 1. Domain Map owns hooks/** (orchestration) and tools/doctor/** (brigade)
    assert matches_tracked_paths(["hooks/dispatch.py"], context_globs["orchestration"]) == ["hooks/dispatch.py"]
    assert matches_tracked_paths(
        ["tools/doctor/cli.py", "tools/doctor/checks.py", "tools/doctor/models.py"],
        context_globs["brigade"],
    ) == ["tools/doctor/cli.py", "tools/doctor/checks.py", "tools/doctor/models.py"]

    # 2. Closed Concept Glossary registers all 4 new concepts
    for concept in (
        "session-gated-hooks",
        "fail-open-dispatch",
        "cross-os-runtime-env",
        "doctor-preflight",
    ):
        assert concept in context_concepts, f"CONTEXT.md missing concept {concept!r}"

    # 3. DOMAIN.md documents register concepts + invariants without code leaks
    orch_doc = parse_canonical_domain_doc(
        (REPO_ROOT / "docs" / "orchestration" / "DOMAIN.md").read_text(encoding="utf-8-sig"),
        doc_path="docs/orchestration/DOMAIN.md",
        fallback_domain="orchestration",
    )
    assert {"session-gated-hooks", "fail-open-dispatch"}.issubset(set(orch_doc.concepts))
    assert {"INV-ORCH-SESSION-GATE", "INV-ORCH-FAIL-OPEN"}.issubset(set(orch_doc.invariant_ids))

    brigade_doc = parse_canonical_domain_doc(
        (REPO_ROOT / "docs" / "brigade" / "DOMAIN.md").read_text(encoding="utf-8-sig"),
        doc_path="docs/brigade/DOMAIN.md",
        fallback_domain="brigade",
    )
    assert {"cross-os-runtime-env", "doctor-preflight"}.issubset(set(brigade_doc.concepts))
    assert "INV-BRIGADE-CROSS-OS-ENV" in brigade_doc.invariant_ids
    assert "PAT-BRIGADE-DOCTOR-PREFLIGHT" in brigade_doc.pattern_ids

    # 4. Zero errors & zero warnings from validate_ontology
    report = validate_ontology(REPO_ROOT)
    assert not report.skipped
    assert not report.has_errors, f"Ontology errors: {report.issues}"
    assert report.issues == [], f"Ontology issues found: {report.issues}"
