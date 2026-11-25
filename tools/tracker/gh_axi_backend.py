"""
`gh-axi` primary tracker backend.

Uses `gh-axi` CLI with `--body-file` for mutations and delegates lossless reads
and paginated sub-issue queries to `tools.tracker.graphql`.
"""

import re
from pathlib import Path
from typing import List, Optional, Sequence, Union

from tools.common.paths import normalize_target_path
from . import graphql
from .backends import classify_tracker_error, run_tracker_checked, run_tracker_cmd, temp_body_file
from .models import CANONICAL_LABELS, TrackerBackendKind, TrackerComment, TrackerError, TrackerIssue

_ISSUE_NUM_RE = re.compile(r"(?:number:\s*|/issues/|#)(\d+)")


def _parse_issue_number(output: str) -> int:
    match = _ISSUE_NUM_RE.search(output or "")
    if not match:
        raise TrackerError(f"Unable to parse issue number from gh-axi output: {output!r}")
    return int(match.group(1))


class GhAxiBackend:
    """Tracker backend delegating mutations to `gh-axi` and reads to GraphQL."""

    kind: TrackerBackendKind = "gh-axi"

    def __init__(self, repo_path: Union[str, Path]) -> None:
        self.repo_path: Path = normalize_target_path(repo_path)

    def ensure_labels(self) -> List[str]:
        """Idempotently ensure canonical tracker labels via `gh-axi label create`."""
        for name, (color, desc) in CANONICAL_LABELS.items():
            cmd = ["gh-axi", "label", "create", "--name", name, "--color", color, "--description", desc]
            rc, out, err = run_tracker_cmd(cmd, cwd=self.repo_path, strip=True)
            if rc != 0 and "already exists" not in f"{err}\n{out}".lower():
                raise classify_tracker_error(rc, out, err, tool="gh-axi")
        return list(CANONICAL_LABELS.keys())

    def create_issue(
        self,
        title: str,
        body: str = "",
        labels: Optional[Sequence[str]] = None,
        parent_number: Optional[int] = None,
    ) -> TrackerIssue:
        """Create an issue via `gh-axi issue create --body-file` and optional subissue link."""
        with temp_body_file(body, cwd=self.repo_path) as body_path:
            cmd = ["gh-axi", "issue", "create", "--title", title, "--body-file", body_path]
            for label in labels or ():
                cmd.extend(["--label", label])
            out = run_tracker_checked(cmd, cwd=self.repo_path)
        number = _parse_issue_number(out)
        if parent_number is not None:
            run_tracker_checked(
                ["gh-axi", "issue", "subissue", "add", str(parent_number), str(number)],
                cwd=self.repo_path,
            )
        return self.get_issue(number)

    def get_issue(self, number: int, include_comments: bool = True) -> TrackerIssue:
        """Fetch an issue losslessly via `graphql.fetch_issue`."""
        return graphql.fetch_issue(
            self.repo_path,
            number,
            include_comments=include_comments,
            backend_kind=self.kind,
        )

    def list_issues(
        self,
        state: str = "open",
        labels: Optional[Sequence[str]] = None,
        parent_number: Optional[int] = None,
        limit: int = 100,
    ) -> List[TrackerIssue]:
        """List issues losslessly via `graphql.list_issues`."""
        return graphql.list_issues(
            self.repo_path,
            state=state,
            labels=labels,
            parent_number=parent_number,
            limit=limit,
            backend_kind=self.kind,
        )

    def edit_issue(
        self,
        number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        add_labels: Optional[Sequence[str]] = None,
        remove_labels: Optional[Sequence[str]] = None,
    ) -> TrackerIssue:
        """Edit issue metadata, labels, or body (`--body-file`) via `gh-axi issue edit`."""
        cmd = ["gh-axi", "issue", "edit", str(number)]
        if title is not None:
            cmd.extend(["--title", title])
        for label in add_labels or ():
            cmd.extend(["--add-label", label])
        for label in remove_labels or ():
            cmd.extend(["--remove-label", label])
        if body is not None:
            with temp_body_file(body, cwd=self.repo_path) as body_path:
                run_tracker_checked([*cmd, "--body-file", body_path], cwd=self.repo_path)
        elif len(cmd) > 4:
            run_tracker_checked(cmd, cwd=self.repo_path)
        return self.get_issue(number)

    def add_comment(self, number: int, body: str) -> TrackerComment:
        """Add an issue comment via `gh-axi issue comment --body-file`."""
        with temp_body_file(body, cwd=self.repo_path) as body_path:
            run_tracker_checked(
                ["gh-axi", "issue", "comment", str(number), "--body-file", body_path],
                cwd=self.repo_path,
            )
        issue = self.get_issue(number, include_comments=True)
        if issue.comments:
            return issue.comments[-1]
        return TrackerComment(id="", author="", body=body)

    def add_subissue(self, parent_number: int, child_numbers: Sequence[int]) -> List[TrackerIssue]:
        """Link child issues under `parent_number` via `gh-axi issue subissue add`."""
        if not child_numbers:
            return []
        cmd = ["gh-axi", "issue", "subissue", "add", str(parent_number), *[str(int(c)) for c in child_numbers]]
        run_tracker_checked(cmd, cwd=self.repo_path)
        return [self.get_issue(int(c), include_comments=False) for c in child_numbers]

    def remove_subissue(self, parent_number: int, child_numbers: Sequence[int]) -> List[TrackerIssue]:
        """Unlink child issues from `parent_number` via `gh-axi issue subissue remove`."""
        for child in child_numbers:
            run_tracker_checked(
                ["gh-axi", "issue", "subissue", "remove", str(parent_number), str(int(child))],
                cwd=self.repo_path,
            )
        return [self.get_issue(int(c), include_comments=False) for c in child_numbers]

    def list_subissues(self, parent_number: int) -> List[TrackerIssue]:
        """List sub-issues losslessly via `graphql.list_subissues`."""
        return graphql.list_subissues(self.repo_path, parent_number, backend_kind=self.kind)

    def close_issue(
        self,
        number: int,
        comment: Optional[str] = None,
        reason: str = "completed",
    ) -> TrackerIssue:
        """Close an issue via `gh-axi issue close`."""
        cmd = ["gh-axi", "issue", "close", str(number), "--reason", reason]
        if comment is not None:
            cmd.extend(["--comment", comment])
        run_tracker_checked(cmd, cwd=self.repo_path)
        return self.get_issue(number)
