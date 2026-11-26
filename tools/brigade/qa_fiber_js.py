"""React Fiber JS inspection snippet and headless browser evaluator."""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from tools.common import normalize_target_path


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


def _parse_eval_json(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except Exception:
                pass
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    except Exception as e:
        return {"error": f"Failed to parse eval JSON output: {e}", "raw": raw}


def execute_browser_eval(js_code: str) -> Optional[Dict[str, Any]]:
    """Runs a JavaScript snippet in the active browser using chrome-devtools-axi eval."""
    clean_js = " ".join(js_code.strip().splitlines())
    try:
        proc = subprocess.run(["chrome-devtools-axi", "eval", clean_js], capture_output=True, text=True, timeout=10, check=False)
    except Exception as e:
        return {"error": f"Exception executing chrome-devtools-axi: {str(e)}"}
    if proc.returncode != 0:
        return {"error": f"chrome-devtools-axi failed with code {proc.returncode}: {proc.stderr}"}
    stdout = proc.stdout.strip()
    for line in stdout.splitlines():
        line_str = line.strip()
        if line_str.startswith("result:"):
            return _parse_eval_json(line_str[len("result:"):].strip())
    return {"error": "No 'result:' line found in chrome-devtools-axi output", "stdout": stdout}
