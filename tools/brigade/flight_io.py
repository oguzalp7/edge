"""Atomic JSON/Markdown persistence helpers for FlightRecorder."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict


def default_flight_data(ticket_id: str) -> Dict[str, Any]:
    """Return initial empty FlightRecorder state dictionary."""
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "ticket_id": ticket_id,
        "status": "ACTIVE",
        "track": "core",
        "domain": "unknown",
        "target_file": "",
        "worktree_path": "",
        "created_at": now_iso,
        "updated_at": now_iso,
        "dead_ends": [],
        "escalations": [],
        "attempts": [],
        "guard_failures": [],
        "review_findings": [],
    }


def load_flight_data(json_file: Path, ticket_id: str) -> Dict[str, Any]:
    """Load persisted FlightRecorder JSON or initialize fresh state."""
    if not json_file.exists():
        return default_flight_data(ticket_id)
    try:
        data = json.loads(json_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("guard_failures", [])
            data.setdefault("review_findings", [])
            return data
    except Exception:
        pass
    return default_flight_data(ticket_id)


def atomic_write_text_file(target_path: Path, content: str) -> None:
    """Atomically write UTF-8 text via sibling .tmp rename."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    if tmp_path.exists():
        if target_path.exists():
            target_path.unlink()
        tmp_path.rename(target_path)


def atomic_save_flight_json(json_file: Path, data: Dict[str, Any]) -> None:
    """Update timestamp and atomically persist FlightRecorder JSON state."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    serialized = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    atomic_write_text_file(json_file, serialized)
