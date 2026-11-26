"""
RED unit, contract, and subprocess guard tests for Slice 2.1:
Stdlib-only Stack Profile Loader (`tools.common.profiles`) & Line Budget Enforcement.

Note on seam: `resolve_active_profiles(repo_root, profiles_dir=...)` accepts an
optional `profiles_dir` override (defaulting to `<plugin_root>/profiles`) so all
tests remain 100% hermetic before and after `profiles/` assets exist on disk.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _profiles_api():
    from tools.common.profiles import (
        ProfileResolutionError,
        ResolvedProfileSet,
        StackProfile,
        has_profile_capability,
        is_stack_gate_enabled,
        load_profile_station_overlays,
        resolve_active_profiles,
    )

    return (
        StackProfile,
        ResolvedProfileSet,
        ProfileResolutionError,
        resolve_active_profiles,
        has_profile_capability,
        is_stack_gate_enabled,
        load_profile_station_overlays,
    )


def _write_json(path: Path, payload: Dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _build_fixture_profiles(profiles_dir: Path) -> Path:
    _write_json(
        profiles_dir / "typescript" / "profile.json",
        {
            "schema_version": 1,
            "id": "typescript",
            "name": "TypeScript Base",
            "description": "Clean TypeScript profile without Next.js, Drizzle, Tailwind, or Coolify.",
            "extends": [],
            "detect": {
                "any_files": ["tsconfig.json"],
                "all_files": [],
                "package_json_deps": ["typescript"],
            },
            "capabilities": ["typescript", "vitest"],
            "paths": {
                "source_roots": ["src/"],
                "action_globs": [],
                "schema_globs": [],
                "migration_globs": [],
                "ui_globs": [],
                "test_globs": ["tests/**", "**/*.test.ts*", "**/*.spec.ts*"],
            },
            "commands": {
                "typecheck": ["npx", "tsc", "--noEmit"],
                "unit_test": ["npm", "run", "test:unit"],
            },
            "delivery": {
                "topology": "single_main",
                "default_stage_branches": {"integration": "main"},
            },
            "rules": {
                "enabled_patterns": [
                    "TYPE_ESCAPE_PATTERN",
                    "TS_EXPLICIT_ANY_PATTERN",
                    "TS_CONSOLE_LOG_PATTERN",
                ],
                "disabled_patterns": [],
            },
            "skills": ["edge-tests-audit-typescript"],
        },
    )
    _write_json(
        profiles_dir / "nextjs-drizzle-tailwind" / "profile.json",
        {
            "schema_version": 1,
            "id": "nextjs-drizzle-tailwind",
            "name": "Next.js App Router + Drizzle + Tailwind",
            "description": "Full-stack Next.js App Router, Drizzle ORM, Tailwind dual-theme, Coolify two-tier.",
            "extends": ["typescript"],
            "detect": {
                "any_files": ["next.config.*", "drizzle.config.*", "tailwind.config.*"],
                "all_files": [],
                "package_json_deps": ["next", "drizzle-orm"],
            },
            "capabilities": [
                "typescript",
                "vitest",
                "nextjs_app_router",
                "drizzle_orm",
                "tailwind_dual_theme",
                "lucide_a11y",
                "server_actions",
                "coolify_two_tier",
            ],
            "paths": {
                "source_roots": ["src/", "app/", "lib/", "db/"],
                "action_globs": ["src/actions/**", "app/actions/**", "*/actions/*.ts*"],
                "schema_globs": ["src/db/schema/*"],
                "migration_globs": ["drizzle/*"],
                "ui_globs": ["src/components/**/*.tsx", "src/app/**/*.tsx", "app/**/*.tsx"],
                "test_globs": ["tests/**", "**/*.test.ts*", "**/*.spec.ts*"],
            },
            "commands": {
                "typecheck": ["npx", "tsc", "--noEmit"],
                "unit_test": ["npm", "run", "test:unit"],
            },
            "delivery": {
                "topology": "two_tier",
                "default_stage_branches": {
                    "integration": "development",
                    "staging": "staging",
                    "production": "production",
                },
            },
            "rules": {
                "enabled_patterns": [
                    "SQL_LEAK_PATTERN",
                    "RAW_TH_PATTERN",
                    "CANONICAL_ARRAY_PATTERN",
                    "SHALLOW_WRAPPER_PATTERN",
                    "BG_WHITE_NO_DARK_PATTERN",
                    "ICON_X_BUTTON_NO_ARIA_PATTERN",
                    "TYPE_ESCAPE_PATTERN",
                    "TS_EXPLICIT_ANY_PATTERN",
                    "TS_CONSOLE_LOG_PATTERN",
                ],
                "disabled_patterns": [],
            },
            "skills": [
                "edge-core-refactor",
                "edge-ui-refactor",
                "edge-ui-audit",
                "edge-tests-audit-typescript",
            ],
        },
    )
    return profiles_dir


def test_missing_root_returns_pure_core_without_raising() -> None:
    _, ResolvedProfileSet, _, resolve_active_profiles, has_cap, is_gate_enabled, _ = _profiles_api()

    resolved = resolve_active_profiles(Path("/nonexistent/mock/repo"))

    assert isinstance(resolved, ResolvedProfileSet)
    assert resolved.profile_ids == []
    assert resolved.profiles == []
    assert resolved.source == "missing_root"
    assert len(resolved.capabilities) == 0
    assert resolved.delivery["topology"] == "single_main"
    assert resolved.delivery["default_stage_branches"]["integration"] == "main"
    assert has_cap(resolved, "typescript") is False
    assert is_gate_enabled(resolved, "migration_gate") is False


@pytest.mark.parametrize("cfg", [{"profiles": []}, {"profile": "none"}])
def test_explicit_none_forces_pure_core_over_stack_markers(tmp_path: Path, cfg: Dict[str, Any]) -> None:
    _, _, _, resolve_active_profiles, has_cap, is_gate_enabled, _ = _profiles_api()
    profiles_dir = _build_fixture_profiles(tmp_path / "profiles")
    repo = tmp_path / "repo"
    _write_text(repo / "next.config.ts", "export default {};\n")
    _write_text(repo / "tsconfig.json", "{}\n")
    _write_json(repo / ".edge" / "profile.json", cfg)

    resolved = resolve_active_profiles(repo, profiles_dir=profiles_dir)

    assert resolved.profile_ids == []
    assert resolved.source == "explicit_none"
    assert len(resolved.capabilities) == 0
    assert resolved.delivery["topology"] == "single_main"
    assert resolved.delivery["default_stage_branches"]["integration"] == "main"
    assert has_cap(resolved, "nextjs_app_router") is False
    assert is_gate_enabled(resolved, "layer_leakage") is False


@pytest.mark.parametrize("cfg", [{"profile": "typescript"}, {"profiles": ["typescript"]}])
def test_explicit_typescript_profile_isolates_from_nextjs_and_coolify(tmp_path: Path, cfg: Dict[str, Any]) -> None:
    StackProfile, _, _, resolve_active_profiles, has_cap, is_gate_enabled, _ = _profiles_api()
    profiles_dir = _build_fixture_profiles(tmp_path / "profiles")
    repo = tmp_path / "ts-repo"
    _write_json(repo / ".edge" / "profile.json", cfg)

    resolved = resolve_active_profiles(repo, profiles_dir=profiles_dir)

    assert resolved.profile_ids == ["typescript"]
    assert resolved.source == "explicit"
    assert len(resolved.profiles) == 1
    assert isinstance(resolved.profiles[0], StackProfile)
    assert resolved.profiles[0].id == "typescript"
    assert resolved.delivery["topology"] == "single_main"
    assert resolved.delivery["default_stage_branches"]["integration"] == "main"
    assert has_cap(resolved, "typescript") is True
    assert has_cap(resolved, "vitest") is True
    for next_cap in (
        "nextjs_app_router",
        "drizzle_orm",
        "tailwind_dual_theme",
        "lucide_a11y",
        "server_actions",
        "coolify_two_tier",
    ):
        assert has_cap(resolved, next_cap) is False

    assert is_gate_enabled(resolved, "type_escapes") is True
    assert is_gate_enabled(resolved, "verification") is True
    for stack_gate in ("migration_gate", "layer_leakage", "dual_theme_and_a11y", "zero_wrappers", "domain_purity"):
        assert is_gate_enabled(resolved, stack_gate) is False


def test_explicit_nextjs_expands_extends_topologically_and_merges(tmp_path: Path) -> None:
    _, _, _, resolve_active_profiles, has_cap, is_gate_enabled, _ = _profiles_api()
    profiles_dir = _build_fixture_profiles(tmp_path / "profiles")
    repo = tmp_path / "next-repo"
    _write_json(repo / ".edge" / "profile.json", {"profile": "nextjs-drizzle-tailwind"})

    resolved = resolve_active_profiles(repo, profiles_dir=profiles_dir)

    assert resolved.profile_ids == ["typescript", "nextjs-drizzle-tailwind"]
    assert [p.id for p in resolved.profiles] == ["typescript", "nextjs-drizzle-tailwind"]
    assert resolved.source == "explicit"
    for cap in (
        "typescript",
        "vitest",
        "nextjs_app_router",
        "drizzle_orm",
        "tailwind_dual_theme",
        "lucide_a11y",
        "server_actions",
        "coolify_two_tier",
    ):
        assert has_cap(resolved, cap) is True

    assert resolved.delivery["topology"] == "two_tier"
    assert resolved.delivery["default_stage_branches"] == {
        "integration": "development",
        "staging": "staging",
        "production": "production",
    }
    assert resolved.paths["action_globs"] == ["src/actions/**", "app/actions/**", "*/actions/*.ts*"]
    assert resolved.paths["schema_globs"] == ["src/db/schema/*"]
    assert resolved.paths["migration_globs"] == ["drizzle/*"]
    assert resolved.commands["typecheck"] == ["npx", "tsc", "--noEmit"]
    assert resolved.commands["unit_test"] == ["npm", "run", "test:unit"]
    assert {"TYPE_ESCAPE_PATTERN", "SQL_LEAK_PATTERN", "BG_WHITE_NO_DARK_PATTERN"}.issubset(
        set(resolved.rules["enabled_patterns"])
    )
    for gate in ("migration_gate", "layer_leakage", "dual_theme_and_a11y", "zero_wrappers", "domain_purity", "type_escapes"):
        assert is_gate_enabled(resolved, gate) is True


def test_diamond_extends_deduplicates_topologically_and_applies_disabled_patterns(tmp_path: Path) -> None:
    _, _, _, resolve_active_profiles, _, _, _ = _profiles_api()
    profiles_dir = tmp_path / "profiles"
    _write_json(
        profiles_dir / "base" / "profile.json",
        {"schema_version": 1, "id": "base", "extends": [], "capabilities": ["c_base"], "rules": {"enabled_patterns": ["P_A", "P_B"]}},
    )
    _write_json(
        profiles_dir / "left" / "profile.json",
        {"schema_version": 1, "id": "left", "extends": ["base"], "capabilities": ["c_left"]},
    )
    _write_json(
        profiles_dir / "right" / "profile.json",
        {"schema_version": 1, "id": "right", "extends": ["base"], "capabilities": ["c_right"]},
    )
    _write_json(
        profiles_dir / "app" / "profile.json",
        {
            "schema_version": 1,
            "id": "app",
            "extends": ["left", "right"],
            "capabilities": ["c_app"],
            "rules": {"enabled_patterns": ["P_C"], "disabled_patterns": ["P_B"]},
        },
    )
    repo = tmp_path / "diamond-repo"
    _write_json(repo / ".edge" / "profile.json", {"profile": "app"})

    resolved = resolve_active_profiles(repo, profiles_dir=profiles_dir)

    assert resolved.profile_ids == ["base", "left", "right", "app"]
    assert {"c_base", "c_left", "c_right", "c_app"}.issubset(set(resolved.capabilities))
    assert "P_A" in resolved.rules["enabled_patterns"]
    assert "P_C" in resolved.rules["enabled_patterns"]
    assert "P_B" not in resolved.rules["enabled_patterns"]


def test_default_plugin_profiles_and_edge_repo_core_default(tmp_path: Path) -> None:
    _, _, _, resolve_active_profiles, has_cap, _, load_profile_station_overlays = _profiles_api()

    edge_res = resolve_active_profiles(ROOT_DIR)
    assert edge_res.profile_ids == []
    assert edge_res.source == "core_default"
    assert has_cap(edge_res, "nextjs_app_router") is False

    next_repo = tmp_path / "real-next-repo"
    _write_text(next_repo / "next.config.ts", "export default {};\n")
    next_res = resolve_active_profiles(next_repo)
    assert next_res.source == "auto_detect"
    assert next_res.profile_ids == ["typescript", "nextjs-drizzle-tailwind"]
    overlays = load_profile_station_overlays("coder", next_res)
    assert [pid for pid, _ in overlays] == ["typescript", "nextjs-drizzle-tailwind"]


def test_unknown_profile_id_and_circular_extends_raise_error(tmp_path: Path) -> None:
    _, _, ProfileResolutionError, resolve_active_profiles, _, _, _ = _profiles_api()
    profiles_dir = _build_fixture_profiles(tmp_path / "profiles")

    unknown_repo = tmp_path / "unknown-repo"
    _write_json(unknown_repo / ".edge" / "profile.json", {"profile": "does-not-exist"})
    with pytest.raises(ProfileResolutionError):
        resolve_active_profiles(unknown_repo, profiles_dir=profiles_dir)

    _write_json(profiles_dir / "cycle-a" / "profile.json", {"schema_version": 1, "id": "cycle-a", "extends": ["cycle-b"]})
    _write_json(profiles_dir / "cycle-b" / "profile.json", {"schema_version": 1, "id": "cycle-b", "extends": ["cycle-a"]})
    cycle_repo = tmp_path / "cycle-repo"
    _write_json(cycle_repo / ".edge" / "profile.json", {"profile": "cycle-a"})
    with pytest.raises(ProfileResolutionError):
        resolve_active_profiles(cycle_repo, profiles_dir=profiles_dir)


def test_explicit_overrides_replace_commands_paths_delivery_and_capabilities(tmp_path: Path) -> None:
    _, _, _, resolve_active_profiles, has_cap, _, _ = _profiles_api()
    profiles_dir = _build_fixture_profiles(tmp_path / "profiles")
    repo = tmp_path / "override-repo"
    _write_json(
        repo / ".edge" / "profile.json",
        {
            "profile": "nextjs-drizzle-tailwind",
            "overrides": {
                "commands": {"unit_test": ["pnpm", "vitest", "run"]},
                "paths": {"migration_globs": ["db/migrations/*"]},
                "delivery": {
                    "topology": "single_main",
                    "default_stage_branches": {"integration": "trunk"},
                },
                "capabilities": ["typescript", "mysql"],
            },
        },
    )

    resolved = resolve_active_profiles(repo, profiles_dir=profiles_dir)

    assert resolved.commands["unit_test"] == ["pnpm", "vitest", "run"]
    assert resolved.commands["typecheck"] == ["npx", "tsc", "--noEmit"]
    assert resolved.paths["migration_globs"] == ["db/migrations/*"]
    assert resolved.delivery["topology"] == "single_main"
    assert resolved.delivery["default_stage_branches"]["integration"] == "trunk"
    assert has_cap(resolved, "mysql") is True
    assert has_cap(resolved, "typescript") is True


@pytest.mark.parametrize(
    ("marker_rel", "marker_body"),
    [
        ("next.config.ts", "export default {};\n"),
        ("drizzle.config.ts", "export default {};\n"),
        ("tailwind.config.ts", "export default {};\n"),
        ("package.json", json.dumps({"dependencies": {"next": "15.0.0"}})),
        ("package.json", json.dumps({"devDependencies": {"drizzle-orm": "0.35.0"}})),
    ],
)
def test_auto_detect_nextjs_drizzle_tailwind_markers(tmp_path: Path, marker_rel: str, marker_body: str) -> None:
    _, _, _, resolve_active_profiles, has_cap, _, _ = _profiles_api()
    profiles_dir = _build_fixture_profiles(tmp_path / "profiles")
    repo = tmp_path / "auto-next"
    _write_text(repo / marker_rel, marker_body)

    resolved = resolve_active_profiles(repo, profiles_dir=profiles_dir)

    assert resolved.source == "auto_detect"
    assert resolved.profile_ids == ["typescript", "nextjs-drizzle-tailwind"]
    assert has_cap(resolved, "nextjs_app_router") is True


def test_auto_detect_tsconfig_only_and_pure_core_defaults(tmp_path: Path) -> None:
    _, _, _, resolve_active_profiles, has_cap, _, _ = _profiles_api()
    profiles_dir = _build_fixture_profiles(tmp_path / "profiles")

    ts_repo = tmp_path / "auto-ts"
    _write_text(ts_repo / "tsconfig.json", "{}\n")
    ts_res = resolve_active_profiles(ts_repo, profiles_dir=profiles_dir)
    assert ts_res.source == "auto_detect"
    assert ts_res.profile_ids == ["typescript"]
    assert has_cap(ts_res, "typescript") is True
    assert has_cap(ts_res, "nextjs_app_router") is False

    empty_repo = tmp_path / "empty-repo"
    empty_repo.mkdir(parents=True)
    empty_res = resolve_active_profiles(empty_repo, profiles_dir=profiles_dir)
    assert empty_res.source == "core_default"
    assert empty_res.profile_ids == []
    assert len(empty_res.capabilities) == 0

    py_repo = tmp_path / "python-repo"
    _write_text(py_repo / "pyproject.toml", "[project]\nname = 'edge'\n")
    _write_text(py_repo / "tools" / "app.py", "print('ok')\n")
    py_res = resolve_active_profiles(py_repo, profiles_dir=profiles_dir)
    assert py_res.source == "core_default"
    assert py_res.profile_ids == []


def test_load_profile_station_overlays_base_to_derived_order(tmp_path: Path) -> None:
    _, _, _, resolve_active_profiles, _, _, load_profile_station_overlays = _profiles_api()
    profiles_dir = _build_fixture_profiles(tmp_path / "profiles")
    _write_text(profiles_dir / "typescript" / "agents" / "coder.md", "TS coder overlay\n")
    _write_text(profiles_dir / "nextjs-drizzle-tailwind" / "agents" / "coder.md", "Next coder overlay\n")
    _write_text(profiles_dir / "typescript" / "agents" / "seam-architect.md", "TS seam overlay\n")
    _write_text(profiles_dir / "nextjs-drizzle-tailwind" / "agents" / "seam-architect.md", "Next seam overlay\n")
    _write_text(profiles_dir / "nextjs-drizzle-tailwind" / "agents" / "qa-engineer.md", "Next qa overlay\n")

    repo = tmp_path / "overlay-repo"
    _write_json(repo / ".edge" / "profile.json", {"profile": "nextjs-drizzle-tailwind"})
    resolved = resolve_active_profiles(repo, profiles_dir=profiles_dir)

    coder_overlays = load_profile_station_overlays("coder", resolved)
    assert [pid for pid, _ in coder_overlays] == ["typescript", "nextjs-drizzle-tailwind"]
    assert "TS coder overlay" in coder_overlays[0][1]
    assert "Next coder overlay" in coder_overlays[1][1]

    # Underscore role slug resolves hyphenated agent markdown filenames
    seam_overlays = load_profile_station_overlays("seam_architect", resolved)
    assert [pid for pid, _ in seam_overlays] == ["typescript", "nextjs-drizzle-tailwind"]

    # Roles missing in base profile skip cleanly without failing
    qa_overlays = load_profile_station_overlays("qa_engineer", resolved)
    assert [pid for pid, _ in qa_overlays] == ["nextjs-drizzle-tailwind"]

    core_resolved = resolve_active_profiles(Path("/nonexistent/mock/repo"))
    assert load_profile_station_overlays("coder", core_resolved) == []


def test_stdlib_only_and_sub_50ms_latency_guard(tmp_path: Path) -> None:
    profiles_dir = _build_fixture_profiles(tmp_path / "profiles")
    repo = tmp_path / "perf-repo"
    _write_text(repo / "next.config.ts", "export default {};\n")

    probe = (
        "import json, sys, time; "
        "from pathlib import Path; "
        "before = set(sys.modules.keys()); "
        "t0 = time.perf_counter(); "
        "import tools.common.profiles as p; "
        "res = p.resolve_active_profiles(Path(sys.argv[1]), profiles_dir=Path(sys.argv[2])); "
        "elapsed_ms = (time.perf_counter() - t0) * 1000.0; "
        "added = sorted(m for m in sys.modules if m not in before); "
        "print(json.dumps({'elapsed_ms': elapsed_ms, 'added': added, 'ids': res.profile_ids}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe, str(repo), str(profiles_dir)],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Subprocess import/resolve failed: {proc.stderr}"
    data = json.loads(proc.stdout.strip())
    assert data["ids"] == ["typescript", "nextjs-drizzle-tailwind"]
    assert data["elapsed_ms"] < 50.0, f"resolve_active_profiles took {data['elapsed_ms']:.2f}ms (>= 50ms)"

    forbidden_heavy = {
        "tools.brigade.fsm",
        "tools.brigade.stations",
        "tools.common.toon",
        "tools.common.runner",
    }
    added_set = set(data["added"])
    assert forbidden_heavy.isdisjoint(added_set), f"Heavy modules eagerly loaded: {forbidden_heavy & added_set}"

    allowed_tools = {"tools", "tools.common", "tools.common.profiles"}
    for mod_name in added_set:
        top_pkg = mod_name.split(".")[0]
        if top_pkg == "tools":
            assert mod_name in allowed_tools, f"Unexpected tools module imported: {mod_name}"
        else:
            assert top_pkg in sys.stdlib_module_names, f"Non-stdlib module imported: {mod_name}"

    profiles_src = ROOT_DIR / "tools" / "common" / "profiles.py"
    tree = ast.parse(profiles_src.read_text(encoding="utf-8"), filename=str(profiles_src))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in sys.stdlib_module_names
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            assert node.module.split(".")[0] in sys.stdlib_module_names


def test_distill_collect_budget_targets_includes_profile_agents_40_line_ceiling(tmp_path: Path) -> None:
    from tools.distill.state import check_line_budget, collect_budget_targets

    repo = tmp_path / "plugin-repo"
    _write_text(repo / "agents" / "coder.md", "\n".join(f"core {i}" for i in range(10)))
    _write_text(repo / ".edge" / "stations" / "coder.md", "\n".join(f"local {i}" for i in range(10)))
    _write_text(repo / "profiles" / "typescript" / "agents" / "coder.md", "\n".join(f"ts {i}" for i in range(40)))
    _write_text(
        repo / "profiles" / "nextjs-drizzle-tailwind" / "agents" / "examiner.md",
        "\n".join(f"next {i}" for i in range(25)),
    )
    _write_text(repo / "profiles" / "typescript" / "PLAYBOOK.md", "\n".join(f"doc {i}" for i in range(120)))

    targets: Dict[str, int] = {
        path.resolve().relative_to(repo.resolve()).as_posix(): limit
        for path, limit in collect_budget_targets(repo)
    }

    assert targets["agents/coder.md"] == 60
    assert targets[".edge/stations/coder.md"] == 40
    assert targets["profiles/typescript/agents/coder.md"] == 40
    assert targets["profiles/nextjs-drizzle-tailwind/agents/examiner.md"] == 40
    assert "profiles/typescript/PLAYBOOK.md" not in targets

    ok_before, _, _ = check_line_budget(repo)
    assert ok_before is True

    _write_text(repo / "profiles" / "typescript" / "agents" / "coder.md", "\n".join(f"ts {i}" for i in range(41)))
    ok_after, max_cnt, eff_limit = check_line_budget(repo)
    assert ok_after is False
    assert max_cnt == 41
    assert eff_limit == 40
