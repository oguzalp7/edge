"""
Domain models, exception hierarchy, and canonical label taxonomy for Edge Tracker.

Pure Python >= 3.11 standard library module (`INV-TRACKER-STDLIB-ONLY`).
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

TrackerBackendKind = Literal["gh-axi", "gh", "local"]


class TrackerError(Exception):
    """Base exception for tracker adapter errors (CLI exit code 1)."""

    exit_code: int = 1

    def __init__(self, message: str, exit_code: Optional[int] = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class TrackerAuthError(TrackerError):
    """Fail-fast error for missing binary, auth, or network failure (CLI exit code 2)."""

    exit_code: int = 2


class TrackerNotFoundError(TrackerError):
    """Raised when a requested issue or parent/child reference is missing (CLI exit code 1)."""

    exit_code: int = 1


CANONICAL_LABELS: Dict[str, Tuple[str, str]] = {
    "type:frontier": ("5319e7", "Frontier discovery item or specification epic"),
    "spec:draft": ("fbca04", "Draft specification awaiting review"),
    "spec:approved": ("0e8a16", "Approved specification ready for slicing"),
    "status:ready": ("1d76db", "Ready for brigade slice execution"),
    "status:in-progress": ("006b75", "Currently active in a brigade slice"),
    "status:done": ("6f42c1", "Completed and verified"),
    "track:feature": ("a2eeef", "Feature delivery track"),
    "track:core": ("0075ca", "Core infrastructure or domain track"),
    "track:ui": ("d4c5f9", "User interface track"),
    "track:bug": ("d73a4a", "Defect or regression fix track"),
}


def _coerce_author(raw_author: Any) -> str:
    if isinstance(raw_author, dict):
        return str(raw_author.get("login") or "")
    if raw_author is None:
        return ""
    return str(raw_author)


def _coerce_labels(raw_labels: Any) -> List[str]:
    if not isinstance(raw_labels, list):
        return []
    result: List[str] = []
    for item in raw_labels:
        if isinstance(item, dict):
            name = item.get("name")
            if name:
                result.append(str(name))
        elif item is not None:
            result.append(str(item))
    return result


def _coerce_subissues(raw_subissues: Any) -> List[int]:
    if not isinstance(raw_subissues, list):
        return []
    result: List[int] = []
    for item in raw_subissues:
        if isinstance(item, dict) and item.get("number") is not None:
            result.append(int(item["number"]))
        elif item is not None:
            result.append(int(item))
    return result


def _coerce_parent_number(raw_parent: Any) -> Optional[int]:
    if raw_parent is None:
        return None
    if isinstance(raw_parent, dict):
        num = raw_parent.get("number")
        return int(num) if num is not None else None
    return int(raw_parent)


@dataclass
class TrackerComment:
    """Canonical representation of an issue comment."""

    id: str
    author: str
    body: str
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize comment to a JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackerComment":
        """Deserialize a comment dictionary tolerating missing or extra keys."""
        raw_body = data.get("body")
        body = raw_body if isinstance(raw_body, str) else ""
        created = data.get("created_at")
        if created is None:
            created = data.get("createdAt")
        return cls(
            id=str(data.get("id") or ""),
            author=_coerce_author(data.get("author")),
            body=body,
            created_at=str(created or ""),
        )


def _pick_str(data: Dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        if key in data and data[key] is not None:
            return str(data[key])
    return default


def _pick_optional_str(data: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        if key in data and data[key] is not None:
            return str(data[key])
    return None


def _coerce_comments(raw_comments: Any) -> List[TrackerComment]:
    if not isinstance(raw_comments, list):
        return []
    result: List[TrackerComment] = []
    for item in raw_comments:
        if isinstance(item, TrackerComment):
            result.append(item)
        elif isinstance(item, dict):
            result.append(TrackerComment.from_dict(item))
    return result


@dataclass
class TrackerIssue:
    """Canonical representation of a GitHub or local tracker issue."""

    number: int
    title: str
    body: str = ""
    state: str = "open"
    labels: List[str] = field(default_factory=list)
    url: str = ""
    parent_number: Optional[int] = None
    subissues: List[int] = field(default_factory=list)
    comments: List[TrackerComment] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    closed_at: Optional[str] = None
    backend: str = "local"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize issue and nested comments to a JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackerIssue":
        """Deserialize an issue dictionary tolerating missing or extra keys."""
        raw_body = data.get("body")
        body = raw_body if isinstance(raw_body, str) else ""
        parent_val = data.get("parent_number") if "parent_number" in data else data.get("parent")
        return cls(
            number=int(data.get("number", 0)),
            title=_pick_str(data, "title"),
            body=body,
            state=_pick_str(data, "state", default="open").lower(),
            labels=_coerce_labels(data.get("labels")),
            url=_pick_str(data, "url"),
            parent_number=_coerce_parent_number(parent_val),
            subissues=_coerce_subissues(data.get("subissues")),
            comments=_coerce_comments(data.get("comments")),
            created_at=_pick_str(data, "created_at", "createdAt"),
            updated_at=_pick_str(data, "updated_at", "updatedAt"),
            closed_at=_pick_optional_str(data, "closed_at", "closedAt"),
            backend=_pick_str(data, "backend", default="local"),
        )
