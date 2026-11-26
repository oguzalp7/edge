"""Submodule: scanner."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from tools.brigade.smoke.constants import _write_json_atomic
from tools.brigade.smoke.models import DiscoveredRoute, RouteSmokeResult, SmokeScanReport
from tools.brigade.smoke.urls import discover_project_routes
from tools.brigade.smoke.probe import _default_browser_driver, _is_auth_redirected

def _classify_perf_telemetry(
    raw_spinner: str,
    settle_ms: int,
    heap_used_mb: float,
    settle_budget_ms: int,
    hard_settle_timeout_ms: int,
    heap_budget_mb: float,
) -> tuple[str, str, bool]:
    if raw_spinner == "stuck" or settle_ms >= hard_settle_timeout_ms:
        return "stuck", "FAIL_STUCK", True
    if settle_ms > settle_budget_ms:
        return "slow_settle", "WARN_SLOW", False
    settled_or_none = "settled" if (settle_ms > 0 or raw_spinner == "settled") else "none"
    if heap_used_mb > heap_budget_mb:
        return settled_or_none, "WARN_MEMORY", False
    return settled_or_none, "PASS", False


def _compute_base_navigable(
    http_status: int,
    console_errors: List[str],
    page_errors: List[str],
    auth_redirected: bool,
) -> bool:
    if not (200 <= http_status < 400):
        return False
    if console_errors or page_errors or auth_redirected:
        return False
    return True


def _raw_num(raw: Dict[str, Any], key: str, cast: Any, default: Any) -> Any:
    val = raw.get(key)
    return cast(default if val is None else val)


def _raw_str_list(raw: Dict[str, Any], key: str) -> List[str]:
    val = raw.get(key)
    return [str(e) for e in val] if val else []


def _evaluate_probe_result(
    route: DiscoveredRoute,
    full_url: str,
    raw: Dict[str, Any],
    settle_budget_ms: int = 1500,
    hard_settle_timeout_ms: int = 5000,
    heap_budget_mb: float = 80.0,
) -> RouteSmokeResult:
    http_status = _raw_num(raw, "http_status", int, 0)
    raw_final = raw.get("final_url")
    final_url = str(raw_final) if raw_final else full_url
    console_errors = _raw_str_list(raw, "console_errors")
    page_errors = _raw_str_list(raw, "page_errors")
    failed_requests = _raw_str_list(raw, "failed_requests")
    auth_redirected = bool(raw.get("auth_redirected")) or _is_auth_redirected(route.route_pattern, final_url)

    ttfb_ms = _raw_num(raw, "ttfb_ms", int, 0)
    settle_ms = _raw_num(raw, "settle_ms", int, 0)
    heap_used_mb = round(_raw_num(raw, "heap_used_mb", float, 0.0), 2)
    dom_nodes = _raw_num(raw, "dom_nodes", int, 0)
    raw_spinner = str(raw.get("spinner_state") or "none").strip().lower()

    spinner_state, perf_status, is_stuck = _classify_perf_telemetry(
        raw_spinner, settle_ms, heap_used_mb, settle_budget_ms, hard_settle_timeout_ms, heap_budget_mb
    )
    navigable = _compute_base_navigable(http_status, console_errors, page_errors, auth_redirected) and not is_stuck
    return RouteSmokeResult(
        route_pattern=route.route_pattern,
        url=full_url,
        source_file=route.source_file,
        http_status=http_status,
        final_url=final_url,
        auth_redirected=auth_redirected,
        console_errors=console_errors,
        page_errors=page_errors,
        failed_requests=failed_requests,
        navigable=navigable,
        ttfb_ms=ttfb_ms,
        settle_ms=settle_ms,
        heap_used_mb=heap_used_mb,
        dom_nodes=dom_nodes,
        spinner_state=spinner_state,
        perf_status=perf_status,
    )


def run_route_smoke_scan(
    repo_path: Path, base_url: str = "http://localhost:3000", pattern: Optional[str] = None,
    params: Optional[Dict[str, str]] = None, auth_cookie: Optional[str] = None, out_path: Optional[Path] = None,
    driver_fn: Optional[Callable[[DiscoveredRoute, str, Optional[str]], Dict[str, Any]]] = None,
    settle_budget_ms: int = 1500, hard_settle_timeout_ms: int = 5000, heap_budget_mb: float = 80.0,
) -> SmokeScanReport:
    """Scans discovered routes via headless browser or driver_fn and writes .edge/qa/smoke-routes.json."""
    repo = Path(repo_path)
    routes = discover_project_routes(repo, pattern=pattern, params=params)
    probe, base_clean = driver_fn or _default_browser_driver, base_url.rstrip("/")
    results = [
        _evaluate_probe_result(
            route, f"{base_clean}{route.concrete_url_path}", probe(route, f"{base_clean}{route.concrete_url_path}", auth_cookie),
            settle_budget_ms=settle_budget_ms, hard_settle_timeout_ms=hard_settle_timeout_ms, heap_budget_mb=heap_budget_mb,
        )
        for route in routes
    ]
    passed = sum(1 for r in results if r.navigable)
    report = SmokeScanReport(
        base_url=base_clean, scanned_at=datetime.now(timezone.utc).isoformat(),
        total_routes=len(results), passed_routes=passed, failed_routes=len(results) - passed, all_navigable=(passed == len(results)),
        total_console_errors=sum(len(r.console_errors) for r in results), total_page_errors=sum(len(r.page_errors) for r in results),
        results=results, settle_budget_ms=settle_budget_ms, hard_settle_timeout_ms=hard_settle_timeout_ms, heap_budget_mb=heap_budget_mb,
        slow_routes=sum(1 for r in results if r.perf_status in ("WARN_SLOW", "WARN_MEMORY")),
        stuck_routes=sum(1 for r in results if r.perf_status == "FAIL_STUCK"),
        max_settle_ms=max((r.settle_ms for r in results), default=0), max_heap_mb=round(max((r.heap_used_mb for r in results), default=0.0), 2),
    )
    _write_json_atomic(Path(out_path) if out_path else (repo / ".edge" / "qa" / "smoke-routes.json"), report.to_dict())
    return report
