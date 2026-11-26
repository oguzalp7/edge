"""Submodule: probe."""

from typing import Any, Callable, Dict, List, Optional
import json
import shutil
import subprocess
import urllib.error
import urllib.request

from tools.brigade.smoke.constants import _AUTH_REDIRECT_MARKERS
from tools.brigade.smoke.models import DiscoveredRoute
from tools.brigade.smoke.route_params import _is_auth_entry_route

def _is_auth_redirected(route_pattern: str, final_url: str) -> bool:
    if _is_auth_entry_route(route_pattern):
        return False
    low = (final_url or "").lower()
    return any(marker in low for marker in _AUTH_REDIRECT_MARKERS)


def _http_fallback_probe(full_url: str, auth_cookie: Optional[str]) -> Dict[str, Any]:
    headers = {"Cookie": auth_cookie} if auth_cookie else {}
    req = urllib.request.Request(full_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {
                "http_status": int(resp.getcode() or 200),
                "final_url": resp.geturl(),
                "console_errors": [],
                "page_errors": [],
                "failed_requests": [],
            }
    except urllib.error.HTTPError as exc:
        return {
            "http_status": int(exc.code),
            "final_url": exc.geturl(),
            "console_errors": [],
            "page_errors": [f"HTTP {exc.code}: {exc.reason}"],
            "failed_requests": [f"{full_url} -> {exc.code}"],
        }
    except Exception as exc:
        return {
            "http_status": 0,
            "final_url": full_url,
            "console_errors": [],
            "page_errors": [str(exc)],
            "failed_requests": [f"{full_url} -> {exc}"],
        }


def _playwright_node_probe(
    full_url: str,
    auth_cookie: Optional[str],
    hard_settle_timeout_ms: int = 5000,
) -> Optional[Dict[str, Any]]:
    if not shutil.which("node"):
        return None
    script = (
        "const { chromium } = require('playwright');"
        "(async () => {"
        "  const url = process.argv[1]; const cookie = process.argv[2] || '';"
        "  const hardTimeout = Math.max(200, parseInt(process.argv[3] || '5000', 10));"
        "  const browser = await chromium.launch({ headless: true });"
        "  const ctx = await browser.newContext(cookie ? { extraHTTPHeaders: { Cookie: cookie } } : {});"
        "  const page = await ctx.newPage();"
        "  const consoleErrors = []; const pageErrors = []; const failedRequests = [];"
        "  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });"
        "  page.on('pageerror', e => pageErrors.push(String(e)));"
        "  page.on('response', r => { if (r.status() >= 500) failedRequests.push(r.url() + ' -> ' + r.status()); });"
        "  const t0 = Date.now();"
        "  const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });"
        "  const sel = \".animate-spin, .animate-pulse, [aria-busy='true'], [data-loading='true'], [role='status']\";"
        "  let seenSpinner = false; let spinnerState = 'none'; let settleMs = Date.now() - t0;"
        "  while (Date.now() - t0 < hardTimeout) {"
        "    const vis = await page.evaluate((s) => Array.from(document.querySelectorAll(s)).some(el => el.offsetParent !== null), sel);"
        "    if (vis) { seenSpinner = true; await page.waitForTimeout(100); } else { spinnerState = seenSpinner ? 'settled' : 'none'; settleMs = Date.now() - t0; break; }"
        "  }"
        "  if (seenSpinner && spinnerState === 'none') { spinnerState = 'stuck'; settleMs = hardTimeout; }"
        "  const metrics = await page.evaluate(() => {"
        "    const nav = performance.getEntriesByType('navigation')[0];"
        "    const ttfb = nav ? Math.round(Math.max(0, nav.responseStart - nav.requestStart)) : 0;"
        "    const mem = performance.memory ? Number((performance.memory.usedJSHeapSize / 1048576).toFixed(2)) : 0.0;"
        "    return { ttfb_ms: ttfb, heap_used_mb: mem, dom_nodes: document.querySelectorAll('*').length };"
        "  });"
        "  console.log(JSON.stringify({ http_status: resp ? resp.status() : 0, final_url: page.url(), console_errors: consoleErrors, page_errors: pageErrors, failed_requests: failedRequests, ttfb_ms: metrics.ttfb_ms, settle_ms: settleMs, heap_used_mb: metrics.heap_used_mb, dom_nodes: metrics.dom_nodes, spinner_state: spinnerState }));"
        "  await browser.close();"
        "})().catch(e => { console.error(String(e)); process.exit(2); });"
    )
    try:
        proc = subprocess.run(
            ["node", "-e", script, full_url, auth_cookie or "", str(hard_settle_timeout_ms)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    return None


def _default_browser_driver(
    route: DiscoveredRoute,
    full_url: str,
    auth_cookie: Optional[str],
) -> Dict[str, Any]:
    pw_res = _playwright_node_probe(full_url, auth_cookie)
    if pw_res is not None:
        return pw_res
    return _http_fallback_probe(full_url, auth_cookie)
