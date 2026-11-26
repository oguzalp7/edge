"""
Flight-recorder, critique file, and git churn extractors for TranscriptGraphHarvester.
"""

import subprocess
from pathlib import Path
from typing import Any, Dict, List

from tools.distill.harvester_harness import _parse_dead_end_entry, _parse_guard_failure_entry
from tools.distill.harvester_matching import _read_json_safe


def extract_flight_recorder(project_path: Path) -> List[Dict[str, Any]]:
    insights: List[Dict[str, Any]] = []
    fr_dir = project_path / ".edge" / "flight-recorder"
    if not fr_dir.exists():
        return insights
    for f in sorted(fr_dir.glob("*.json")):
        data = _read_json_safe(f)
        if not data:
            continue
        insights.extend(_parse_dead_end_entry(d) for d in data.get("dead_ends", []))
        insights.extend(_parse_guard_failure_entry(g) for g in data.get("guard_failures", []))
    return insights


def extract_critiques(project_path: Path) -> List[Dict[str, Any]]:
    critiques: List[Dict[str, Any]] = []
    specs_dir = project_path / ".edge" / "specs"
    if not specs_dir.exists():
        return critiques
    for f in specs_dir.glob("*critique*.md"):
        try:
            critiques.append({"spec": f.name, "finding": f.read_text(encoding="utf-8")[:200]})
        except Exception:
            pass
    return critiques


def extract_git_churn(project_path: Path) -> List[Dict[str, Any]]:
    if not (project_path / ".git").exists():
        return []
    try:
        res = subprocess.run(
            ["git", "log", "-n", "15", "--grep=revert", "--grep=fixup", "--oneline"],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return []
        return [
            {"commit": parts[0], "message": parts[1] if len(parts) > 1 else ""}
            for line in res.stdout.strip().splitlines()
            for parts in [line.split(" ", 1)]
        ]
    except Exception:
        return []
