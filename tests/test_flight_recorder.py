"""Companion unit tests for FlightRecorder persistence and rendering."""

from pathlib import Path
from tools.brigade.flight_recorder import FlightRecorder


def test_flight_recorder_roundtrip_and_dedup(tmp_path: Path) -> None:
    rec = FlightRecorder(tmp_path, "TICK-101")
    rec.set_metadata(track="core", domain="auth", target_file="src/auth.ts", expected_files=["src/auth.ts"])
    rec.record_dead_end(title="Raw SQL", reason="Broke repository boundary", prohibited_rule="Never query DB from action")
    rec.record_escalation("Need decision", station="CODER")
    rec.record_captain_decision("Use repository", decided_by="captain")
    rec.record_attempt(1, 0, "All green", diff_stat="1 file changed")
    rec.record_guard_failure("VERIFY", "Gate failed", {"code": 1})
    rec.seal_review_findings([{"axis": "standards", "file_path": "src/auth.ts", "line_number": 5, "description": "dup"}, {"axis": "standards", "file_path": "src/auth.ts", "line_number": 5, "description": "dup"}])

    reloaded = FlightRecorder(tmp_path, "TICK-101")
    assert reloaded.load()["status"] == "DECIDED"
    assert len(reloaded.load()["review_findings"]) == 1
    assert reloaded.get_negative_constraints() == ["Never query DB from action"]
    alert = reloaded.get_prompt_alert_block()
    assert "Never query DB from action" in alert
    assert "Use repository" in alert
    assert reloaded.md_file.exists()
