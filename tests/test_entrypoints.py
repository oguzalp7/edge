#!/usr/bin/env python3
"""
Hermetic RED Contract Tests for Session 3 — Slice 3:
- Cross-OS packaging & scripts (pyproject.toml with [tool.uv] managed=false)
- Cross-OS zero-install wrappers (bin/brigade, bin/edge-doctor, bin/*.cmd) & .gitattributes
- tools/doctor/checks.py cross-OS fallback capability matrix
- Smoke-verified README.md installation & fallback matrix
- Phase 0 Ontology Alignment (CONTEXT.md, docs/brigade/DOMAIN.md, docs/orchestration/DOMAIN.md)
"""

import ast
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Dict, Iterable, Set

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Hermetic Helpers
# ---------------------------------------------------------------------------


def _ast_top_level_symbols(py_path: Path) -> Set[str]:
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    names: Set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def _extract_glossary_rows(context_text: str) -> Dict[str, tuple[str, str]]:
    rows: Dict[str, tuple[str, str]] = {}
    in_glossary = False
    for line in context_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_glossary = "Closed Concept Glossary" in stripped
            continue
        if not in_glossary or not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 3 or cells[0].startswith("---") or cells[0].lower() == "concept":
            continue
        concept = cells[0].strip("`").strip()
        if concept:
            rows[concept] = (cells[1], cells[2])
    return rows


def _make_probes(models_mod, available_names: Iterable[str]) -> Dict[str, object]:
    avail = set(available_names)
    all_tools = (
        "python",
        "git",
        "node",
        "uv",
        "gh",
        "gh-axi",
        "treehouse",
        "lavish-axi",
        "npx",
        "chrome-devtools-axi",
        "chrome-dev-tools-axi",
        "wsl",
    )
    return {
        name: models_mod.ToolProbeResult(
            name=name,
            available=(name in avail),
            path=f"/usr/bin/{name}" if name in avail else "",
            version="1.0.0" if name in avail else "",
        )
        for name in all_tools
    }


def _isolated_sub_env(tmp_path: Path) -> Dict[str, str]:
    sub_env = os.environ.copy()
    sub_env.pop("PYTHONPATH", None)
    edge_home = tmp_path / "edge_home"
    plugin_data = tmp_path / "plugin_data"
    edge_home.mkdir(parents=True, exist_ok=True)
    plugin_data.mkdir(parents=True, exist_ok=True)
    sub_env["PLUGIN_ROOT"] = str(REPO_ROOT)
    sub_env["EDGE_HOME"] = str(edge_home)
    sub_env["PLUGIN_DATA"] = str(plugin_data)
    return sub_env


# ---------------------------------------------------------------------------
# 1. pyproject.toml Packaging & Console Scripts
# ---------------------------------------------------------------------------


def test_pyproject_toml_scripts_uv_unmanaged_and_pytest_pythonpath() -> None:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    assert pyproject_path.is_file(), "Missing root pyproject.toml"

    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    assert data.get("build-system", {}).get("build-backend") == "setuptools.build_meta"

    proj = data.get("project", {})
    assert proj.get("name") == "edge-plugin"
    assert proj.get("dependencies") == []
    assert proj.get("requires-python")

    expected_scripts = {
        "brigade": "tools.brigade.cli:main",
        "edge-doctor": "tools.doctor.cli:main",
        "edge-drift": "tools.drift.cli:main",
        "edge-audit": "tools.audit.cli:main",
        "edge-tracker": "tools.tracker.cli:main",
        "edge-radar": "tools.radar.cli:main",
    }
    scripts = proj.get("scripts", {})
    for cmd_name, target in expected_scripts.items():
        assert scripts.get(cmd_name) == target, f"pyproject.toml missing script {cmd_name}={target}"
        mod_name, attr_name = target.split(":", 1)
        mod = importlib.import_module(mod_name)
        assert callable(getattr(mod, attr_name, None)), f"Script target {target} is not callable"

    tool_cfg = data.get("tool", {})
    find_cfg = tool_cfg.get("setuptools", {}).get("packages", {}).get("find", {})
    assert find_cfg.get("where") == ["."]
    assert "tools*" in (find_cfg.get("include") or [])

    pkg_data = tool_cfg.get("setuptools", {}).get("package-data", {})
    assert "station_models.json" in (pkg_data.get("tools.brigade") or [])

    assert tool_cfg.get("pytest", {}).get("ini_options", {}).get("pythonpath") == ["."]
    assert tool_cfg.get("uv", {}).get("managed") is False, "[tool.uv] managed = false is required"
    assert not (REPO_ROOT / ".venv").exists()
    assert not (REPO_ROOT / "uv.lock").exists()


# ---------------------------------------------------------------------------
# 2. bin/ Cross-OS Zero-Install Wrappers & .gitattributes
# ---------------------------------------------------------------------------


def test_posix_bin_wrappers_lf_executable_syntax_and_execution(tmp_path: Path) -> None:
    expected_targets = {
        "brigade": "tools.brigade.cli",
        "edge-doctor": "tools.doctor.cli",
    }
    for name, target_mod in expected_targets.items():
        wrapper = REPO_ROOT / "bin" / name
        assert wrapper.is_file(), f"Missing POSIX wrapper bin/{name}"
        raw = wrapper.read_bytes()
        assert b"\r" not in raw, f"bin/{name} must use LF-only line endings"
        text = raw.decode("utf-8")
        assert text.startswith("#!/usr/bin/env sh")
        assert target_mod in text
        assert "oguz" not in text.lower()

        if os.name == "posix":
            assert os.stat(wrapper).st_mode & stat.S_IXUSR, f"bin/{name} must be executable (chmod +x)"
            if shutil.which("sh"):
                syn = subprocess.run(["sh", "-n", str(wrapper)], capture_output=True, text=True)
                assert syn.returncode == 0, f"Invalid POSIX sh syntax in bin/{name}: {syn.stderr}"

            git_ls = subprocess.run(
                ["git", "ls-files", "--stage", "--", f"bin/{name}"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
            if git_ls.returncode == 0 and git_ls.stdout.strip():
                assert git_ls.stdout.strip().startswith("100755 "), f"git index mode for bin/{name} must be 100755"

    if os.name == "posix" and shutil.which("sh"):
        ext_cwd = tmp_path / "external_cwd"
        ext_cwd.mkdir()
        sub_env = _isolated_sub_env(tmp_path)

        proc_brig = subprocess.run(
            [str(REPO_ROOT / "bin" / "brigade"), "--help"],
            cwd=str(ext_cwd),
            env=sub_env,
            capture_output=True,
            text=True,
        )
        assert proc_brig.returncode == 0, proc_brig.stderr
        assert "brigade" in proc_brig.stdout.lower()

        proc_doc = subprocess.run(
            [str(REPO_ROOT / "bin" / "edge-doctor"), "--json"],
            cwd=str(ext_cwd),
            env=sub_env,
            capture_output=True,
            text=True,
        )
        assert proc_doc.returncode == 0, proc_doc.stderr
        parsed = json.loads(proc_doc.stdout.strip())
        assert parsed["hooks_health"]["ok"] is True


def test_windows_cmd_bin_wrappers_zero_goto_python_discovery_and_execution(tmp_path: Path) -> None:
    expected_targets = {
        "brigade.cmd": "tools.brigade.cli",
        "edge-doctor.cmd": "tools.doctor.cli",
    }
    for name, target_mod in expected_targets.items():
        wrapper = REPO_ROOT / "bin" / name
        assert wrapper.is_file(), f"Missing Windows wrapper bin/{name}"
        text = wrapper.read_text(encoding="utf-8")
        low = text.lower()

        assert not re.search(r"(?im)^\s*goto\b", text), f"bin/{name} must not use goto"
        assert not re.search(r"(?m)^:[A-Za-z_]", text), f"bin/{name} must have zero batch labels"
        assert "oguz" not in low and "wsl" not in low
        assert target_mod in text
        for token in ("python_exe.txt", "cpython-3.1", "python3", "python", "py -3", "uv run --no-project --offline python"):
            assert token in low, f"bin/{name} missing Python discovery token {token!r}"

    if os.name == "nt":
        ext_cwd = tmp_path / "external_cwd"
        ext_cwd.mkdir()
        sub_env = _isolated_sub_env(tmp_path)

        proc_brig = subprocess.run(
            ["cmd", "/c", str(REPO_ROOT / "bin" / "brigade.cmd"), "--help"],
            cwd=str(ext_cwd),
            env=sub_env,
            capture_output=True,
            text=True,
        )
        assert proc_brig.returncode == 0, proc_brig.stderr
        assert "brigade" in proc_brig.stdout.lower()

        proc_doc = subprocess.run(
            ["cmd", "/c", str(REPO_ROOT / "bin" / "edge-doctor.cmd"), "--json"],
            cwd=str(ext_cwd),
            env=sub_env,
            capture_output=True,
            text=True,
        )
        assert proc_doc.returncode == 0, proc_doc.stderr
        parsed = json.loads(proc_doc.stdout.strip())
        assert parsed["hooks_health"]["ok"] is True


def test_gitattributes_enforces_cross_os_line_endings() -> None:
    attr_path = REPO_ROOT / ".gitattributes"
    assert attr_path.is_file()
    lines = {" ".join(ln.strip().split()) for ln in attr_path.read_text(encoding="utf-8").splitlines() if ln.strip()}
    for required in (
        "hooks/dispatch.cmd text eol=lf",
        "bin/brigade text eol=lf",
        "bin/edge-doctor text eol=lf",
        "bin/*.cmd text eol=crlf",
        "*.sh text eol=lf",
    ):
        assert required in lines, f".gitattributes missing {required!r}"


# ---------------------------------------------------------------------------
# 3. tools/doctor/checks.py Cross-OS Fallback Capability Matrix
# ---------------------------------------------------------------------------


def test_doctor_checks_cross_os_fallback_matrix() -> None:
    models = importlib.import_module("tools.doctor.models")
    checks = importlib.import_module("tools.doctor.checks")

    assert "npx" in checks.PROBE_BINARIES

    # 1. Lite (python + git only): isolated_worktrees is native via git worktree;
    #    visual_gate mentions HTML artifact fallback; browser_qa mentions browser + chrome-devtools-mcp
    lite_caps, lite_profile = checks.build_capability_matrix(_make_probes(models, ("python", "git")))
    assert lite_profile == "lite"
    by_name = {c.name: c for c in lite_caps}

    assert by_name["isolated_worktrees"].status == "native"
    assert "git" in by_name["isolated_worktrees"].detail.lower()

    assert by_name["visual_gate"].status == "passive"
    assert "artifact" in by_name["visual_gate"].detail.lower() or "html" in by_name["visual_gate"].detail.lower()

    assert by_name["browser_qa"].status == "passive"
    assert "browser" in by_name["browser_qa"].detail.lower()
    assert "chrome-devtools-mcp" in by_name["browser_qa"].detail.lower()

    # 2. npx available (without lavish-axi) -> visual_gate passive with npx fallback detail
    npx_caps, _ = checks.build_capability_matrix(_make_probes(models, ("python", "git", "node", "npx")))
    npx_by_name = {c.name: c for c in npx_caps}
    assert npx_by_name["visual_gate"].status == "passive"
    assert "npx" in npx_by_name["visual_gate"].detail.lower()

    # 3. Full toolchain + treehouse -> isolated_worktrees native (treehouse), visual_gate native, browser_qa native
    full_caps, full_profile = checks.build_capability_matrix(
        _make_probes(
            models,
            ("python", "git", "uv", "node", "gh", "gh-axi", "treehouse", "lavish-axi", "chrome-devtools-axi"),
        )
    )
    assert full_profile == "full"
    full_by_name = {c.name: c for c in full_caps}
    assert full_by_name["isolated_worktrees"].status == "native"
    assert "treehouse" in full_by_name["isolated_worktrees"].detail.lower()
    assert full_by_name["visual_gate"].status == "native"
    assert full_by_name["browser_qa"].status == "native"

    # 4. Missing both treehouse and git -> isolated_worktrees unavailable
    nogit_caps, _ = checks.build_capability_matrix(_make_probes(models, ("python",)))
    assert {c.name: c for c in nogit_caps}["isolated_worktrees"].status == "unavailable"


# ---------------------------------------------------------------------------
# 4. Smoke-Verified README.md & Phase 0 Ontology Alignment
# ---------------------------------------------------------------------------


def test_root_readme_smoke_verified_cross_os_guides_and_fallback_matrix() -> None:
    readme_path = REPO_ROOT / "README.md"
    assert readme_path.is_file()
    text = readme_path.read_text(encoding="utf-8")
    low = text.lower()

    assert "oguz" not in low
    assert "c:/users/oguz" not in low and "c:\\users\\oguz" not in low

    for token in (
        "winget",
        "git.git",
        "python.python.3.12",
        "github.cli",
        "openjs.nodejs",
        "lavish-axi",
        "brew install",
        "apt-get",
        "uv run --no-project",
        "tools/doctor/cli.py --init",
        "bin/brigade",
        "bin\\brigade.cmd",
        "-e .",
        "treehouse",
        "git worktree",
        "spec_critic",
        "npx",
        "chrome-devtools-axi",
        "chrome-devtools-mcp",
        "browser",
    ):
        assert token in low, f"README.md missing Slice 3 smoke-verified token {token!r}"


def test_slice3_ontology_alignment_and_ast_symbol_binding() -> None:
    from tools.drift.models import matches_tracked_paths, parse_canonical_domain_doc, parse_context_glossary
    from tools.drift.scanner import validate_ontology

    context_text = (REPO_ROOT / "CONTEXT.md").read_text(encoding="utf-8-sig")
    context_globs, context_concepts = parse_context_glossary(context_text)

    # 1. Domain Map owns Slice 3 modules, bin/**, and pyproject.toml under brigade
    assert matches_tracked_paths(
        [
            "tools/brigade/worktree_git.py",
            "tools/brigade/prototype.py",
            "bin/brigade",
            "pyproject.toml",
        ],
        context_globs["brigade"],
    ) == [
        "tools/brigade/worktree_git.py",
        "tools/brigade/prototype.py",
        "bin/brigade",
        "pyproject.toml",
    ]

    # 2. Closed Concept Glossary binds all 4 Slice 3 concepts strictly to AST-verified .py symbols
    glossary_rows = _extract_glossary_rows(context_text)
    expected_bindings = {
        "native-worktree-fallback": (
            ("acquire_git_worktree", "return_git_worktree", "prune_git_worktrees"),
            ("tools/brigade/worktree_git.py",),
        ),
        "native-station-critic": (
            ("build_spec_critic_dispatch", "resolve_subagent_model"),
            ("tools/brigade/station_dispatch.py", "tools/brigade/tier_ssot.py"),
        ),
        "cross-os-visual-bridge": (
            ("execute_prototype_action", "read_lavish_sessions"),
            ("tools/brigade/prototype.py",),
        ),
        "cross-os-cli-entrypoints": (
            ("main",),
            ("tools/brigade/cli.py", "tools/doctor/cli.py"),
        ),
    }

    for concept, (req_syms, req_files) in expected_bindings.items():
        assert concept in context_concepts, f"CONTEXT.md missing concept {concept!r}"
        assert concept in glossary_rows, f"CONTEXT.md missing glossary table row for {concept!r}"
        sym_col, _ = glossary_rows[concept]
        cited_files = re.findall(r"tools/[a-zA-Z0-9_/]+\.py", sym_col)
        assert cited_files, f"Glossary row {concept!r} must cite .py file paths"
        for rf in req_files:
            assert rf in cited_files, f"Glossary row {concept!r} missing file {rf}"
        pool: Set[str] = set()
        for rel_file in cited_files:
            py_file = REPO_ROOT / rel_file
            assert py_file.is_file(), f"Glossary row {concept!r} cites missing file {rel_file}"
            pool.update(_ast_top_level_symbols(py_file))
        for sym in req_syms:
            assert sym in sym_col, f"Glossary row {concept!r} missing symbol {sym!r}"
            assert sym in pool, f"Symbol {sym!r} not found in AST of {cited_files}"

    # 3. DOMAIN.md documents register concepts & invariants/patterns cleanly (code-free)
    brigade_doc = parse_canonical_domain_doc(
        (REPO_ROOT / "docs" / "brigade" / "DOMAIN.md").read_text(encoding="utf-8-sig"),
        doc_path="docs/brigade/DOMAIN.md",
        fallback_domain="brigade",
    )
    assert {"native-worktree-fallback", "cross-os-visual-bridge", "cross-os-cli-entrypoints"}.issubset(
        set(brigade_doc.concepts)
    )
    assert "INV-BRIGADE-WORKTREE-CLEANUP" in brigade_doc.invariant_ids
    assert "PAT-BRIGADE-NATIVE-FALLBACKS" in brigade_doc.pattern_ids

    orch_doc = parse_canonical_domain_doc(
        (REPO_ROOT / "docs" / "orchestration" / "DOMAIN.md").read_text(encoding="utf-8-sig"),
        doc_path="docs/orchestration/DOMAIN.md",
        fallback_domain="orchestration",
    )
    assert "native-station-critic" in orch_doc.concepts
    assert "PAT-ORCH-NATIVE-DISPATCH" in orch_doc.pattern_ids

    # 4. Zero ontology errors and zero warnings
    report = validate_ontology(REPO_ROOT)
    assert not report.skipped
    assert not report.has_errors, f"Ontology errors: {report.issues}"
    assert report.issues == [], f"Ontology issues found: {report.issues}"
