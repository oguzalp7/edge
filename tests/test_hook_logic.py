"""Hermetic cross-OS subprocess smoke tests for orchestrator_guard.py hooks."""

import json
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_SCRIPT = REPO_ROOT / "tools" / "brigade" / "orchestrator_guard.py"


def _run_guard(mode: str, payload: dict, tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["EDGE_ANTIGRAVITY_DIR"] = str(tmp_path / "agy")
    env["EDGE_HOME"] = str(tmp_path / "edge_home")
    raw = subprocess.check_output(
        [sys.executable, str(GUARD_SCRIPT), mode],
        input=json.dumps(payload).encode("utf-8"),
        env=env,
    ).decode("utf-8")
    return json.loads(raw.strip())


def test_orchestrator_guard_cli_pre_tool_and_pre_invocation(tmp_path: Path) -> None:
    orch_tp = tmp_path / "orch_transcript.jsonl"
    orch_tp.write_text(
        json.dumps({"type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "/edge-orchestrator start"}) + "\n",
        encoding="utf-8",
    )
    payload_tool = {
        "conversationId": "orch-cli-smoke",
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": "src/app.ts"}},
        "transcriptPath": str(orch_tp),
    }

    res_tool = _run_guard("pre_tool", payload_tool, tmp_path)
    assert res_tool["decision"] == "deny"

    res_inv = _run_guard("pre_invocation", payload_tool, tmp_path)
    assert res_inv.get("injectSteps")

    coder_tp = tmp_path / "coder_transcript.jsonl"
    coder_tp.write_text(
        json.dumps(
            {
                "type": "SYSTEM_MESSAGE",
                "source": "SYSTEM",
                "content": "[Message] content=[edge-station:CODER] You are the CODER station worker.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    payload_coder = {
        "conversationId": "coder-cli-smoke",
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": "src/app.ts"}},
        "transcriptPath": str(coder_tp),
    }
    res_allow = _run_guard("pre_tool", payload_coder, tmp_path)
    assert res_allow["decision"] == "allow"
