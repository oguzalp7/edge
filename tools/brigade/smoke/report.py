"""Submodule: report."""

import json

from tools.brigade.smoke.models import SmokeScanReport

def _format_smoke_toon(report: SmokeScanReport) -> str:
    header = (
        f"smoke_routes[{report.total_routes}]"
        f"{{base:{report.base_url},navigable:{report.passed_routes}/{report.total_routes},"
        f"slow:{report.slow_routes},stuck:{report.stuck_routes},"
        f"budget_ms:{report.settle_budget_ms},heap_budget_mb:{report.heap_budget_mb},"
        f"all_navigable:{str(report.all_navigable).lower()}}}:"
    )
    lines = [
        header,
        "  route | status | settle_ms | ttfb_ms | heap_mb | dom_nodes | spinner | perf | navigable | source",
    ]
    for r in report.results:
        lines.append(
            f"  {r.route_pattern} | {r.http_status} | {r.settle_ms} | {r.ttfb_ms} | "
            f"{r.heap_used_mb} | {r.dom_nodes} | {r.spinner_state} | {r.perf_status} | "
            f"{str(r.navigable).lower()} | {r.source_file}"
        )
    if report.triage_tickets_created:
        lines.append(f"triage_tickets: {json.dumps(report.triage_tickets_created)}")
    return "\n".join(lines)


def _format_smoke_markdown(report: SmokeScanReport) -> str:
    icon = "✅" if report.all_navigable else "❌"
    lines = [
        f"### Route Smoke & Perf Telemetry ({icon} {report.passed_routes}/{report.total_routes} navigable)",
        (
            f"- **Budgets:** settle `<= {report.settle_budget_ms}ms`, hard `<= {report.hard_settle_timeout_ms}ms`, "
            f"heap `<= {report.heap_budget_mb}MB` · **Slow:** {report.slow_routes} · **Stuck:** {report.stuck_routes}"
        ),
        "",
        "| route | status | settle_ms | ttfb_ms | heap_mb | dom_nodes | spinner | perf | navigable | source |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in report.results:
        lines.append(
            f"| `{r.route_pattern}` | {r.http_status} | {r.settle_ms} | {r.ttfb_ms} | "
            f"{r.heap_used_mb} | {r.dom_nodes} | {r.spinner_state} | `{r.perf_status}` | "
            f"{str(r.navigable).lower()} | `{r.source_file}` |"
        )
    return "\n".join(lines)


def format_smoke_report(report: SmokeScanReport, fmt: str = "toon") -> str:
    """Formats SmokeScanReport as token-frugal 'toon' (default), 'json', or 'markdown'."""
    mode = (fmt or "toon").strip().lower()
    if mode == "json":
        return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
    if mode == "markdown":
        return _format_smoke_markdown(report)
    return _format_smoke_toon(report)
