"""Stdlib-only import hygiene and <50ms dispatch budget tests for orchestrator_guard."""

import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from tools.brigade import orchestrator_guard as guard


def test_orchestrator_guard_imports_only_stdlib_in_fresh_subprocess() -> None:
    """Importing orchestrator_guard must load only stdlib and tools.brigade.guard.* modules."""
    repo_root = Path(__file__).resolve().parent.parent
    probe = (
        "import json, sys; "
        "import tools.brigade.orchestrator_guard; "
        "loaded = sorted(k for k in sys.modules if k.startswith(('tools.', 'yaml', 'tree_sitter', 'pytest'))); "
        "print(json.dumps(loaded))"
    )
    res = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = json.loads(res.stdout.strip())
    forbidden = [
        mod for mod in loaded
        if mod != "tools"
        and mod != "tools.brigade"
        and mod != "tools.brigade.orchestrator_guard"
        and not mod.startswith("tools.brigade.guard")
    ]
    assert forbidden == [], f"Non-guard / heavy modules loaded at import time: {forbidden}"


def test_handle_pre_tool_and_pre_invocation_under_50ms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hot-path hook dispatch must finish within the 50ms latency budget."""
    monkeypatch.setattr(guard, "ACTIVE_STATIONS_FILE", tmp_path / "edge_active_stations.json")
    monkeypatch.delenv("EDGE_AFK", raising=False)
    monkeypatch.delenv("EDGE_AFK_MODE", raising=False)

    pre_tool_payload = {
        "conversationId": "perf-cid-1",
        "toolCall": {"name": "read_file", "args": {"Path": str(tmp_path / "src/app.ts")}},
    }
    pre_inv_payload = {
        "conversationId": "perf-cid-1",
        "userMessage": "Inspect the codebase",
    }

    t0 = time.perf_counter()
    tool_res = guard.handle_pre_tool(pre_tool_payload)
    tool_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    inv_res = guard.handle_pre_invocation(pre_inv_payload)
    inv_ms = (time.perf_counter() - t1) * 1000.0

    assert tool_res.get("decision") == "allow"
    assert isinstance(inv_res, dict)
    assert tool_ms < 50.0, f"handle_pre_tool took {tool_ms:.2f}ms (>= 50ms)"
    assert inv_ms < 50.0, f"handle_pre_invocation took {inv_ms:.2f}ms (>= 50ms)"
