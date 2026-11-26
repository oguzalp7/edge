"""Companion unit tests for hooks/dispatch.py session-gate and fail-open helpers."""

import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hooks import dispatch  # noqa: E402


def test_dispatch_fail_open_responses_and_kill_switch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EDGE_HOME", str(tmp_path / "edge_home"))
    monkeypatch.setenv("EDGE_ANTIGRAVITY_DIR", str(tmp_path / "agy"))
    monkeypatch.setenv("EDGE_HOOKS", "off")

    assert dispatch._fail_open_response("pre_tool") == {"decision": "allow"}
    assert dispatch._fail_open_response("post_tool") == {}
    assert dispatch._fail_open_response("pre_invocation") == {"injectSteps": []}

    enforce, reason = dispatch.should_enforce_hooks({"conversationId": "c1", "lastUserInput": "/edge-orchestrator"})
    assert enforce is False
    assert reason == "hooks_off"


def test_dispatch_activates_on_orchestrator_slash_and_station_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EDGE_HOME", str(tmp_path / "edge_home"))
    monkeypatch.setenv("EDGE_ANTIGRAVITY_DIR", str(tmp_path / "agy"))
    monkeypatch.delenv("EDGE_HOOKS", raising=False)

    enforce_orch, reason_orch = dispatch.should_enforce_hooks(
        {"conversationId": "c-orch", "lastUserInput": "/edge-orchestrator run slice"}
    )
    assert enforce_orch is True
    assert reason_orch == "explicit_trigger"

    tp = tmp_path / "station_tp.jsonl"
    tp.write_text(json.dumps({"step_index": 0, "source": "SYSTEM", "content": "[edge-station:CODER] implement"}) + "\n", encoding="utf-8")
    enforce_station, reason_station = dispatch.should_enforce_hooks(
        {"conversationId": "c-station", "transcriptPath": str(tp)}
    )
    assert enforce_station is True
    assert reason_station == "station_token"
