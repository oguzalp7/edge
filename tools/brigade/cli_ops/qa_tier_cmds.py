"""Distill, QA React Fiber inspector, Lavish prototype bridge, and Tier CLI commands."""

import argparse
import json
from pathlib import Path
import shlex
import sys
from typing import Optional

from tools.brigade.cli_ops._facade import resolve_symbol
from tools.common import normalize_target_path


def cmd_distill(args: argparse.Namespace) -> int:
    """Forward arguments to edge-distill CLI."""
    from tools.distill.cli import main as distill_main
    return distill_main(getattr(args, "distill_args", []))


def cmd_qa_inspect(args: argparse.Namespace) -> int:
    """Locate React Fiber component and optionally stage frontier finding."""
    from tools.brigade.qa_fiber import inspect_fiber
    from tools.tracker.models import TrackerAuthError

    repo_path = normalize_target_path(getattr(args, "repo", "."))
    try:
        res = inspect_fiber(
            query=args.query, repo_path_str=repo_path,
            log_frontier=args.frontier or bool(getattr(args, "issue", None)),
            issue=getattr(args, "issue", "") or "", category=getattr(args, "category", None),
            offline=bool(getattr(args, "offline", False)),
        )
    except TrackerAuthError as exc:
        print(f"Error: {exc}")
        return exc.exit_code
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("success") else 1
    if not res.get("success"):
        print(f"❌ Fiber Inspection Failed: {res.get('error')}")
        return 1
    el, loc = res["element"], res.get("location")
    print("🎯 React Component Located Successfully:")
    print(f"   Query:       {res['query']}\n   Component:   {res['component']}")
    print(f"   Source File: {loc['file']}:{loc['line']}" if loc else "   Source File: (Could not resolve source file in repo)")
    print(f"   Element:     <{el['tag']}> \"{el['text']}\"")
    if el.get("classes"):
        print(f"   Classes:     {el['classes']}")
    print(f"   Hierarchy:   {' > '.join(res['hierarchy'][:4])}")
    if res.get("frontier"):
        f_res = res["frontier"]
        if not f_res.get("success"):
            print(f"\n⚠️ Frontier Staging Failed: {f_res.get('error')}")
            return 1
        print(f"\n📋 Staged to tracker frontier:\n   ID:    {f_res.get('id')}\n   Title: {f_res.get('title')}\n   Via:   {f_res.get('method')}")
    return 0


def _resolve_proto_wsl(repo_path: Path, raw_file: Optional[str], must_exist: bool) -> Optional[str]:
    if not raw_file:
        print("❌ --file is required. Example: --file .lavish/feature.html")
        return None
    html_file = Path(raw_file) if Path(raw_file).is_absolute() else (repo_path / raw_file)
    if must_exist and not html_file.exists():
        print(f"❌ HTML file not found: {html_file}")
        return None
    from tools.common.paths import to_wsl_path
    return str(to_wsl_path(html_file))


def cmd_prototype(args: argparse.Namespace) -> int:
    """Run lavish-axi interactive UI prototype bridge actions."""
    repo_path, action = normalize_target_path(args.repo), args.action
    run_cmd = resolve_symbol("run_command", "tools.common")
    if action == "serve":
        wsl_path = _resolve_proto_wsl(repo_path, args.file, must_exist=True)
        if wsl_path is None:
            return 1
        ret, stdout, stderr = run_cmd(f"lavish-axi {wsl_path}", cwd=repo_path)
    elif action == "poll":
        wsl_path = _resolve_proto_wsl(repo_path, args.file, must_exist=False)
        if wsl_path is None:
            return 1
        cmd = f"lavish-axi poll {wsl_path}"
        if getattr(args, "agent_reply", None):
            cmd += f" --agent-reply {shlex.quote(args.agent_reply)}"
        ret, stdout, stderr = run_cmd(cmd, cwd=repo_path, timeout=3600)
    elif action == "stop":
        ret, stdout, stderr = run_cmd("lavish-axi stop", cwd=repo_path)
    elif action == "status":
        cmd = "python3 -c \"import json, os; p=os.path.expanduser('~/.lavish-axi/state.json'); s=json.load(open(p)) if os.path.exists(p) else {}; print(json.dumps([{'id': k, 'file': v.get('file'), 'status': v.get('status'), 'endedAt': v.get('endedAt'), 'endedBy': v.get('endedBy')} for k, v in s.get('sessions', {}).items()], indent=2))\""
        ret, stdout, stderr = run_cmd(cmd, cwd=repo_path)
    else:
        return 0
    print(stdout)
    if stderr and action in ("serve", "poll", "stop"):
        print(stderr, file=sys.stderr)
    return ret


def cmd_tier(args: argparse.Namespace) -> int:
    """Inspect or switch Edge Brigade execution tier."""
    repo_path = normalize_target_path(args.repo)
    is_json = bool(getattr(args, "json", False))
    if args.action == "status":
        state = resolve_symbol("get_tier_status", "tools.brigade.tier")(repo_path)
        print(json.dumps(state.to_dict(), indent=2) if is_json else resolve_symbol("format_tier_card", "tools.brigade.tier")(state))
        return 0
    if args.action == "switch":
        target = getattr(args, "target", None)
        if not target:
            print("❌ Error: --target <pro|ultra> is required when --action switch is specified.")
            return 1
        success, msg, state = resolve_symbol("switch_tier", "tools.brigade.tier")(repo_path, target)
        print(json.dumps({"success": success, "message": msg, "state": state.to_dict()}, indent=2) if is_json else msg)
        return 0 if success else 1
    print(f"❌ Unknown tier action: {args.action}")
    return 1
