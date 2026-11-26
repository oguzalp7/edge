"""Submodule: tickets."""

from typing import Any, Callable, Dict, List, Optional
import hashlib
import re

from tools.brigade.models import CycleState, Ticket, TransitionLog
from tools.brigade.smoke.models import RouteSmokeResult, SmokeScanReport

def _route_to_slug(route_pattern: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", (route_pattern or "").strip("/")).strip("-")
    return cleaned.upper() if cleaned else "ROOT"


def _build_smoke_fix_hint(res: RouteSmokeResult) -> str:
    if res.perf_status == "FAIL_STUCK":
        return (
            f"Resolve stuck loading/spinner/Suspense boundary on '{res.route_pattern}' "
            f"exceeding hard settle timeout ({res.settle_ms}ms)."
        )
    if res.auth_redirected:
        return "Verify session/auth cookie handling or public visibility for this route (redirected to login wall)."
    if res.http_status >= 500 or res.http_status == 404 or res.http_status == 0:
        return f"Fix route handler or page resolution returning HTTP {res.http_status} on '{res.route_pattern}'."
    if res.page_errors:
        return f"Fix uncaught runtime / React hydration pageerror on '{res.route_pattern}'."
    return f"Eliminate browser console.error emitted during navigation to '{res.route_pattern}'."


def _build_perf_ticket(res: RouteSmokeResult, report: SmokeScanReport) -> Ticket:
    slug = _route_to_slug(res.route_pattern)
    ticket_id = f"TICK-PERF-{slug}"
    fingerprint = hashlib.sha256(f"ui:perf:{res.route_pattern}".encode("utf-8")).hexdigest()[:16]
    desc = (
        f"Slow route {res.route_pattern}: settle_ms={res.settle_ms}ms "
        f"(budget={report.settle_budget_ms}ms), heap={res.heap_used_mb}MB, dom_nodes={res.dom_nodes}"
    )
    target_file = res.source_file or "specs/INDEX.md"
    return Ticket(
        ticket_id=ticket_id,
        track="ui",
        domain="smoke-perf",
        rule_id="ROUTE_PERF_SLOW_SETTLE",
        severity="WARNING",
        target_file=target_file,
        line_number=1,
        fingerprint=fingerprint,
        description=desc,
        suggested_fix="Profile loader/Suspense waterfall, parallelize data fetches, or reduce initial client bundle/DOM payload.",
        branch_name=f"fix/perf-{slug.lower()}",
        expected_files=[target_file],
        require_qa=True,
    )


def _build_smoke_ticket(res: RouteSmokeResult) -> Ticket:
    slug = _route_to_slug(res.route_pattern)
    ticket_id = f"TICK-SMOKE-{slug}"
    fingerprint = hashlib.sha256(f"ui:smoke:{res.route_pattern}".encode("utf-8")).hexdigest()[:16]
    desc = (
        f"Route '{res.route_pattern}' ({res.url}) failed smoke navigability: "
        f"http_status={res.http_status}, auth_redirected={res.auth_redirected}, "
        f"console_errors={len(res.console_errors)}, page_errors={len(res.page_errors)}."
    )
    target_file = res.source_file or "specs/INDEX.md"
    return Ticket(
        ticket_id=ticket_id,
        track="ui",
        domain="smoke",
        rule_id="ROUTE_SMOKE_NAVIGABILITY",
        severity="CRITICAL",
        target_file=target_file,
        line_number=1,
        fingerprint=fingerprint,
        description=desc,
        suggested_fix=_build_smoke_fix_hint(res),
        branch_name=f"fix/smoke-{slug.lower()}",
        expected_files=[target_file],
        require_qa=True,
    )


def _ticket_to_ledger_item(ticket: Ticket, res: RouteSmokeResult) -> Dict[str, Any]:
    return {
        "ticket_id": ticket.ticket_id,
        "track": ticket.track,
        "domain": ticket.domain,
        "rule_id": ticket.rule_id,
        "severity": ticket.severity,
        "file_path": ticket.target_file,
        "line_number": ticket.line_number,
        "fingerprint": ticket.fingerprint,
        "title": f"Smoke failure on {res.route_pattern}",
        "description": ticket.description,
        "suggested_fix": ticket.suggested_fix,
        "route_pattern": res.route_pattern,
        "url": res.url,
        "status": "OPEN",
        "created_at": ticket.created_at,
    }
