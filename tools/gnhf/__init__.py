"""
Edge-GNHF: Autonomous Overnight Worktree Engine ("Good Night, Have Fun").
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any


class AfkMode(str, Enum):
    STRICT = "strict"
    YOLO = "yolo"


@dataclass
class SkippedHitlBlocker:
    file_path: str
    reason: str
    raw_line: str


@dataclass
class GnhfWorktreeStatus:
    worktree_path: Path
    branch_name: str
    base_branch: str
    commits_ahead: int
    last_commit_hash: str
    last_commit_subject: str
    last_commit_timestamp: str
    blockers: List[SkippedHitlBlocker] = field(default_factory=list)


@dataclass
class GnhfRunOptions:
    repo_path: Path
    objective: str
    mode: AfkMode = AfkMode.STRICT
    agent: str = "agy"
    model: str = "gemini-3.8-flash-medium"
    track: str = "all"
    max_iterations: Optional[int] = None
    max_tokens: Optional[int] = None
    stop_when: Optional[str] = None
    test_cmd: Optional[str] = None
    dry_run: bool = False


@dataclass
class GnhfHarvestResult:
    branch_name: str
    base_branch: str
    gate_passed: bool
    gate_exit_code: int
    gate_output: str
    diff_stat: str
    merged: bool = False
    cleaned_up: bool = False
    error: Optional[str] = None


from tools.gnhf.shim import create_agy_shim
from tools.gnhf.prompt import build_gnhf_prompt
from tools.gnhf.runner import execute_gnhf_run
from tools.gnhf.harvest import get_gnhf_status, harvest_worktree
from tools.gnhf.cli import parse_args

__all__ = [
    "AfkMode",
    "SkippedHitlBlocker",
    "GnhfWorktreeStatus",
    "GnhfRunOptions",
    "GnhfHarvestResult",
    "create_agy_shim",
    "build_gnhf_prompt",
    "execute_gnhf_run",
    "get_gnhf_status",
    "harvest_worktree",
    "parse_args",
]
