"""Companion unit tests for tools.drift.spec_discovery."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pathlib import Path

from tools.drift.spec_discovery import archive_ephemeral_spec, discover_specs


def test_archive_ephemeral_spec_and_discover_specs(tmp_path: Path) -> None:
    dom_file = tmp_path / "docs" / "core" / "DOMAIN.md"
    dom_file.parent.mkdir(parents=True)
    dom_file.write_text("# Domain: `core`\n- **Concepts:** `x`\n", encoding="utf-8")

    spec_file = tmp_path / ".edge" / "specs" / "feat-a.md"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text("# Feat A\n", encoding="utf-8")

    cache_file = tmp_path / ".edge" / "cache" / "issues" / "1-spec.md"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("# Cached Issue\n", encoding="utf-8")

    report = discover_specs(tmp_path, include_cached_issues=True)
    assert report.domain_contracts == ["docs/core/DOMAIN.md"]
    assert ".edge/specs/feat-a.md" in report.ephemeral_candidates

    # Cache files must never be archived
    assert archive_ephemeral_spec(tmp_path, cache_file) is None
    assert cache_file.exists()

    archived = archive_ephemeral_spec(tmp_path, spec_file)
    assert archived is not None and archived.exists()
    assert not spec_file.exists()
