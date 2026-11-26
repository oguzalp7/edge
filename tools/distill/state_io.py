"""Path resolution, atomic JSON writes, and watermark state manager for edge-distill."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Optional

from tools.distill.models import DistillWatermarkState

TIMESTAMP_LINE_PATTERN = re.compile(r"^(?:Created|Completed)\s+At:\s*.*$", re.MULTILINE | re.IGNORECASE)
ISO8601_TIMESTAMP_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b")
WSL_RELAY_PID_PATTERN = re.compile(r"WSL\s*\(\s*\d+\s*-\s*Relay\s*\)", re.IGNORECASE)
EPHEMERAL_PATH_PATTERN = re.compile(
    r'''(?:/tmp/|/var/folders/|[A-Za-z]:[\\/]Users[\\/][^\\/]+[\\/]AppData[\\/]Local[\\/]Temp[\\/])[^\s"'`:;]+''',
    re.IGNORECASE,
)
EPHEMERAL_TEST_DIR_PATTERN = re.compile(
    r"(?:^|[\\/])(?:pytest-[^\\/]+|test_[^\\/]+|unittest|tmp[^\\/]*|temp[^\\/]*)(?:[\\/]|$)"
    r"|(?:^|[\\/])(?:tmp|var[\\/]folders|AppData[\\/]Local[\\/]Temp)(?:[\\/]|$)",
    re.IGNORECASE,
)


def _sanitize_signal_summary(summary: str) -> str:
    if not summary:
        return ""
    text = TIMESTAMP_LINE_PATTERN.sub("", summary)
    text = ISO8601_TIMESTAMP_PATTERN.sub("<TIMESTAMP>", text)
    text = WSL_RELAY_PID_PATTERN.sub("WSL (<PID> - Relay)", text)
    text = EPHEMERAL_PATH_PATTERN.sub("<TMP_PATH>", text)
    return " ".join(line.strip() for line in text.splitlines() if line.strip()).strip()


def _is_ephemeral_test_path(path_str: str) -> bool:
    if not path_str:
        return False
    return bool(EPHEMERAL_TEST_DIR_PATTERN.search(str(path_str).replace("\\", "/")))


def _resolve_agent_rubric_path(root: Path, role: str) -> Path:
    clean_role = role.strip().lower()
    hyphen_path = root / "agents" / f"{clean_role.replace('_', '-')}.md"
    if hyphen_path.is_file():
        return hyphen_path
    underscore_path = root / "agents" / f"{clean_role.replace('-', '_')}.md"
    return underscore_path if underscore_path.is_file() else hyphen_path


def _default_state_path() -> Path:
    env_path = os.environ.get("EDGE_DISTILL_STATE_FILE")
    return Path(env_path).resolve() if env_path else (Path.home() / ".gemini" / "antigravity" / "edge_distill_state.json").resolve()


def _default_factory_inbox_path() -> Path:
    env_path = os.environ.get("EDGE_DISTILL_FACTORY_INBOX_FILE")
    return Path(env_path).resolve() if env_path else (Path.home() / ".gemini" / "antigravity" / "edge_factory_inbox.json").resolve()


def _default_candidates_path() -> Path:
    env_path = os.environ.get("EDGE_DISTILL_CANDIDATES_FILE")
    return Path(env_path).resolve() if env_path else (Path.home() / ".gemini" / "antigravity" / "edge_distill_candidates.json").resolve()


def _save_json_atomic(target_path: Path, data: Any) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=target_path.parent, prefix="atomic_", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, target_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


class DistillStateManager:
    """Manages atomic watermark state across harvest runs."""

    def __init__(self, state_file_override: Optional[Path] = None):
        self.state_file = Path(state_file_override).resolve() if state_file_override else _default_state_path()

    def load_state(self) -> DistillWatermarkState:
        if not self.state_file.exists():
            return DistillWatermarkState()
        try:
            return DistillWatermarkState.from_dict(json.loads(self.state_file.read_text(encoding="utf-8")))
        except Exception:
            return DistillWatermarkState()

    def save_state(self, state: DistillWatermarkState) -> None:
        _save_json_atomic(self.state_file, state.to_dict())

    def mark_session_processed(self, session_id: str, project_path: Optional[str] = None, mode: str = "project") -> None:
        state = self.load_state()
        if session_id not in state.processed_sessions:
            state.processed_sessions.append(session_id)
        if mode == "factory":
            if session_id not in state.factory_processed_sessions:
                state.factory_processed_sessions.append(session_id)
        elif project_path:
            p_sessions = state.project_sessions.setdefault(str(project_path), [])
            if session_id not in p_sessions:
                p_sessions.append(session_id)
        state.last_harvested_at = datetime.now(timezone.utc).isoformat()
        state.metrics["total_harvested"] = len(state.processed_sessions)
        self.save_state(state)

    def is_session_processed(self, session_id: str, project_path: Optional[str] = None, mode: str = "all") -> bool:
        state = self.load_state()
        if mode == "factory":
            return session_id in state.factory_processed_sessions
        if mode == "project" and project_path and str(project_path) in state.project_sessions:
            return session_id in state.project_sessions[str(project_path)]
        return session_id in state.processed_sessions
