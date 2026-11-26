#!/usr/bin/env python3
"""
QA Fiber Inspector & Component Locator.
Deterministic Bridge from DOM CSS Selector / XPath to React Fiber Component & Source Line,
with automated staging into frontier-axi.
"""

import sys
import os
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import normalize_target_path, toon_encode

# Generic React/Next.js internal wrappers to filter out from domain component hierarchy
INTERNAL_REACT_NAMES = {
    "LinkComponent", "Router", "Boundary", "LayoutRouter", "LayoutRouterContext", "InnerLayoutRouter",
    "OuterLayoutRouter", "RedirectErrorBoundary", "RedirectBoundary",
    "HTTPAccessFallbackErrorBoundary", "HTTPAccessFallbackBoundary",
    "DevRootHTTPAccessFallbackBoundary", "LoadingBoundary", "ErrorBoundary",
    "InnerScrollHandlerNew", "ScrollAndMaybeFocusHandler", "RenderFromTemplateContext",
    "TemplateContext", "SegmentStateProvider", "OuterLayoutRouter", "SegmentViewNode",
    "__next_root_layout_boundary__", "AppDevOverlayErrorBoundary", "HotReload",
    "AppRouterContext", "GlobalLayoutRouterContext", "SearchParamsContext",
    "PathnameContext", "PathParamsContext", "NavigationPromisesContext",
    "AppRouter", "ErrorBoundaryHandler", "RootErrorBoundary", "ServerRoot",
    "Root", "HeadManagerContext", "Fragment", "Suspense", "Consumer", "Provider"
}


FIBER_JS_SNIPPET = r"""
(() => {
  const query = %QUERY%;
  function findElement(q) {
    if (!q) return null;
    if (q.startsWith('//')) {
      const res = document.evaluate(q, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
      return res.singleNodeValue;
    }
    if (q.startsWith('text:')) {
      const txt = q.slice(5).trim().toLowerCase();
      const all = Array.from(document.querySelectorAll('*'));
      const leaf = all.find(el => el.children.length === 0 && el.innerText && el.innerText.trim().toLowerCase().includes(txt));
      return leaf ? (leaf.closest('button, a, input, [role="button"]') || leaf) : null;
    }
    try {
      return document.querySelector(q);
    } catch(e) {
      return null;
    }
  }

  const el = findElement(query);
  if (!el) {
    return JSON.stringify({ error: 'ELEMENT_NOT_FOUND', query: query });
  }

  const fiberKey = Object.keys(el).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
  const fiber = fiberKey ? el[fiberKey] : null;

  const rawHierarchy = [];
  let debugSource = null;
  let curr = fiber;
  let count = 0;

  while (curr && count < 40) {
    const fnType = curr.type;
    const name = curr.type?.displayName || curr.type?.name || (typeof fnType === 'string' ? fnType : null);
    if (name && !rawHierarchy.includes(name)) {
      rawHierarchy.push(name);
    }
    if (!debugSource && curr._debugSource) {
      debugSource = curr._debugSource;
    }
    if (curr._debugOwner) {
      const ownerName = curr._debugOwner.type?.displayName || curr._debugOwner.type?.name;
      if (ownerName && !rawHierarchy.includes(ownerName)) {
        rawHierarchy.push(ownerName);
      }
      if (!debugSource && curr._debugOwner._debugSource) {
        debugSource = curr._debugOwner._debugSource;
      }
    }
    curr = curr.return;
    count++;
  }

  return {
    success: true,
    tag: el.tagName,
    text: (el.innerText || el.value || '').trim().slice(0, 100),
    classes: (el.className && typeof el.className === 'string') ? el.className.trim() : '',
    id: el.id || null,
    testId: el.getAttribute('data-testid') || null,
    role: el.getAttribute('role') || null,
    hierarchy: rawHierarchy,
    debugSource: debugSource ? {
      fileName: debugSource.fileName || null,
      lineNumber: debugSource.lineNumber || null
    } : null
  };
})()
"""


def execute_browser_eval(js_code: str) -> Optional[Dict[str, Any]]:
    """Runs a JavaScript snippet in the active browser using chrome-devtools-axi eval."""
    clean_js = " ".join(js_code.strip().splitlines())
    cmd = ["chrome-devtools-axi", "eval", clean_js]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False
        )
        if proc.returncode != 0:
            return {"error": f"chrome-devtools-axi failed with code {proc.returncode}: {proc.stderr}"}
        
        stdout = proc.stdout.strip()
        for line in stdout.splitlines():
            line_str = line.strip()
            if line_str.startswith("result:"):
                raw = line_str[len("result:"):].strip()
                try:
                    parsed = json.loads(raw)
                    # Handle double-encoded JSON if present
                    if isinstance(parsed, str):
                        try:
                            parsed = json.loads(parsed)
                        except Exception:
                            pass
                    if isinstance(parsed, dict):
                        return parsed
                    return {"result": parsed}
                except Exception as e:
                    return {"error": f"Failed to parse eval JSON output: {e}", "raw": raw}
        return {"error": "No 'result:' line found in chrome-devtools-axi output", "stdout": stdout}
    except Exception as e:
        return {"error": f"Exception executing chrome-devtools-axi: {str(e)}"}


def locate_component_in_repo(repo_path: Path, component_name: str, element_text: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Locates the React component definition and line number in the target repository."""
    src_dir = repo_path / "src"
    if not src_dir.exists():
        src_dir = repo_path

    # Search for export/function/const ComponentName
    def_pattern = re.compile(
        rf"(?:export\s+(?:default\s+)?(?:function|const|class)\s+{re.escape(component_name)}\b|"
        rf"\bfunction\s+{re.escape(component_name)}\b|"
        rf"\bconst\s+{re.escape(component_name)}\s*[:=])"
    )

    matches = []
    exts = {".tsx", ".jsx", ".ts", ".js"}

    for root, _, files in os.walk(src_dir):
        if any(skip in root for skip in ["node_modules", ".next", "dist", "build", ".git"]):
            continue
        for file in files:
            if Path(file).suffix in exts:
                file_path = Path(root) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    for idx, line in enumerate(lines, 1):
                        if def_pattern.search(line):
                            matches.append({
                                "file_path": file_path,
                                "rel_path": str(file_path.relative_to(repo_path)).replace("\\", "/"),
                                "def_line": idx,
                                "lines": lines
                            })
                            break
                except Exception:
                    continue

    if not matches:
        return None

    # Pick the best match (prefer component files matching the name)
    best = matches[0]
    for m in matches:
        if component_name.lower() in m["file_path"].stem.lower():
            best = m
            break

    # If element_text is present, try to pinpoint the exact line in that component file
    exact_line = best["def_line"]
    if element_text and len(element_text) >= 3:
        clean_needle = element_text.strip().lower()
        # Look for literal string occurrence
        for idx, line in enumerate(best["lines"], 1):
            if clean_needle in line.lower():
                exact_line = idx
                break

    return {
        "component": component_name,
        "file": best["rel_path"],
        "line": exact_line,
        "absolute_path": str(best["file_path"])
    }


def stage_to_frontier(
    repo_path: Path,
    file_path: str,
    line_number: int,
    component: str,
    issue: str,
    category: Optional[str] = None,
    offline: bool = False,
) -> Dict[str, Any]:
    """Stages an anomaly or visual bug into the tracker frontier (`type:frontier`, `track:ui`)."""
    from tools.tracker.backends import resolve_backend

    cat_tag = f" (#{category.lstrip('#')})" if category else ""
    title = f"[e2e-journal] {file_path}:{line_number} ({component}) - {issue}{cat_tag}"
    backend = resolve_backend(repo_path, offline=offline)

    existing = backend.list_issues(state="open", labels=["type:frontier"])
    for item in existing:
        if item.title == title or (f"{file_path}:{line_number}" in item.title and issue in item.title):
            return {
                "success": True,
                "method": f"tracker ({backend.kind}, deduped)",
                "id": str(item.number),
                "issue_number": item.number,
                "title": item.title,
                "url": item.url,
            }

    body = (
        "Automated visual anomaly detected by QA Engineer (Sommelier) during browser verification.\n\n"
        f"- **File:** `{file_path}:{line_number}`\n"
        f"- **Component:** `{component}`\n"
        f"- **Category:** `{category or 'ui'}`\n"
        f"- **Issue:** {issue}\n"
    )
    created = backend.create_issue(
        title=title,
        body=body,
        labels=["type:frontier", "track:ui", "status:ready"],
    )
    return {
        "success": True,
        "method": f"tracker ({backend.kind})",
        "id": str(created.number),
        "issue_number": created.number,
        "title": created.title,
        "url": created.url,
    }


def inspect_fiber(
    query: str,
    repo_path_str: str = ".",
    log_frontier: bool = False,
    issue: str = "",
    category: Optional[str] = None,
    offline: bool = False,
) -> Dict[str, Any]:
    """High-level inspection function bridging DOM query to source code and frontier."""
    repo_path = Path(normalize_target_path(repo_path_str))
    
    # Format query for JS
    formatted_query = json.dumps(query)
    js = FIBER_JS_SNIPPET.replace("%QUERY%", formatted_query)

    eval_res = execute_browser_eval(js)
    if not eval_res or "error" in eval_res:
        return {
            "success": False,
            "error": eval_res.get("error") if eval_res else "No response from browser",
            "query": query
        }

    raw_hierarchy = eval_res.get("hierarchy", [])
    # Filter out generic React/Next wrappers
    domain_hierarchy = [
        name for name in raw_hierarchy
        if name and name[0].isupper() and name not in INTERNAL_REACT_NAMES and not name.startswith("tag:")
    ]

    selected_component = domain_hierarchy[0] if domain_hierarchy else "UnknownComponent"
    debug_source = eval_res.get("debugSource")

    source_location = None
    if debug_source and debug_source.get("fileName"):
        clean_file = debug_source["fileName"].replace("\\", "/")
        if "/src/" in clean_file:
            clean_file = "src/" + clean_file.split("/src/", 1)[1]
        source_location = {
            "component": selected_component,
            "file": clean_file,
            "line": debug_source.get("lineNumber") or 1
        }
    else:
        # Fallback to repository AST search
        source_location = locate_component_in_repo(repo_path, selected_component, eval_res.get("text"))

    frontier_result = None
    if log_frontier and issue and source_location:
        frontier_result = stage_to_frontier(
            repo_path=repo_path,
            file_path=source_location["file"],
            line_number=source_location["line"],
            component=selected_component,
            issue=issue,
            category=category,
            offline=offline,
        )

    return {
        "success": True,
        "query": query,
        "element": {
            "tag": eval_res.get("tag"),
            "text": eval_res.get("text"),
            "classes": eval_res.get("classes"),
            "id": eval_res.get("id"),
            "testId": eval_res.get("testId")
        },
        "component": selected_component,
        "hierarchy": domain_hierarchy,
        "location": source_location,
        "frontier": frontier_result
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Deterministic React Fiber Component & Source Line Inspector")
    parser.add_argument("query", help="CSS selector (button.confirm), XPath (//button), or text (text:Giriş Yap)")
    parser.add_argument("--repo", default=".", help="Target repository root path (default: .)")
    parser.add_argument("--issue", help="Description of UI anomaly (e.g. 'Metin container dışına taşıyor')")
    parser.add_argument("--category", choices=["contrast", "overflow", "layout", "visual-regression", "misalignment"], help="Anomaly category")
    parser.add_argument("--frontier", action="store_true", help="Stage finding into frontier-axi")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()
    res = inspect_fiber(
        query=args.query,
        repo_path_str=args.repo,
        log_frontier=args.frontier or bool(args.issue),
        issue=args.issue or "",
        category=args.category
    )

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("success") else 1

    if not res.get("success"):
        print(f"❌ Fiber Inspection Failed: {res.get('error')}")
        return 1

    el = res["element"]
    loc = res.get("location")
    print("🎯 React Component Located Successfully:")
    print(f"   Query:       {res['query']}")
    print(f"   Component:   {res['component']}")
    if loc:
        print(f"   Source File: {loc['file']}:{loc['line']}")
    else:
        print("   Source File: (Could not resolve source file in repo)")
    print(f"   Element:     <{el['tag']}> \"{el['text']}\"")
    if el.get('classes'):
        print(f"   Classes:     {el['classes']}")
    print(f"   Hierarchy:   {' > '.join(res['hierarchy'][:4])}")

    if res.get("frontier"):
        f_res = res["frontier"]
        if f_res.get("success"):
            print(f"\n📋 Staged to frontier-axi:")
            print(f"   ID:    {f_res.get('id')}")
            print(f"   Title: {f_res.get('title')}")
            print(f"   Via:   {f_res.get('method')}")
        else:
            print(f"\n⚠️ Frontier Staging Failed: {f_res.get('error')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
