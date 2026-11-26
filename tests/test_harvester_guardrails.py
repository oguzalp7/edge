import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.distill.harvester_guardrails import _extract_guardrail_gaps


def test_extract_guardrail_gaps_missing_ci(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    gaps = _extract_guardrail_gaps(tmp_path)
    kinds = {g.gap_type for g in gaps}
    assert "MISSING_GUARDRAIL" in kinds
    assert "UNWIRED_GUARDRAIL" in kinds
