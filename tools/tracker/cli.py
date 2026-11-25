"""
Deterministic CLI entry point for Edge Tracker (`python3 -m tools.tracker.cli`).

Supports `--offline`, `--backend auto|gh-axi|gh|local`, `--json`, and the 9
subcommands: init-labels, create, view, edit, comment, list, subissue, close,
and cache-spec. Exit codes: 0 success, 1 general/not-found/403, 2 TrackerAuthError.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

# Support direct script execution (`python3 tools/tracker/cli.py`)
_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from tools.tracker.backends import TrackerBackend, resolve_backend
from tools.tracker.cache import cache_issue_spec
from tools.tracker.models import TrackerAuthError, TrackerError


def _make_common_parser(*, pre: bool) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    prefix = "_pre_" if pre else ""
    common.add_argument("--offline", action="store_true", default=False, dest=f"{prefix}offline", help="Force local backend")
    common.add_argument("--backend", choices=["auto", "gh-axi", "gh", "local"], default="auto", dest=f"{prefix}backend")
    common.add_argument("--json", action="store_true", default=False, dest=f"{prefix}json_out", help="JSON output")
    return common


def _add_body_args(parser: argparse.ArgumentParser, required: bool = False) -> None:
    group = parser.add_mutually_exclusive_group(required=required)
    group.add_argument("--body", default=None)
    group.add_argument("--body-file", default=None)


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser for all 9 tracker subcommands."""
    pre_common, sub_common = _make_common_parser(pre=True), _make_common_parser(pre=False)
    parser = argparse.ArgumentParser(prog="tools.tracker.cli", parents=[pre_common])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-labels", parents=[sub_common]).add_argument("repo")

    p_create = sub.add_parser("create", parents=[sub_common])
    p_create.add_argument("repo")
    p_create.add_argument("--title", required=True)
    _add_body_args(p_create)
    p_create.add_argument("--label", action="append", default=[])
    p_create.add_argument("--parent", type=int, default=None)

    p_view = sub.add_parser("view", parents=[sub_common])
    p_view.add_argument("repo")
    p_view.add_argument("number", type=int)
    p_view.add_argument("--comments", action="store_true")
    p_view.add_argument("--cache", action="store_true")

    p_edit = sub.add_parser("edit", parents=[sub_common])
    p_edit.add_argument("repo")
    p_edit.add_argument("number", type=int)
    p_edit.add_argument("--title", default=None)
    _add_body_args(p_edit)
    p_edit.add_argument("--add-label", action="append", default=[])
    p_edit.add_argument("--remove-label", action="append", default=[])

    p_comment = sub.add_parser("comment", parents=[sub_common])
    p_comment.add_argument("repo")
    p_comment.add_argument("number", type=int)
    _add_body_args(p_comment, required=True)

    p_list = sub.add_parser("list", parents=[sub_common])
    p_list.add_argument("repo")
    p_list.add_argument("--state", choices=["open", "closed", "all"], default="open")
    p_list.add_argument("--label", action="append", default=[])
    p_list.add_argument("--parent", type=int, default=None)
    p_list.add_argument("--limit", type=int, default=100)

    p_sub = sub.add_parser("subissue", parents=[sub_common])
    p_sub.add_argument("repo")
    p_sub.add_argument("action", choices=["add", "remove", "list"])
    p_sub.add_argument("parent", type=int)
    p_sub.add_argument("children", nargs="*", type=int)

    p_close = sub.add_parser("close", parents=[sub_common])
    p_close.add_argument("repo")
    p_close.add_argument("number", type=int)
    p_close.add_argument("--comment", default=None)
    p_close.add_argument("--reason", choices=["completed", "not_planned"], default="completed")

    p_cache = sub.add_parser("cache-spec", parents=[sub_common])
    p_cache.add_argument("repo")
    p_cache.add_argument("number", type=int)
    return parser


def _merge_global_flags(args: argparse.Namespace) -> None:
    args.offline = bool(args.offline or getattr(args, "_pre_offline", False))
    args.json_out = bool(args.json_out or getattr(args, "_pre_json_out", False))
    pre_backend = getattr(args, "_pre_backend", "auto")
    if args.backend == "auto" and pre_backend != "auto":
        args.backend = pre_backend


def _read_body_arg(args: argparse.Namespace) -> Optional[str]:
    if getattr(args, "body_file", None):
        return Path(args.body_file).read_bytes().decode("utf-8")
    return getattr(args, "body", None)


def _emit(payload: Any, text: str, json_out: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False) if json_out else text)


def _cmd_init_labels(backend: TrackerBackend, args: argparse.Namespace) -> None:
    labels = backend.ensure_labels()
    _emit(labels, ", ".join(labels), args.json_out)


def _cmd_create(backend: TrackerBackend, args: argparse.Namespace) -> None:
    issue = backend.create_issue(args.title, _read_body_arg(args) or "", args.label, args.parent)
    _emit(issue.to_dict(), f"#{issue.number} {issue.url}".strip(), args.json_out)


def _cmd_view(backend: TrackerBackend, args: argparse.Namespace) -> None:
    issue = backend.get_issue(args.number, include_comments=args.comments)
    if args.cache:
        cache_issue_spec(args.repo, issue)
    _emit(issue.to_dict(), f"#{issue.number} [{issue.state}] {issue.title}", args.json_out)


def _cmd_edit(backend: TrackerBackend, args: argparse.Namespace) -> None:
    issue = backend.edit_issue(args.number, args.title, _read_body_arg(args), args.add_label, args.remove_label)
    _emit(issue.to_dict(), f"#{issue.number} updated", args.json_out)


def _cmd_comment(backend: TrackerBackend, args: argparse.Namespace) -> None:
    comment = backend.add_comment(args.number, _read_body_arg(args) or "")
    _emit(comment.to_dict(), f"Comment added to #{args.number}", args.json_out)


def _cmd_list(backend: TrackerBackend, args: argparse.Namespace) -> None:
    items = backend.list_issues(args.state, args.label or None, args.parent, args.limit)
    _emit([i.to_dict() for i in items], "\n".join(f"#{i.number} [{i.state}] {i.title}" for i in items), args.json_out)


def _cmd_subissue(backend: TrackerBackend, args: argparse.Namespace) -> None:
    ops = {"list": lambda: backend.list_subissues(args.parent), "add": lambda: backend.add_subissue(args.parent, args.children), "remove": lambda: backend.remove_subissue(args.parent, args.children)}
    items = [i.to_dict() for i in ops[args.action]()]
    _emit(items, "\n".join(f"#{i['number']} {i['title']}" for i in items), args.json_out)


def _cmd_close(backend: TrackerBackend, args: argparse.Namespace) -> None:
    issue = backend.close_issue(args.number, comment=args.comment, reason=args.reason)
    _emit(issue.to_dict(), f"#{issue.number} closed", args.json_out)


def _cmd_cache_spec(backend: TrackerBackend, args: argparse.Namespace) -> None:
    issue = backend.get_issue(args.number, include_comments=True)
    path = cache_issue_spec(args.repo, issue)
    _emit({"number": issue.number, "path": str(path)}, str(path), args.json_out)


_DISPATCH: Dict[str, Callable[[TrackerBackend, argparse.Namespace], None]] = {
    "init-labels": _cmd_init_labels,
    "create": _cmd_create,
    "view": _cmd_view,
    "edit": _cmd_edit,
    "comment": _cmd_comment,
    "list": _cmd_list,
    "subissue": _cmd_subissue,
    "close": _cmd_close,
    "cache-spec": _cmd_cache_spec,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Execute tracker CLI command and return deterministic exit code (0, 1, or 2)."""
    try:
        args = build_parser().parse_args(argv)
        _merge_global_flags(args)
        backend = resolve_backend(args.repo, backend=args.backend, offline=args.offline)
        _DISPATCH[args.command](backend, args)
        return 0
    except TrackerAuthError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    except TrackerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


if __name__ == "__main__":
    sys.exit(main())
