"""
Shared filesystem primitives for Edge Tools.

Provides worktree-aware primary repository root resolution and atomic file writes
using sibling temporary files (`tempfile.mkstemp`) and `os.replace`.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Union

from .paths import normalize_target_path


def resolve_target_repo_root(path: Union[str, Path]) -> Path:
    """Resolve the primary repository root from a checkout or git worktree.

    Normalizes ``path`` via ``normalize_target_path`` and inspects
    ``git rev-parse --git-common-dir`` so leased worktrees anchor back to the
    primary repository root. Falls back to the normalized path outside git.
    """
    norm = normalize_target_path(path)
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(norm),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            raw_common = Path(proc.stdout.strip())
            common_path = raw_common if raw_common.is_absolute() else (norm / raw_common)
            return common_path.resolve().parent
    except Exception:
        pass
    return norm.resolve()


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically write UTF-8 text via sibling ``mkstemp`` and ``os.replace``.

    Creates parent directories if missing, writes exact UTF-8 bytes without
    newline translation, closes the descriptor before ``os.replace``, and
    unlinks any temporary file on failure.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.tmp.")
    tmp_path = Path(tmp_name)
    fd_closed = False
    try:
        with os.fdopen(fd, "wb") as handle:
            fd_closed = True
            handle.write(content.encode("utf-8"))
        os.replace(tmp_path, target)
    finally:
        if not fd_closed:
            os.close(fd)
        tmp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any, indent: int = 2) -> None:
    """Atomically serialize ``payload`` as UTF-8 JSON with a trailing newline."""
    serialized = json.dumps(payload, indent=indent, ensure_ascii=False) + "\n"
    atomic_write_text(path, serialized)
