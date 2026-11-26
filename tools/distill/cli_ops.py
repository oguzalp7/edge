"""Budget check, session/intent mining, and factory inbox subcommands for edge-distill."""

import argparse
import json
from pathlib import Path
import sys
from typing import List, Optional, Tuple

from tools.common import normalize_target_path, toon_encode
from tools.distill.session_miner import SessionMiner
from tools.distill.state import FactoryInbox, collect_budget_targets


def _resolve_budget_targets(p: Path, max_lines_override: Optional[int]) -> List[Tuple[Path, int]]:
    targets = collect_budget_targets(p)
    fallback_limit = max_lines_override or 60
    if not targets and p.is_dir():
        return [(f, fallback_limit) for f in sorted(p.glob("*.md"))]
    return targets or [(p, fallback_limit)]


def _check_and_print_targets(targets: List[Tuple[Path, int]], override_limit: Optional[int]) -> bool:
    all_ok = True
    for f, def_limit in targets:
        lim = override_limit or def_limit
        cnt = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
        if cnt <= lim:
            print(f"PASS: {f.name} has {cnt} lines (budget <= {lim})")
        else:
            print(f"FAIL: {f.name} has {cnt} lines (budget <= {lim} exceeded)", file=sys.stderr)
            all_ok = False
    return all_ok


def cmd_check_budget(args: argparse.Namespace) -> int:
    """Verify physical line-count budgets for rubrics and profile agents."""
    raw_path = getattr(args, "path", None)
    if not raw_path:
        print("Error: path is required", file=sys.stderr)
        return 1
    p = Path(raw_path).resolve()
    if not p.exists():
        print(f"Error: path does not exist: {p}", file=sys.stderr)
        return 1
    override_limit = getattr(args, "max_lines", None)
    return 0 if _check_and_print_targets(_resolve_budget_targets(p, override_limit), override_limit) else 1


def _extract_brain_roots(args: argparse.Namespace) -> Optional[List[Path]]:
    arg = getattr(args, "brain_roots", None)
    if isinstance(arg, list):
        return [Path(r) for r in arg]
    return [Path(arg)] if arg else None


def cmd_sessions(args: argparse.Namespace) -> int:
    """Mine Antigravity session transcripts for time/project summary."""
    repo = normalize_target_path(getattr(args, "repo", "."))
    miner = SessionMiner(brain_roots=_extract_brain_roots(args), repo_path=repo)
    data = miner.mine_sessions()
    if getattr(args, "output", None):
        miner.save_sessions_json(data, output_path=args.output)
    fmt = getattr(args, "format", "human")
    print(toon_encode({"sessions_summary": data}) if fmt == "toon" else miner.format_sessions_report(data, by_project=getattr(args, "by_project", False)))
    return 0


def cmd_intents(args: argparse.Namespace) -> int:
    """Mine architectural user intents across session transcripts."""
    repo = normalize_target_path(getattr(args, "repo", "."))
    miner = SessionMiner(brain_roots=_extract_brain_roots(args), repo_path=repo)
    data = miner.mine_sessions()
    if getattr(args, "output", None):
        miner.save_sessions_json(data, output_path=args.output)
    fmt = getattr(args, "format", "human")
    print(toon_encode({"intents_summary": data}) if fmt == "toon" else miner.format_intents_report(data))
    return 0


def _cmd_inbox_list(args: argparse.Namespace, inbox: FactoryInbox) -> int:
    signals = inbox.load_pending() if getattr(args, "pending_only", False) else inbox.load_signals()
    if getattr(args, "format", "human") == "json":
        print(json.dumps({"signals": signals}, indent=2))
        return 0
    if not signals:
        print("Factory inbox is empty.")
        return 0
    print(f"Factory inbox ({len(signals)} signal(s)):")
    for s in signals:
        status = "resolved" if s.get("resolved") else "pending"
        print(f"- [{s.get('signal_id', '')}] ({status}, {s.get('role_or_tool', '')}) {str(s.get('summary', '')).splitlines()[0][:80]}")
    return 0


def _cmd_inbox_prune(args: argparse.Namespace, inbox: FactoryInbox) -> int:
    res = inbox.prune(
        drop_exit_zero=not getattr(args, "no_drop_exit_zero", False),
        drop_benign_tools=not getattr(args, "no_drop_benign_tools", False),
        resolved_only=getattr(args, "resolved_only", False),
        max_age_days=getattr(args, "max_age_days", None),
        project=getattr(args, "project", None),
        dry_run=getattr(args, "dry_run", False),
    )
    if getattr(args, "format", "human") == "json":
        print(json.dumps(res, indent=2))
    else:
        tag = "[DRY-RUN] " if res["dry_run"] else ""
        print(f"{tag}Pruned {res['removed']} signal(s) ({res['before']} -> {res['after']}): {res['removed_by_reason']}")
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    """List, prune, or clear factory inbox signals."""
    action, inbox = getattr(args, "action", None) or "list", FactoryInbox()
    if action == "prune":
        return _cmd_inbox_prune(args, inbox)
    if action == "clear":
        inbox.clear()
        print("Cleared factory inbox")
        return 0
    return _cmd_inbox_list(args, inbox)
