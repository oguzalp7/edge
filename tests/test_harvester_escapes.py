import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.distill.harvester_escapes import _detect_escalation_role, _extract_station_escapes_from_steps


def test_station_escapes_and_escalation_role() -> None:
    assert _detect_escalation_role("Please ask surgeon to fix") == "surgeon"
    steps = [
        {"source": "MODEL", "content": "EXAMINER REVIEW: PASS", "tool_calls": []},
        {"source": "SYSTEM", "content": "Command exited with code 1: FAILED"},
    ]
    escapes = _extract_station_escapes_from_steps("cid-12345678", steps)
    assert len(escapes) == 1
    assert escapes[0].escape_type == "ESCAPED_DEFECT"
