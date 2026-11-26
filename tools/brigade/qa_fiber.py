#!/usr/bin/env python3
"""QA Fiber Inspector & Component Locator facade."""

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Optional

from tools.brigade.qa_fiber_js import FIBER_JS_SNIPPET, INTERNAL_REACT_NAMES, execute_browser_eval
from tools.brigade.qa_fiber_locator import locate_component_in_repo, stage_to_frontier
from tools.common import normalize_target_path


def _is_ui_profile_active(repo_path: Path) -> bool:
    from tools.common.profiles import has_profile_capability, resolve_active_profiles

    profiles = resolve_active_profiles(repo_path)
    if profiles.source not in ("explicit", "explicit_none"):
        return True
    return any(has_profile_capability(profiles, c) for c in ("nextjs_app_router", "tailwind_dual_theme", "typescript"))


def _resolve_fiber_source(repo_path: Path, eval_res: Dict[str, Any], selected_component: str) -> Optional[Dict[str, Any]]:
    debug_source = eval_res.get("debugSource")
    if debug_source and debug_source.get("fileName"):
        clean_file = debug_source["fileName"].replace("\\", "/")
        clean_file = "src/" + clean_file.split("/src/", 1)[1] if "/src/" in clean_file else clean_file
        return {"component": selected_component, "file": clean_file, "line": debug_source.get("lineNumber") or 1}
    return locate_component_in_repo(repo_path, selected_component, eval_res.get("text"))


def inspect_fiber(
    query: str, repo_path_str: str = ".", log_frontier: bool = False,
    issue: str = "", category: Optional[str] = None, offline: bool = False,
) -> Dict[str, Any]:
    """High-level inspection function bridging DOM query to source code and frontier."""
    repo_path = Path(normalize_target_path(repo_path_str))
    if not _is_ui_profile_active(repo_path):
        return {"success": False, "skipped": True, "error": "Skipped (inactive UI profile)", "query": query}
    js = FIBER_JS_SNIPPET.replace("%QUERY%", json.dumps(query))
    facade = sys.modules.get(__name__)
    eval_fn = getattr(facade, "execute_browser_eval", execute_browser_eval) if facade else execute_browser_eval
    eval_res = eval_fn(js)
    if not eval_res or "error" in eval_res:
        return {"success": False, "error": eval_res.get("error") if eval_res else "No response from browser", "query": query}
    hierarchy = [n for n in eval_res.get("hierarchy", []) if n and n[0].isupper() and n not in INTERNAL_REACT_NAMES and not n.startswith("tag:")]
    selected = hierarchy[0] if hierarchy else "UnknownComponent"
    source_location = _resolve_fiber_source(repo_path, eval_res, selected)
    frontier_res = stage_to_frontier(
        repo_path=repo_path, file_path=source_location["file"], line_number=source_location["line"],
        component=selected, issue=issue, category=category, offline=offline,
    ) if (log_frontier and issue and source_location) else None
    return {
        "success": True, "query": query,
        "element": {k: eval_res.get(k) for k in ("tag", "text", "classes", "id", "testId")},
        "component": selected, "hierarchy": hierarchy, "location": source_location, "frontier": frontier_res,
    }


def _print_human_report(res: Dict[str, Any]) -> None:
    el, loc = res["element"], res.get("location")
    print(f"🎯 React Component Located Successfully:\n   Query:       {res['query']}\n   Component:   {res['component']}")
    print(f"   Source File: {loc['file']}:{loc['line']}" if loc else "   Source File: (Could not resolve source file in repo)")
    print(f"   Element:     <{el['tag']}> \"{el['text']}\"")
    if el.get("classes"):
        print(f"   Classes:     {el['classes']}")
    print(f"   Hierarchy:   {' > '.join(res['hierarchy'][:4])}")
    if (f_res := res.get("frontier")):
        print(f"\n📋 Staged to frontier-axi:\n   ID:    {f_res.get('id')}\n   Title: {f_res.get('title')}\n   Via:   {f_res.get('method')}" if f_res.get("success") else f"\n⚠️ Frontier Staging Failed: {f_res.get('error')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic React Fiber Component & Source Line Inspector")
    parser.add_argument("query", help="CSS selector (button.confirm), XPath (//button), or text (text:Giriş Yap)")
    parser.add_argument("--repo", default=".", help="Target repository root path (default: .)")
    parser.add_argument("--issue", help="Description of UI anomaly")
    parser.add_argument("--category", choices=["contrast", "overflow", "layout", "visual-regression", "misalignment"])
    parser.add_argument("--frontier", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    res = inspect_fiber(query=args.query, repo_path_str=args.repo, log_frontier=args.frontier or bool(args.issue), issue=args.issue or "", category=args.category)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("success") else 1
    if not res.get("success"):
        print(f"❌ Fiber Inspection Failed: {res.get('error')}")
        return 1
    _print_human_report(res)
    return 0
