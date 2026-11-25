"""
Standard `gh` CLI fallback tracker backend.

Uses `gh` issue/label commands with `--body-file` for mutations and delegates
lossless reads and GraphQL sub-issue operations to `tools.tracker.graphql`.
"""

import re
from pathlib import Path
from typing import List, Optional, Sequence, Union

from tools.common.paths import normalize_target_path
from . import graphql
from .backends import run_tracker_checked, temp_body_file
from .models import CANONICAL_LABELS, TrackerBackendKind, TrackerComment, TrackerError, TrackerIssue

_ISSUE_NUM_RE = re.compile(r"(?:/issues/|#)(\d+)")


def _parse_issue_number(output: str) -> int:
    match = _ISSUE_NUM_RE.search(output or "")
    if not match:
        raise TrackerError(f"Unable to parse issue number from gh output: {output!r}")
    return int(match.group(1))


class GhCliBackend:
    """Tracker backend using standard `gh` CLI and GitHub GraphQL API."""

    kind: TrackerBackendKind = "gh"

    def __init__(self, repo_path: Union[str, Path]) -> None:
        self.repo_path: Path = normalize_target_path(repo_path)

    def ensure_labels(self) -> List[str]:
        """Idempotently ensure canonical tracker labels via `gh label create --force`."""
        for name, (color, desc) in CANONICAL_LABELS.items():
            run_tracker_checked(
                ["gh", "label", "create", name, "--color", color, "--description", desc, "--force"],
                cwd=self.repo_path,
            )
        return list(CANONICAL_LABELS.keys())

    def create_issue(
        self,
        title: str,
        body: str = "",
        labels: Optional[Sequence[str]] = None,
        parent_number: Optional[int] = None,
    ) -> TrackerIssue:
        """Create an issue via `gh issue create --body-file` and optional GraphQL subissue link."""
        with temp_body_file(body, cwd=self.repo_path) as body_path:
            cmd = ["gh", "issue", "create", "--title", title, "--body-file", body_path]
            for label in labels or ():
                cmd.extend(["--label", label])
            out = run_tracker_checked(cmd, cwd=self.repo_path)
        number = _parse_issue_number(out)
        if parent_number is not None:
            graphql.add_subissue(
                self.repo_path,
                parent_number,
                [number],
                replace_parent=True,
                backend_kind=self.kind,
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
        """Edit issue metadata, labels, or body (`--body-file`) via `gh issue edit`."""
        cmd = ["gh", "issue", "edit", str(number)]
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
        """Add an issue comment via `gh issue comment --body-file`."""
        with temp_body_file(body, cwd=self.repo_path) as body_path:
            run_tracker_checked(
                ["gh", "issue", "comment", str(number), "--body-file", body_path],
                cwd=self.repo_path,
            )
        issue = self.get_issue(number, include_comments=True)
        if issue.comments:
            return issue.comments[-1]
        return TrackerComment(id="", author="", body=body)

    def add_subissue(self, parent_number: int, child_numbers: Sequence[int]) -> List[TrackerIssue]:
        """Link child issues under `parent_number` via `graphql.add_subissue`."""
        return graphql.add_subissue(
            self.repo_path,
            parent_number,
            child_numbers,
            replace_parent=True,
            backend_kind=self.kind,
        )

    def remove_subissue(self, parent_number: int, child_numbers: Sequence[int]) -> List[TrackerIssue]:
        """Unlink child issues from `parent_number` via `graphql.remove_subissue`."""
        return graphql.remove_subissue(
            self.repo_path,
            parent_number,
            child_numbers,
            backend_kind=self.kind,
        )

    def list_subissues(self, parent_number: int) -> List[TrackerIssue]:
        """List sub-issues losslessly via `graphql.list_subissues`."""
        return graphql.list_subissues(self.repo_path, parent_number, backend_kind=self.kind)

    def close_issue(
        self,
        number: int,
        comment: Optional[str] = None,
        reason: str = "completed",
    ) -> TrackerIssue:
        """Close an issue via `gh issue close` (mapping `not_planned` -> `not planned`)."""
        gh_reason = "not planned" if reason == "not_planned" else reason
        cmd = ["gh", "issue", "close", str(number), "--reason", gh_reason]
        if comment is not None:
            cmd.extend(["--comment", comment])
        run_tracker_checked(cmd, cwd=self.repo_path)
        return self.get_issue(number)
