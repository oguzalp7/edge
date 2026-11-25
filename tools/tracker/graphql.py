"""
Lossless GitHub GraphQL reads and native sub-issue mutations via `gh api graphql`.

Used by both GhAxiBackend (because `gh-axi api` converts responses to TOON) and
GhCliBackend for lossless Markdown bodies, comments, and paginated sub-issues.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from tools.common.paths import normalize_target_path
from .backends import classify_tracker_error, run_tracker_checked
from .models import TrackerBackendKind, TrackerError, TrackerIssue, TrackerNotFoundError

_REMOTE_NWO_RE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$")

_ISSUE_FIELDS = (
    "id number title body state url createdAt updatedAt closedAt "
    "labels(first: 50) { nodes { name } } parent { number } "
    "subIssues(first: 100) { pageInfo { hasNextPage endCursor } nodes { number } }"
)
_COMMENTS_FIELD = "comments(first: $commentLimit) { pageInfo { hasNextPage endCursor } nodes { id author { login } body createdAt } }"

_FETCH_ISSUE_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!, $commentLimit: Int!) { "
    f"repository(owner: $owner, name: $name) {{ issue(number: $number) {{ {_ISSUE_FIELDS} {_COMMENTS_FIELD} }} }} }}"
)

_LIST_ISSUES_QUERY = (
    "query($owner: String!, $name: String!, $first: Int!, $after: String, $states: [IssueState!], $labels: [String!]) { "
    "repository(owner: $owner, name: $name) { "
    "issues(first: $first, after: $after, states: $states, labels: $labels, orderBy: {field: CREATED_AT, direction: DESC}) { "
    f"pageInfo {{ hasNextPage endCursor }} nodes {{ {_ISSUE_FIELDS} "
    "comments(first: 20) { pageInfo { hasNextPage endCursor } nodes { id author { login } body createdAt } } } } } }"
)

_LIST_SUBISSUES_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!, $after: String) { "
    "repository(owner: $owner, name: $name) { issue(number: $number) { number "
    "subIssues(first: 100, after: $after) { pageInfo { hasNextPage endCursor } "
    "nodes { id number title body state url createdAt updatedAt closedAt "
    "labels(first: 50) { nodes { name } } parent { number } } } } } }"
)


def resolve_repo_nwo(repo_path: Union[str, Path]) -> Tuple[str, str]:
    """Resolve ``(owner, name)`` for ``repo_path`` from git remotes or ``gh repo view``."""
    norm = normalize_target_path(repo_path)
    try:
        proc = subprocess.run(["git", "remote", "get-url", "origin"], cwd=str(norm), capture_output=True, text=True, timeout=10)
        if proc.returncode == 0 and proc.stdout.strip():
            match = _REMOTE_NWO_RE.search(proc.stdout.strip())
            if match:
                return match.group(1), match.group(2)
    except Exception:
        pass
    out = run_tracker_checked(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=norm, strip=True)
    if "/" in out:
        owner, name = out.split("/", 1)
        return owner.strip(), name.strip()
    raise TrackerError(f"Could not resolve GitHub owner/name for {norm}")


def _raise_graphql_errors(errors: List[Dict[str, Any]]) -> None:
    msg = "; ".join(str(err.get("message") or err) for err in errors)
    is_missing = any(err.get("type") == "NOT_FOUND" for err in errors) or "could not resolve to an issue" in msg.lower()
    if is_missing:
        raise TrackerNotFoundError(msg)
    raise classify_tracker_error(1, "", msg, tool="gh")


def _append_gql_var(cmd: List[str], key: str, value: Any) -> None:
    if isinstance(value, bool):
        cmd.extend(["-F", f"{key}={'true' if value else 'false'}"])
    elif isinstance(value, int):
        cmd.extend(["-F", f"{key}={value}"])
    elif isinstance(value, list):
        for item in value:
            cmd.extend(["-f", f"{key}[]={item}"])
    else:
        cmd.extend(["-f", f"{key}={value}"])


def run_graphql(query: str, variables: Dict[str, Any], cwd: Union[str, Path]) -> Dict[str, Any]:
    """Execute ``gh api graphql`` and return parsed ``data`` dictionary."""
    cmd: List[str] = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is not None:
            _append_gql_var(cmd, key, value)
    raw = run_tracker_checked(cmd, cwd=cwd, strip=False)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TrackerError(f"Invalid JSON from gh api graphql: {exc}") from exc
    if payload.get("errors"):
        _raise_graphql_errors(payload["errors"])
    return payload.get("data") or {}


def _unwrap_nodes(raw_value: Any) -> Any:
    if isinstance(raw_value, dict) and isinstance(raw_value.get("nodes"), list):
        return raw_value["nodes"]
    return raw_value


def _node_to_issue(node: Dict[str, Any], backend_kind: TrackerBackendKind) -> TrackerIssue:
    normalized = dict(node)
    normalized["labels"] = _unwrap_nodes(node.get("labels"))
    normalized["subissues"] = _unwrap_nodes(node.get("subIssues") if "subIssues" in node else node.get("subissues"))
    normalized["comments"] = _unwrap_nodes(node.get("comments"))
    normalized["backend"] = backend_kind
    return TrackerIssue.from_dict(normalized)


def fetch_node_id(repo_path: Union[str, Path], number: int) -> str:
    """Fetch the GraphQL node ID for issue ``number``."""
    owner, name = resolve_repo_nwo(repo_path)
    query = "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){issue(number:$number){id number}}}"
    data = run_graphql(query, {"owner": owner, "name": name, "number": int(number)}, repo_path)
    issue = (data.get("repository") or {}).get("issue")
    if not issue or not issue.get("id"):
        raise TrackerNotFoundError(f"Issue #{number} not found")
    return str(issue["id"])


_node_id = fetch_node_id


def fetch_issue(
    repo_path: Union[str, Path],
    number: int,
    *,
    include_comments: bool = True,
    backend_kind: TrackerBackendKind = "gh-axi",
) -> TrackerIssue:
    """Fetch a single issue losslessly via ``gh api graphql``."""
    owner, name = resolve_repo_nwo(repo_path)
    comment_limit = 100 if include_comments else 0
    data = run_graphql(_FETCH_ISSUE_QUERY, {"owner": owner, "name": name, "number": int(number), "commentLimit": comment_limit}, repo_path)
    node = (data.get("repository") or {}).get("issue")
    if not node:
        raise TrackerNotFoundError(f"Issue #{number} not found")
    return _node_to_issue(node, backend_kind)


def _matches_filters(issue: TrackerIssue, labels: Optional[Sequence[str]], parent_number: Optional[int]) -> bool:
    if labels and not all(lbl in issue.labels for lbl in labels):
        return False
    return parent_number is None or issue.parent_number == parent_number


def _next_cursor(conn: Dict[str, Any]) -> Optional[str]:
    page_info = conn.get("pageInfo") or {}
    if page_info.get("hasNextPage") and page_info.get("endCursor"):
        return str(page_info["endCursor"])
    return None


def list_issues(
    repo_path: Union[str, Path],
    *,
    state: str = "open",
    labels: Optional[Sequence[str]] = None,
    parent_number: Optional[int] = None,
    limit: int = 100,
    backend_kind: TrackerBackendKind = "gh-axi",
) -> List[TrackerIssue]:
    """List issues losslessly via ``gh api graphql`` with optional filters."""
    owner, name = resolve_repo_nwo(repo_path)
    states = {"open": ["OPEN"], "closed": ["CLOSED"], "all": ["OPEN", "CLOSED"]}.get(state.lower(), ["OPEN"])
    results: List[TrackerIssue] = []
    cursor: Optional[str] = None
    while len(results) < limit:
        variables = {"owner": owner, "name": name, "first": min(100, limit - len(results)), "after": cursor, "states": states, "labels": list(labels or ()) or None}
        conn = (run_graphql(_LIST_ISSUES_QUERY, variables, repo_path).get("repository") or {}).get("issues") or {}
        items = [_node_to_issue(node, backend_kind) for node in conn.get("nodes") or ()]
        results.extend(item for item in items if _matches_filters(item, labels, parent_number))
        cursor = _next_cursor(conn)
        if not cursor:
            break
    return results[:limit]


def list_subissues(repo_path: Union[str, Path], parent_number: int, *, backend_kind: TrackerBackendKind = "gh-axi") -> List[TrackerIssue]:
    """List all child sub-issues of ``parent_number`` with cursor pagination."""
    owner, name = resolve_repo_nwo(repo_path)
    results: List[TrackerIssue] = []
    cursor: Optional[str] = None
    while True:
        data = run_graphql(_LIST_SUBISSUES_QUERY, {"owner": owner, "name": name, "number": int(parent_number), "after": cursor}, repo_path)
        issue = (data.get("repository") or {}).get("issue")
        if not issue:
            raise TrackerNotFoundError(f"Issue #{parent_number} not found")
        conn = issue.get("subIssues") or {}
        results.extend(_node_to_issue(node, backend_kind) for node in conn.get("nodes") or ())
        cursor = _next_cursor(conn)
        if not cursor:
            break
    return results


def _mutate_subissues(
    repo_path: Union[str, Path],
    parent_number: int,
    child_numbers: Sequence[int],
    *,
    mutation_name: str,
    replace_parent: Optional[bool],
    backend_kind: TrackerBackendKind,
) -> List[TrackerIssue]:
    if not child_numbers:
        return []
    parent_id = fetch_node_id(repo_path, parent_number)
    extra_var = ", $replaceParent: Boolean!" if replace_parent is not None else ""
    extra_arg = ", replaceParent: $replaceParent" if replace_parent is not None else ""
    query = (
        f"mutation($parentId: ID!, $childId: ID!{extra_var}) {{ "
        f"{mutation_name}(input: {{issueId: $parentId, subIssueId: $childId{extra_arg}}}) {{ "
        f"issue {{ number }} subIssue {{ {_ISSUE_FIELDS} }} }} }}"
    )
    updated: List[TrackerIssue] = []
    for child in child_numbers:
        variables: Dict[str, Any] = {"parentId": parent_id, "childId": fetch_node_id(repo_path, int(child))}
        if replace_parent is not None:
            variables["replaceParent"] = replace_parent
        sub_node = (run_graphql(query, variables, repo_path).get(mutation_name) or {}).get("subIssue")
        updated.append(_node_to_issue(sub_node, backend_kind) if sub_node else fetch_issue(repo_path, int(child), include_comments=False, backend_kind=backend_kind))
    return updated


def add_subissue(repo_path: Union[str, Path], parent_number: int, child_numbers: Sequence[int], *, replace_parent: bool = True, backend_kind: TrackerBackendKind = "gh") -> List[TrackerIssue]:
    """Attach child issues to ``parent_number`` via GraphQL ``addSubIssue``."""
    return _mutate_subissues(repo_path, parent_number, child_numbers, mutation_name="addSubIssue", replace_parent=replace_parent, backend_kind=backend_kind)


def remove_subissue(repo_path: Union[str, Path], parent_number: int, child_numbers: Sequence[int], *, backend_kind: TrackerBackendKind = "gh") -> List[TrackerIssue]:
    """Detach child issues from ``parent_number`` via GraphQL ``removeSubIssue``."""
    return _mutate_subissues(repo_path, parent_number, child_numbers, mutation_name="removeSubIssue", replace_parent=None, backend_kind=backend_kind)
