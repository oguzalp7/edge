#!/usr/bin/env python3
"""
Hermetic RED Contract Tests for Session 3 — Slice 2 (Sections 2.1, 2.2, 2.4):
- resolve_subagent_model in tier_ssot.py / tier.py + station_selector.py Model normalization
- Native SPEC_CRITIC station dispatch (build_subagent_dispatch_directive, build_spec_critic_dispatch)
- run_spec_critique(..., native=True) & missing-agy fallback + CLI --native / --json
- Cross-OS Browser QA fallback (qa_fiber_js.py + Windows .cmd unwrap + guards_visual.py python)
- Cross-OS Rules, Skills, and UI Audit Markdown Reporter alignment
"""

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _isolate_tier_and_guard_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep tier state and Antigravity station registries isolated inside tmp_path."""
    agy_dir = tmp_path / "antigravity"
    agy_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EDGE_TIER_STATE_PATH", str(agy_dir / "edge_tier.json"))
    monkeypatch.setenv("EDGE_ANTIGRAVITY_DIR", str(agy_dir))
    monkeypatch.setenv("EDGE_ACTIVE_STATIONS_FILE", str(agy_dir / "edge_active_stations.json"))
    monkeypatch.setenv("EDGE_ACTIVE_SESSIONS_DIR", str(agy_dir / "edge_active_sessions"))


# ---------------------------------------------------------------------------
# 1. resolve_subagent_model & station_selector Model Normalization
# ---------------------------------------------------------------------------


def test_resolve_subagent_model_mapping_and_pro_ssot_preserved() -> None:
    tier_ssot = importlib.import_module("tools.brigade.tier_ssot")
    tier_mod = importlib.import_module("tools.brigade.tier")
    tier_models = importlib.import_module("tools.brigade.tier_models")

    resolve_fn = getattr(tier_ssot, "resolve_subagent_model", None)
    assert callable(resolve_fn), "tools.brigade.tier_ssot must define resolve_subagent_model"
    assert getattr(tier_mod, "resolve_subagent_model", None) is resolve_fn

    valid_enum = {"inherit", "flash", "flash_lite", "pro"}
    for direct in valid_enum:
        assert resolve_fn(direct) == direct

    assert resolve_fn("claude-opus-5-5-high") == "pro"
    assert resolve_fn("gemini-4-hydrogen-xhigh") == "pro"
    assert resolve_fn("gemini-4-hydrogen-high") == "pro"
    assert resolve_fn("gemini-3.8-flash-high") == "flash"
    assert resolve_fn("gemini-2.5-flash-lite") == "flash_lite"
    assert resolve_fn("unknown-model-x") == "flash"
    assert resolve_fn("") == "flash"

    # Existing Pro SSOT contract MUST stay untouched (test_tier_switch & test_brigade)
    assert tier_models.PRO_STATION_MODELS["spec_critic"] == "gemini-3.8-flash-high"
    ssot_json = json.loads((REPO_ROOT / "tools" / "brigade" / "station_models.json").read_text(encoding="utf-8"))
    assert ssot_json["tiers"]["pro"]["stations"]["spec_critic"]["model"] == "gemini-3.8-flash-high"


def test_station_selector_normalizes_missing_or_non_enum_subagent_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selector = importlib.import_module("tools.brigade.guard.station_selector")
    monkeypatch.setattr(
        selector,
        "effective_stations_file",
        lambda: tmp_path / "antigravity" / "edge_active_stations.json",
    )

    valid_enum = {"inherit", "flash", "flash_lite", "pro"}

    # Missing Model -> preloads normalized enum for canonical station
    res_missing = selector._handle_invoke_subagent_guard(
        {"TypeName": "self", "Role": "Spec Critic", "Prompt": "Audit slice spec"},
        "orch-parent-1",
    )
    assert res_missing["decision"] == "allow"
    over_missing = res_missing.get("overwrite", {})
    assert over_missing.get("Model") in valid_enum

    # Non-enum Model (e.g. gemini-3.8-flash-high or claude-opus-5-5-high) -> normalized into enum
    res_non_enum = selector._handle_invoke_subagent_guard(
        {
            "TypeName": "self",
            "Role": "Spec Critic",
            "Model": "claude-opus-5-5-high",
            "Prompt": "Audit slice spec",
        },
        "orch-parent-2",
    )
    assert res_non_enum["decision"] == "allow"
    over_non_enum = res_non_enum.get("overwrite", {})
    assert over_non_enum.get("Model") in valid_enum


# ---------------------------------------------------------------------------
# 2. Native SPEC_CRITIC Station Dispatch (Ultra Swarm vs Pro Subagent)
# ---------------------------------------------------------------------------


def test_build_subagent_and_spec_critic_dispatch_directives(tmp_path: Path) -> None:
    dispatch_mod = importlib.import_module("tools.brigade.station_dispatch")
    build_subagent = getattr(dispatch_mod, "build_subagent_dispatch_directive", None)
    build_critic = getattr(dispatch_mod, "build_spec_critic_dispatch", None)
    assert callable(build_subagent), "station_dispatch.py must define build_subagent_dispatch_directive"
    assert callable(build_critic), "station_dispatch.py must define build_spec_critic_dispatch"

    repo = tmp_path / "repo"
    spec_file = repo / ".edge" / "specs" / "auth-flow.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("# Auth Flow Spec\n", encoding="utf-8")

    # 1. build_subagent_dispatch_directive resolves native model enum cleanly
    sub_pro = build_subagent("spec_critic", "Review spec", model="claude-opus-5-5-high")
    assert sub_pro["tool"] == "invoke_subagent"
    assert sub_pro["TypeName"] == "self"
    assert sub_pro["Model"] == "pro"
    assert sub_pro["Role"] == "Spec Critic"
    assert sub_pro["Prompt"] == "Review spec"

    sub_default = build_subagent("spec_critic", "Review spec")
    assert sub_default["Model"] in {"flash", "pro"}

    # 2. Ultra tier -> native_swarm directive (swarm add spec_critic with claude-opus-5-5-high)
    mode_u, dir_u, prompt_u = build_critic(repo, spec_file, "Full critique prompt", tier="ultra", issue_number=77)
    assert mode_u == "native_swarm"
    assert dir_u["action"] == "add"
    assert dir_u["name"] == "spec_critic"
    assert dir_u["model"] == "claude-opus-5-5-high"
    assert prompt_u.is_file()
    assert prompt_u == repo / ".edge" / "cache" / "issues" / "77-critic-prompt.md"
    assert "Full critique prompt" in prompt_u.read_text(encoding="utf-8")

    # 3. Pro tier -> native_subagent directive (invoke_subagent with native enum)
    mode_p, dir_p, prompt_p = build_critic(repo, spec_file, "Pro critique prompt", tier="pro")
    assert mode_p == "native_subagent"
    assert dir_p["tool"] == "invoke_subagent"
    assert dir_p["TypeName"] == "self"
    assert dir_p["Role"] == "Spec Critic"
    assert dir_p["Model"] in {"flash", "pro"}
    assert prompt_p.is_file()
    assert prompt_p == repo / ".edge" / "specs" / "auth-flow-critic-prompt.md"


def test_run_spec_critique_native_flag_missing_agy_fallback_and_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sc_mod = importlib.import_module("tools.brigade.spec_critic")
    tier_mod = importlib.import_module("tools.brigade.tier")

    repo = tmp_path / "repo"
    spec_file = repo / "docs" / "slice.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("# Feature Slice\nAdd billing receipts.", encoding="utf-8")

    # SpecCritiqueResult preserves defaulted fields
    base_res = sc_mod.SpecCritiqueResult(
        success=True,
        model_used="claude-opus-5-5-high",
        fallback_triggered=False,
        report_path="",
        summary="ok",
    )
    assert base_res.dispatch_mode == "cli"
    assert base_res.dispatch_directive is None

    # 1. Explicit native=True skips agy CLI completely and returns native_subagent (Pro) or native_swarm (Ultra)
    monkeypatch.setattr(
        sc_mod,
        "run_command",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("agy CLI must not run when native=True")),
    )
    state_path = Path(os.environ["EDGE_TIER_STATE_PATH"])
    tier_mod.atomic_write_json(
        state_path,
        tier_mod.create_tier_state("ultra", "main").to_dict(),
    )

    res_ultra = sc_mod.run_spec_critique(repo, spec_file, native=True)
    assert res_ultra.success is True
    assert res_ultra.dispatch_mode == "native_swarm"
    assert isinstance(res_ultra.dispatch_directive, dict)
    assert res_ultra.dispatch_directive.get("name") == "spec_critic"

    # Switch to Pro tier -> native_subagent
    tier_mod.atomic_write_json(
        state_path,
        tier_mod.create_tier_state("pro", "main").to_dict(),
    )
    res_pro = sc_mod.run_spec_critique(repo, spec_file, native=True)
    assert res_pro.success is True
    assert res_pro.dispatch_mode == "native_subagent"
    assert isinstance(res_pro.dispatch_directive, dict)
    assert res_pro.dispatch_directive.get("Model") in {"flash", "pro"}

    # 2. Missing agy binary fallback when native=False & shutil.which("agy") is None
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "agy" else "/usr/bin/git")
    monkeypatch.setattr(sc_mod, "run_command", lambda *a, **kw: (127, "", "agy: command not found"))
    res_missing_agy = sc_mod.run_spec_critique(repo, spec_file)
    assert res_missing_agy.success is True
    assert res_missing_agy.dispatch_mode == "native_subagent"
    assert isinstance(res_missing_agy.dispatch_directive, dict)

    # 3. Non-missing-binary error (e.g. Fatal: model unavailable) STILL fails cleanly even when agy not on PATH
    monkeypatch.setattr(
        sc_mod,
        "run_command",
        lambda *a, **kw: (1, "", "Fatal: model unavailable"),
    )
    res_model_err = sc_mod.run_spec_critique(repo, spec_file)
    assert res_model_err.success is False
    assert "model unavailable" in (res_model_err.error or "")

    # 4. CLI wiring: brigade critique-spec --native --json and --dispatch
    parser = importlib.import_module("tools.brigade.cli_ops.parser").build_parser()
    parsed_nat = parser.parse_args(["critique-spec", str(repo), "--spec", str(spec_file), "--native", "--json"])
    assert parsed_nat.native is True and parsed_nat.json is True
    parsed_disp = parser.parse_args(["critique-spec", str(repo), "--spec", str(spec_file), "--dispatch"])
    assert parsed_disp.native is True

    brigade_cli = importlib.import_module("tools.brigade.cli")
    monkeypatch.setattr(
        sys,
        "argv",
        ["brigade", "critique-spec", str(repo), "--spec", str(spec_file), "--native", "--json"],
    )
    capsys.readouterr()
    rc = brigade_cli.main()
    out = capsys.readouterr().out.strip()
    assert rc == 0, out
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["dispatch_mode"] == "native_subagent"
    assert isinstance(payload["dispatch_directive"], dict)


# ---------------------------------------------------------------------------
# 3. Cross-OS Browser QA (qa_fiber_js.py & guards_visual.py)
# ---------------------------------------------------------------------------


def test_qa_fiber_execute_browser_eval_cmd_unwrap_alias_and_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qa_js = importlib.import_module("tools.brigade.qa_fiber_js")

    # 1. Missing both binaries -> structured fallback dict instead of raw error/crash
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    def raise_not_found(*_args, **_kwargs):
        raise FileNotFoundError("No such file or directory: 'chrome-devtools-axi'")

    monkeypatch.setattr(subprocess, "run", raise_not_found)
    fallback_res = qa_js.execute_browser_eval("(() => 1 && 2)()")
    assert fallback_res is not None
    assert fallback_res["error"] == "CHROME_DEVTOOLS_AXI_UNAVAILABLE"
    assert fallback_res["fallback"] == "chrome-devtools-mcp"
    assert fallback_res["alternative"] == "browser_subagent"
    assert "1 && 2" in fallback_res["js_snippet"]
    assert "evaluate_script" in fallback_res.get("instruction", "")

    # 2. Alias chrome-dev-tools-axi & Windows .cmd shim unwrapped to direct node.exe call (shell=False)
    bin_dir = tmp_path / "npm"
    js_entry = bin_dir / "node_modules" / "chrome-devtools-axi" / "dist" / "cli.js"
    js_entry.parent.mkdir(parents=True, exist_ok=True)
    js_entry.write_text("console.log('ok');\n", encoding="utf-8")
    node_exe = bin_dir / "node.exe"
    node_exe.write_text("node", encoding="utf-8")
    cmd_shim = bin_dir / "chrome-dev-tools-axi.cmd"
    cmd_shim.write_text(
        '@echo off\r\n"%~dp0\\node.exe" "%~dp0\\node_modules\\chrome-devtools-axi\\dist\\cli.js" %*\r\n',
        encoding="utf-8",
    )

    with monkeypatch.context() as mp:
        mp.setattr(os, "name", "nt")
        mp.setattr(
            shutil,
            "which",
            lambda name: str(cmd_shim) if name == "chrome-dev-tools-axi" else (str(node_exe) if name == "node" else None),
        )

        seen: List[Dict[str, Any]] = []

        def fake_run(cmd, **kwargs):
            seen.append({"cmd": cmd, "kwargs": kwargs})
            return subprocess.CompletedProcess(cmd, 0, 'result: {"success": true, "tag": "BUTTON"}\n', "")

        mp.setattr(subprocess, "run", fake_run)
        js_with_meta = "(() => a && b | c > 0 ^ 1 % 2)()"
        ok_res = qa_js.execute_browser_eval(js_with_meta)
        assert ok_res == {"success": True, "tag": "BUTTON"}
        assert len(seen) == 1
        assert isinstance(seen[0]["cmd"], list)
        assert not seen[0]["kwargs"].get("shell", False)
        assert os.path.normcase(os.path.realpath(seen[0]["cmd"][0])) == os.path.normcase(os.path.realpath(str(node_exe)))
        assert seen[0]["cmd"][-2:] == ["eval", js_with_meta]


def test_guards_visual_uses_portable_python_not_python3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fsm_mod = importlib.import_module("tools.brigade.fsm")
    repo = tmp_path / "repo"
    repo.mkdir()
    fsm = fsm_mod.BrigadeFSM(repo)

    captured_cmds: List[List[str]] = []
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(
        fsm,
        "_run_cmd",
        lambda cmd, cwd=None, timeout=None: (captured_cmds.append(list(cmd)) or (0, "ok", "")),
    )

    baseline = tmp_path / "base.png"
    refactored = tmp_path / "ref.png"
    diff_out = tmp_path / "diff.png"
    ok, _, _ = fsm._run_diff_image_subprocess(baseline, refactored, diff_out)
    assert ok is True
    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert "python" in cmd
    assert "python3" not in cmd


# ---------------------------------------------------------------------------
# 4. Rules, Skills & UI Audit Reporter Cross-OS Documentation Contracts
# ---------------------------------------------------------------------------


def test_rules_skills_and_ui_reporter_document_slice2_fallbacks() -> None:
    # 1. rules/AGENTS.md §1C
    agents_text = (REPO_ROOT / "rules" / "AGENTS.md").read_text(encoding="utf-8")
    sec1c_match = re.search(r"###\s+.*?C\.(.*?)(?=\n---|\n##\s)", agents_text, re.DOTALL)
    assert sec1c_match is not None, "Missing Section 1C in rules/AGENTS.md"
    sec1c = sec1c_match.group(1).lower()
    assert "browser" in sec1c, "rules/AGENTS.md §1C must document built-in browser subagent"
    assert "chrome-devtools-mcp" in sec1c
    assert "chrome-devtools-axi" in sec1c or "chrome-dev-tools-axi" in sec1c
    assert "linux/wsl ortamında" not in sec1c

    # 2. skills/edge-orchestrator/SKILL.md
    orch_text = (REPO_ROOT / "skills" / "edge-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
    orch_low = orch_text.lower()
    assert "npx" in orch_low
    assert "chrome-devtools-mcp" in orch_low
    assert "chrome-devtools-axi" in orch_low or "chrome-dev-tools-axi" in orch_low
    assert "--native" in orch_text or ("spec_critic" in orch_low and "swarm" in orch_low)

    # 3. skills/edge-brigade/SKILL.md
    brigade_text = (REPO_ROOT / "skills" / "edge-brigade" / "SKILL.md").read_text(encoding="utf-8")
    brigade_low = brigade_text.lower()
    assert "--native" in brigade_text or "native_swarm" in brigade_low
    assert "npx" in brigade_low
    assert "chrome-devtools-axi" in brigade_low
    assert "chrome-devtools-mcp" in brigade_low
    assert "browser" in brigade_low

    # 4. skills/edge-ui-audit/SKILL.md
    ui_audit_text = (REPO_ROOT / "skills" / "edge-ui-audit" / "SKILL.md").read_text(encoding="utf-8")
    ui_audit_low = ui_audit_text.lower()
    assert "/usr/local/bin/chrome-devtools-axi" not in ui_audit_text
    assert "chrome-devtools-axi" in ui_audit_low
    assert "chrome-devtools-mcp" in ui_audit_low
    assert "browser" in ui_audit_low

    # 5. skills/edge-ui-refactor/SKILL.md
    ui_ref_text = (REPO_ROOT / "skills" / "edge-ui-refactor" / "SKILL.md").read_text(encoding="utf-8")
    ui_ref_low = ui_ref_text.lower()
    assert "chrome-devtools-axi" in ui_ref_low
    assert "chrome-devtools-mcp" in ui_ref_low
    assert "browser" in ui_ref_low

    # 6. tools/ui_audit/reporter_markdown.py
    rep_text = (REPO_ROOT / "tools" / "ui_audit" / "reporter_markdown.py").read_text(encoding="utf-8")
    rep_low = rep_text.lower()
    assert "chrome-devtools-axi" in rep_low
    assert "chrome-devtools-mcp" in rep_low or "browser" in rep_low
