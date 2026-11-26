"""Distill, QA React Fiber inspector, Lavish prototype bridge, and Tier CLI commands."""

import argparse
import json
from pathlib import Path
import sys

from tools.brigade.cli_ops._facade import resolve_symbol
from tools.brigade.prototype import execute_prototype_action
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


def cmd_prototype(args: argparse.Namespace) -> int:
    """Run lavish-axi interactive UI prototype bridge actions."""
    repo_path = normalize_target_path(args.repo)
    ret, stdout, stderr = execute_prototype_action(
        repo_path=repo_path,
        action=args.action,
        raw_file=getattr(args, "file", None),
        agent_reply=getattr(args, "agent_reply", None),
    )
    if stdout:
        print(stdout)
    if stderr:
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
