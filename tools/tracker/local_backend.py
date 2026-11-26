"""
Local offline/no-remote tracker backend anchored to the primary repository root.

Persists issues atomically under `<primary_root>/.edge/issues/` (`index.json` +
`<N>.md`) using `os.O_CREAT | os.O_EXCL` issue-number claiming and `tools.common.fs`.
"""

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union

from tools.common.fs import atomic_write_json, atomic_write_text, resolve_target_repo_root
from .models import CANONICAL_LABELS, TrackerBackendKind, TrackerComment, TrackerError, TrackerIssue, TrackerNotFoundError

_LOCK_GUARD = threading.Lock()
_DIR_LOCKS: Dict[Path, threading.Lock] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_dir_lock(issues_dir: Path) -> threading.Lock:
    key = issues_dir.resolve()
    with _LOCK_GUARD:
        lock = _DIR_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _DIR_LOCKS[key] = lock
        return lock


def _serialize_issue_md(issue: TrackerIssue) -> str:
    meta = issue.to_dict()
    meta.pop("body", None)
    return f"---\n{json.dumps(meta, ensure_ascii=False)}\n---\n{issue.body}"


def _parse_issue_md(md_path: Path) -> TrackerIssue:
    raw = md_path.read_bytes().decode("utf-8")
    parts = raw.split("\n", 3)
    if len(parts) == 4 and parts[0] == "---" and parts[2] == "---":
        meta = json.loads(parts[1])
        meta["body"] = parts[3]
        return TrackerIssue.from_dict(meta)
    raise TrackerError(f"Corrupt local issue file: {md_path}")


def _load_index(issues_dir: Path) -> Dict[str, Any]:
    index_path = issues_dir / "index.json"
    if not index_path.exists():
        return {"labels": {}, "next_number": 1, "issues": {}}
    return json.loads(index_path.read_bytes().decode("utf-8"))


def _claim_issue_number(issues_dir: Path, start: int) -> int:
    candidate = max(1, start)
    while True:
        try:
            fd = os.open(issues_dir / f"{candidate}.md", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            candidate += 1
            continue
        os.close(fd)
        return candidate


class LocalTrackerBackend:
    """Filesystem-backed tracker under `<primary_root>/.edge/issues/`."""

    kind: TrackerBackendKind = "local"

    def __init__(self, repo_path: Union[str, Path]) -> None:
        self.repo_path: Path = Path(repo_path)

    @property
    def repo_root(self) -> Path:
        """Primary repository root resolved via `resolve_target_repo_root`."""
        return resolve_target_repo_root(self.repo_path)

    @property
    def issues_dir(self) -> Path:
        """Directory holding `index.json` and `<N>.md` issue records."""
        return self.repo_root / ".edge" / "issues"

    @contextmanager
    def _locked(self) -> Iterator[Path]:
        issues_dir = self.issues_dir
        issues_dir.mkdir(parents=True, exist_ok=True)
        with _get_dir_lock(issues_dir):
            yield issues_dir

    def _read_issue(self, issues_dir: Path, number: int) -> TrackerIssue:
        md_path = issues_dir / f"{int(number)}.md"
        if not md_path.exists():
            raise TrackerNotFoundError(f"Local issue #{number} not found")
        return _parse_issue_md(md_path)

    def _persist(self, issues_dir: Path, index: Dict[str, Any], *issues: TrackerIssue) -> None:
        for issue in issues:
            atomic_write_text(issues_dir / f"{issue.number}.md", _serialize_issue_md(issue))
            index.setdefault("issues", {})[str(issue.number)] = issue.to_dict()
        atomic_write_json(issues_dir / "index.json", index)

    def ensure_labels(self) -> List[str]:
        """Idempotently persist canonical labels into `.edge/issues/index.json`."""
        with self._locked() as issues_dir:
            index = _load_index(issues_dir)
            labels_map = index.setdefault("labels", {})
            for name, (color, desc) in CANONICAL_LABELS.items():
                labels_map[name] = {"color": color, "description": desc}
            atomic_write_json(issues_dir / "index.json", index)
        return list(CANONICAL_LABELS.keys())

    def create_issue(self, title: str, body: str = "", labels: Optional[Sequence[str]] = None, parent_number: Optional[int] = None) -> TrackerIssue:
        """Create `<N>.md` via `O_CREAT | O_EXCL` retry loop and update `index.json`."""
        with self._locked() as issues_dir:
            index = _load_index(issues_dir)
            parent = self._read_issue(issues_dir, parent_number) if parent_number is not None else None
            number = _claim_issue_number(issues_dir, int(index.get("next_number", 1)))
            now = _now_iso()
            issue = TrackerIssue(
                number=number, title=title, body=body, state="open", labels=list(labels or ()),
                url=f"local://issues/{number}", parent_number=parent_number, created_at=now, updated_at=now, backend="local",
            )
            index["next_number"] = number + 1
            to_save = [issue]
            if parent is not None:
                parent.subissues.append(number)
                parent.updated_at = now
                to_save.append(parent)
            self._persist(issues_dir, index, *to_save)
            return issue

    def get_issue(self, number: int, include_comments: bool = True) -> TrackerIssue:
        """Read `<N>.md` frontmatter, verbatim body, and comments."""
        with self._locked() as issues_dir:
            issue = self._read_issue(issues_dir, number)
            if not include_comments:
                issue.comments = []
            return issue

    def list_issues(self, state: str = "open", labels: Optional[Sequence[str]] = None, parent_number: Optional[int] = None, limit: int = 100) -> List[TrackerIssue]:
        """List local issues filtered by state, labels, and optional parent."""
        with self._locked() as issues_dir:
            items = [TrackerIssue.from_dict(v) for v in (_load_index(issues_dir).get("issues") or {}).values()]
        target_state = state.lower()
        return [
            item for item in sorted(items, key=lambda i: i.number)
            if (target_state == "all" or item.state == target_state)
            and (not labels or all(lbl in item.labels for lbl in labels))
            and (parent_number is None or item.parent_number == parent_number)
        ][:limit]

    def edit_issue(self, number: int, title: Optional[str] = None, body: Optional[str] = None, add_labels: Optional[Sequence[str]] = None, remove_labels: Optional[Sequence[str]] = None) -> TrackerIssue:
        """Mutate `<N>.md` and `index.json` atomically."""
        with self._locked() as issues_dir:
            index = _load_index(issues_dir)
            issue = self._read_issue(issues_dir, number)
            if title is not None:
                issue.title = title
            if body is not None:
                issue.body = body
            issue.labels = [lbl for lbl in issue.labels if lbl not in set(remove_labels or ())]
            for lbl in add_labels or ():
                if lbl not in issue.labels:
                    issue.labels.append(lbl)
            issue.updated_at = _now_iso()
            self._persist(issues_dir, index, issue)
            return issue

    def add_comment(self, number: int, body: str) -> TrackerComment:
        """Append a comment to `<N>.md` and update `index.json` atomically."""
        with self._locked() as issues_dir:
            index = _load_index(issues_dir)
            issue = self._read_issue(issues_dir, number)
            now = _now_iso()
            comment = TrackerComment(id=f"local-{len(issue.comments) + 1}", author="local", body=body, created_at=now)
            issue.comments.append(comment)
            issue.updated_at = now
            self._persist(issues_dir, index, issue)
            return comment

    def add_subissue(self, parent_number: int, child_numbers: Sequence[int]) -> List[TrackerIssue]:
        """Atomically link parent and child issues bidirectionally."""
        with self._locked() as issues_dir:
            index = _load_index(issues_dir)
            parent = self._read_issue(issues_dir, parent_number)
            now = _now_iso()
            to_save: List[TrackerIssue] = []
            updated: List[TrackerIssue] = []
            for child_num in child_numbers:
                child = self._read_issue(issues_dir, int(child_num))
                if child.parent_number is not None and child.parent_number != parent_number:
                    old_parent = self._read_issue(issues_dir, child.parent_number)
                    old_parent.subissues = [n for n in old_parent.subissues if n != child.number]
                    old_parent.updated_at = now
                    to_save.append(old_parent)
                child.parent_number, child.updated_at = parent_number, now
                if child.number not in parent.subissues:
                    parent.subissues.append(child.number)
                to_save.append(child)
                updated.append(child)
            parent.updated_at = now
            self._persist(issues_dir, index, parent, *to_save)
            return updated

    def remove_subissue(self, parent_number: int, child_numbers: Sequence[int]) -> List[TrackerIssue]:
        """Atomically unlink child issues from `parent_number`."""
        with self._locked() as issues_dir:
            index = _load_index(issues_dir)
            parent = self._read_issue(issues_dir, parent_number)
            now = _now_iso()
            updated: List[TrackerIssue] = []
            for child_num in child_numbers:
                child = self._read_issue(issues_dir, int(child_num))
                if child.parent_number == parent_number:
                    child.parent_number, child.updated_at = None, now
                parent.subissues = [n for n in parent.subissues if n != child.number]
                updated.append(child)
            parent.updated_at = now
            self._persist(issues_dir, index, parent, *updated)
            return updated

    def list_subissues(self, parent_number: int) -> List[TrackerIssue]:
        """Return child TrackerIssues linked to `parent_number`."""
        with self._locked() as issues_dir:
            parent = self._read_issue(issues_dir, parent_number)
            return [self._read_issue(issues_dir, num) for num in parent.subissues]

    def close_issue(self, number: int, comment: Optional[str] = None, reason: str = "completed") -> TrackerIssue:
        """Close issue `number` with timestamp and optional closing comment."""
        with self._locked() as issues_dir:
            index = _load_index(issues_dir)
            issue = self._read_issue(issues_dir, number)
            now = _now_iso()
            if comment is not None:
                issue.comments.append(TrackerComment(id=f"local-{len(issue.comments) + 1}", author="local", body=comment, created_at=now))
            issue.state, issue.closed_at, issue.updated_at = "closed", now, now
            self._persist(issues_dir, index, issue)
            return issue
