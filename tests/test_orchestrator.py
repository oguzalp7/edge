import sys
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.brigade.ship.orchestrator import _evaluate_danger_with_receipts, prepare_ship_payload


def test_evaluate_danger_with_receipts_merges_one_way_reasons() -> None:
    receipts = [(".edge/receipts/refactor/demo.json", {
        "seal_1_intent": {"door_type": "One-way door (seal)", "one_way_reasons": ["Custom receipt reason"]}
    })]
    door, blast = _evaluate_danger_with_receipts(["src/core/a.py"], "1 file changed, 1 insertion(+)", "", "refactor/demo", None, receipts)
    assert door.startswith("One-way")
    assert "Custom receipt reason" in blast["one_way_reasons"]


def test_prepare_ship_payload_rejects_slice_targeting_staging(tmp_path: Path) -> None:
    with patch("tools.brigade.ship_prep.run_command", return_value=(0, "feat/demo\n", "")):
        ok, res, err = prepare_ship_payload(tmp_path, base_branch="staging")
    assert not ok
    assert "Branch topology violation" in err
    assert res.head_branch == "feat/demo"
