"""Integration & contract tests for Slice 2.3: Stack Profile Gating across Core Tools."""

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools import rules as rules_mod
from tools.brigade import qa_fiber, ship_prep
from tools.brigade.orchestrator_guard import _is_schema_target
from tools.brigade.stations import StationRegistry
from tools.gate import EdgeVerificationGate
from tools.test_audit import cli as test_audit_cli
from tools.ui_audit.graph_builder import GraphBuilder


def _git(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"


def _init_git_repo(repo: Path, files: dict[str, str]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    for rel, content in files.items():
        fp = repo / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore: initial commit")


def _commit_files(repo: Path, files: dict[str, str], msg: str) -> None:
    for rel, content in files.items():
        fp = repo / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", msg)


def _stage_map(payload: dict) -> dict[str, dict]:
    return {s["name"]: s for s in payload["stages"]}


def test_edge_repo_pure_core_skips_stack_gates() -> None:
    gate = EdgeVerificationGate(ROOT_DIR)
    payload = gate.run_all_structured(base_ref="HEAD", is_refactor=True, skip_verification=False, track="all")
    stages = _stage_map(payload)

    for skipped_stage in (
        "MigrationGate Invariant Gate",
        "Type Escape Gate",
        "Dual-Theme & A11y Heuristic Gate",
        "Layer Leakage Gate",
        "Zero-Wrapper Gate",
        "Domain Purity Gate",
        "Hermetic Verification Gate",
    ):
        assert stages[skipped_stage]["passed"] is True
        assert stages[skipped_stage]["message"] == "Skipped (inactive profile)"


def test_typescript_profile_enforces_ts_only_and_skips_nextjs_gates(tmp_path: Path) -> None:
    repo = tmp_path / "ts-only"
    _init_git_repo(repo, {"tsconfig.json": "{}\n", "src/core/calc.ts": "export const add = (a: number, b: number) => a + b;\n"})
    _commit_files(
        repo,
        {
            "src/core/calc.ts": "export const add = (a: any, b: number) => a + b;\n",
            "src/db/schema/users.ts": "export const users = {};\n",
        },
        "feat: add ts escape and schema file",
    )

    payload = EdgeVerificationGate(repo).run_all_structured(base_ref="HEAD~1", is_refactor=True, skip_verification=True, track="all")
    stages = _stage_map(payload)

    assert payload["all_passed"] is False
    assert stages["Type Escape Gate"]["passed"] is False
    assert stages["MigrationGate Invariant Gate"]["message"] == "Skipped (inactive profile)"
    assert stages["Layer Leakage Gate"]["message"] == "Skipped (inactive profile)"
    assert stages["Dual-Theme & A11y Heuristic Gate"]["message"] == "Skipped (inactive profile)"
    assert stages["Zero-Wrapper Gate"]["message"] == "Skipped (inactive profile)"
    assert stages["Domain Purity Gate"]["message"] == "Skipped (inactive profile)"


def test_nextjs_profile_enforces_all_stack_gates(tmp_path: Path) -> None:
    repo = tmp_path / "nextjs-app"
    _init_git_repo(
        repo,
        {
            "next.config.ts": "export default {};\n",
            "src/actions/booking.ts": "export async function ok() { return true; }\n",
            "src/components/Card.tsx": "export function Card() { return <div className=\"bg-white dark:bg-slate-900\" />; }\n",
        },
    )
    _commit_files(
        repo,
        {
            "src/db/schema/bookings.ts": "export const bookings = {};\n",
            "src/actions/booking.ts": "export async function bad() { return db.select(); }\n",
            "src/components/Card.tsx": "export function Card() { return <div className=\"bg-white\" />; }\n",
        },
        "feat: introduce stack violations",
    )

    payload = EdgeVerificationGate(repo).run_all_structured(base_ref="HEAD~1", is_refactor=True, skip_verification=True, track="all")
    stages = _stage_map(payload)

    assert payload["all_passed"] is False
    assert stages["MigrationGate Invariant Gate"]["passed"] is False
    assert stages["Layer Leakage Gate"]["passed"] is False
    assert stages["Dual-Theme & A11y Heuristic Gate"]["passed"] is False


def test_station_registry_3_layer_rubric_composition(tmp_path: Path) -> None:
    pure_repo = tmp_path / "pure"
    pure_repo.mkdir()
    pure_rubric = StationRegistry.load_station_rubric("coder", pure_repo)
    assert "## STACK PROFILE OVERLAY" not in pure_rubric
    assert "disabled={isPending}" not in pure_rubric

    ts_repo = tmp_path / "ts"
    ts_repo.mkdir()
    (ts_repo / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    ts_rubric = StationRegistry.load_station_rubric("coder", ts_repo)
    assert "## STACK PROFILE OVERLAY (typescript)" in ts_rubric
    assert "## STACK PROFILE OVERLAY (nextjs-drizzle-tailwind)" not in ts_rubric
    assert "npx tsc --noEmit" in ts_rubric
    assert "disabled={isPending}" not in ts_rubric

    next_repo = tmp_path / "next"
    (next_repo / ".edge" / "stations").mkdir(parents=True)
    (next_repo / "next.config.ts").write_text("export default {};\n", encoding="utf-8")
    (next_repo / ".edge" / "stations" / "coder.md").write_text("Custom local coder invariant\n", encoding="utf-8")
    next_rubric = StationRegistry.load_station_rubric("coder", next_repo)
    idx_ts = next_rubric.index("## STACK PROFILE OVERLAY (typescript)")
    idx_next = next_rubric.index("## STACK PROFILE OVERLAY (nextjs-drizzle-tailwind)")
    idx_local = next_rubric.index("## REPOSITORY-LOCAL STATION OVERLAY")
    assert idx_ts < idx_next < idx_local
    assert "disabled={isPending}" in next_rubric
    assert "Custom local coder invariant" in next_rubric


def test_ship_prep_stage_branches_and_rule_packs(tmp_path: Path) -> None:
    ts_repo = tmp_path / "ts-ship"
    ts_repo.mkdir()
    (ts_repo / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    assert ship_prep.resolve_stage_branches(ts_repo)["integration"] == "main"

    next_repo = tmp_path / "next-ship"
    next_repo.mkdir()
    (next_repo / "next.config.ts").write_text("export default {};\n", encoding="utf-8")
    next_stages = ship_prep.resolve_stage_branches(next_repo)
    assert next_stages["integration"] == "development"
    assert next_stages["staging"] == "staging"

    assert "core" in rules_mod.RULE_PACKS
    assert "typescript" in rules_mod.RULE_PACKS
    assert "nextjs-drizzle-tailwind" in rules_mod.RULE_PACKS
    assert hasattr(rules_mod, "SQL_LEAK_PATTERN")
    assert hasattr(rules_mod, "TYPE_ESCAPE_PATTERN")


def test_other_tools_profile_gating_and_guard_stdlib_only(tmp_path: Path) -> None:
    # 1. ui_audit skips when explicit typescript profile
    ts_repo = tmp_path / "ts-ui"
    (ts_repo / ".edge").mkdir(parents=True)
    (ts_repo / ".edge" / "profile.json").write_text(json.dumps({"profile": "typescript"}), encoding="utf-8")
    (ts_repo / "src" / "components").mkdir(parents=True)
    (ts_repo / "src" / "components" / "Btn.tsx").write_text("export const Btn = () => <button />;\n", encoding="utf-8")
    assert GraphBuilder(ts_repo).scan_files() == []

    # 2. test_audit skips SERVER_ACTION_IMPORT under explicit typescript profile
    unit_test = ts_repo / "tests" / "unit" / "sample.test.ts"
    unit_test.parent.mkdir(parents=True)
    unit_test.write_text('import { x } from "@/actions/booking";\n', encoding="utf-8")
    res = test_audit_cli.TestFileAuditor(ts_repo).analyze_file(unit_test)
    assert all(v["rule"] != "SERVER_ACTION_IMPORT" for v in res["violations"])

    # 3. qa_fiber skips cleanly on explicit none
    none_repo = tmp_path / "none-repo"
    (none_repo / ".edge").mkdir(parents=True)
    (none_repo / ".edge" / "profile.json").write_text(json.dumps({"profile": "none"}), encoding="utf-8")
    fiber_res = qa_fiber.inspect_fiber("button", repo_path_str=str(none_repo))
    assert fiber_res["skipped"] is True

    # 4. orchestrator_guard skips drizzle lock when explicit typescript without migration_globs
    assert _is_schema_target(str(ts_repo / "drizzle" / "0001.sql")) is False
    # And stays stdlib-only at module top-level
    guard_src = ROOT_DIR / "tools" / "brigade" / "orchestrator_guard.py"
    tree = ast.parse(guard_src.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in sys.stdlib_module_names
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if not node.module.startswith("tools.brigade.guard"):
                assert node.module.split(".")[0] in sys.stdlib_module_names