"""
RED unit & contract tests for Slice 1.2: Honest Python Test-Seam Calibration.

Contracts covered:
- `FileScanner._build_test_index` strips Python's leading `test_` prefix
  (e.g. `tests/test_ship_prep.py` -> `ship_prep`, `tests/test_profiles.py` -> `profiles`)
  without corrupting inner `test_` substrings (e.g. `test_attest_helper.py` -> `attest_helper`).
- Honest matching: `tests/test_brigade.py` MUST NOT falsely mark an untested
  `tools/brigade/orphan_helper.py` as having a test seam (no directory-wide blanket match).
- `GENERIC_STEMS` (`cli`, `models`, `scanner`) isolation and scoped matching.
- Negative orphan module check (`has_test_seam == False` for `tools/foo/orphan_widget.py`).
"""

import sys
from pathlib import Path
from typing import Dict

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.audit.models import FileMetrics
from tools.audit.scanner import FileScanner


def _write(path: Path, content: str = "def fn():\n    return 1\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _scan_by_rel_path(root: Path) -> Dict[str, FileMetrics]:
    summary = FileScanner(workspace_root=root).scan(root)
    return {m.rel_path.replace("\\", "/"): m for m in summary.file_results}


def _norm_paths(paths: list[str]) -> list[str]:
    return [p.replace("\\", "/") for p in paths]


def test_build_test_index_strips_python_test_prefix(tmp_path: Path) -> None:
    _write(tmp_path / "tests" / "test_ship_prep.py", "def test_ship(): pass\n")
    _write(tmp_path / "tests" / "test_profiles.py", "def test_prof(): pass\n")
    _write(tmp_path / "tests" / "test_attest_helper.py", "def test_att(): pass\n")
    _write(tmp_path / "tests" / "legacy_runner_test.py", "def test_leg(): pass\n")

    index = FileScanner(workspace_root=tmp_path)._build_test_index(tmp_path)

    assert "tests/test_ship_prep.py" in _norm_paths(index.get("ship_prep", []))
    assert "tests/test_profiles.py" in _norm_paths(index.get("profiles", []))
    assert "tests/test_attest_helper.py" in _norm_paths(index.get("attest_helper", []))
    assert index.get("athelper", []) == []
    assert "tests/legacy_runner_test.py" in _norm_paths(index.get("legacy_runner", []))


def test_scan_matches_ship_prep_and_profiles_via_test_prefix(tmp_path: Path) -> None:
    _write(tmp_path / "tools" / "brigade" / "ship_prep.py")
    _write(tmp_path / "tools" / "common" / "profiles.py")
    _write(tmp_path / "tests" / "test_ship_prep.py", "def test_prepare(): pass\n")
    _write(tmp_path / "tests" / "test_profiles.py", "def test_resolve(): pass\n")

    by_path = _scan_by_rel_path(tmp_path)

    ship_m = by_path["tools/brigade/ship_prep.py"]
    assert ship_m.has_test_seam is True
    assert "tests/test_ship_prep.py" in _norm_paths(ship_m.companion_tests)

    prof_m = by_path["tools/common/profiles.py"]
    assert prof_m.has_test_seam is True
    assert "tests/test_profiles.py" in _norm_paths(prof_m.companion_tests)


def test_honest_matching_no_brigade_directory_blanket(tmp_path: Path) -> None:
    _write(tmp_path / "tools" / "brigade" / "orphan_helper.py")
    _write(tmp_path / "tools" / "brigade" / "cli.py")
    _write(tmp_path / "tools" / "distill" / "models.py")
    _write(tmp_path / "tools" / "distill" / "orphan_internal.py")
    _write(tmp_path / "tests" / "test_brigade.py", "def test_brigade_cli(): pass\n")
    _write(tmp_path / "tests" / "test_distill.py", "def test_distill_models(): pass\n")

    by_path = _scan_by_rel_path(tmp_path)

    assert by_path["tools/brigade/orphan_helper.py"].has_test_seam is False
    assert by_path["tools/brigade/orphan_helper.py"].companion_tests == []
    assert by_path["tools/distill/orphan_internal.py"].has_test_seam is False
    assert by_path["tools/distill/orphan_internal.py"].companion_tests == []
    # Generic stems in a tested domain still resolve via domain:<parent_dir>
    assert by_path["tools/brigade/cli.py"].has_test_seam is True
    assert by_path["tools/distill/models.py"].has_test_seam is True


def test_generic_stems_bare_names_do_not_blanket_match(tmp_path: Path) -> None:
    for stem in ("cli", "models", "scanner"):
        _write(tmp_path / "tools" / "alpha" / f"{stem}.py")
        _write(tmp_path / "tests" / f"test_{stem}.py", "def test_generic(): pass\n")

    scanner = FileScanner(workspace_root=tmp_path)
    index = scanner._build_test_index(tmp_path)

    for stem in ("cli", "models", "scanner"):
        assert index.get(stem, []) == []
        assert index.get(f"domain:{stem}", []) == []

    by_path = _scan_by_rel_path(tmp_path)
    for stem in ("cli", "models", "scanner"):
        metric = by_path[f"tools/alpha/{stem}.py"]
        assert metric.has_test_seam is False
        assert metric.companion_tests == []


def test_generic_stems_scoped_subdir_match_without_cross_domain_leak(tmp_path: Path) -> None:
    for stem in ("cli", "models", "scanner"):
        _write(tmp_path / "tools" / "billing" / f"{stem}.py")
        _write(tmp_path / "tools" / "other" / f"{stem}.py")
        _write(tmp_path / "tests" / "billing" / f"test_{stem}.py", "def test_scoped(): pass\n")

    by_path = _scan_by_rel_path(tmp_path)

    for stem in ("cli", "models", "scanner"):
        billing_m = by_path[f"tools/billing/{stem}.py"]
        assert billing_m.has_test_seam is True
        assert f"tests/billing/test_{stem}.py" in _norm_paths(billing_m.companion_tests)

        other_m = by_path[f"tools/other/{stem}.py"]
        assert other_m.has_test_seam is False
        assert other_m.companion_tests == []


def test_negative_orphan_module_has_no_test_seam(tmp_path: Path) -> None:
    _write(tmp_path / "tools" / "foo" / "orphan_widget.py")
    _write(tmp_path / "tools" / "foo" / "tested_widget.py")
    _write(tmp_path / "tests" / "test_tested_widget.py", "def test_ok(): pass\n")

    by_path = _scan_by_rel_path(tmp_path)

    orphan_m = by_path["tools/foo/orphan_widget.py"]
    assert orphan_m.has_test_seam is False
    assert orphan_m.companion_tests == []

    tested_m = by_path["tools/foo/tested_widget.py"]
    assert tested_m.has_test_seam is True
    assert "tests/test_tested_widget.py" in _norm_paths(tested_m.companion_tests)
