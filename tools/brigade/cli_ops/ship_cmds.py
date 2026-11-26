"""Ship preparation, headless route smoke scan, and security audit CLI commands."""

import argparse
from pathlib import Path
import sys
from typing import Any, Dict

from tools.brigade.cli_ops._facade import (
    parse_param_pairs,
    resolve_cli_out_path,
    resolve_symbol,
    write_atomic_text,
)
from tools.common import normalize_target_path


def cmd_prepare_ship(args: argparse.Namespace) -> int:
    """Synthesize per-spec ship plans and optional split branches."""
    repo_path = normalize_target_path(args.repo)
    prep_kwargs: Dict[str, Any] = dict(
        repo_path=repo_path,
        base_branch=getattr(args, "base", "development") or "development",
        strict_proofs=bool(getattr(args, "strict_proofs", False)),
        spec_slug=getattr(args, "spec", None),
        split_branches=bool(getattr(args, "split_branches", False)),
        publish_evidence=bool(getattr(args, "publish_evidence", False)),
        evidence_branch=getattr(args, "evidence_branch", "edge-qa-evidence") or "edge-qa-evidence",
        require_smoke=bool(getattr(args, "require_smoke", False)),
        allow_topology_override=bool(getattr(args, "allow_topology_override", False)),
        stage_branches=parse_param_pairs(getattr(args, "stage_branch", None)) or None,
    )
    for arg_name, kw_name in (("issue", "issue_numbers"), ("parent_issue", "parent_issue")):
        if getattr(args, arg_name, None) is not None:
            prep_kwargs[kw_name] = getattr(args, arg_name)
    if getattr(args, "offline", False):
        prep_kwargs["offline"] = True
    prepare_ship_payload = resolve_symbol("prepare_ship_payload", "tools.brigade.ship_prep")
    format_ship_output = resolve_symbol("format_ship_output", "tools.brigade.ship_prep")
    ok, result, err = prepare_ship_payload(**prep_kwargs)
    rendered = format_ship_output(result, fmt=getattr(args, "format", "pr") or "pr")
    if not ok:
        print(f"❌ prepare-ship blocked: {err}", file=sys.stderr)
        if rendered:
            print(rendered)
        return 1
    out_arg = getattr(args, "out", None)
    if out_arg:
        out_path = normalize_target_path(out_arg) if Path(out_arg).is_absolute() else (repo_path / out_arg)
        write_atomic_text(out_path, rendered)
        print(f"✅ Ship payload written atomically to {out_path}")
    print(rendered)
    return 0


def cmd_smoke_routes(args: argparse.Namespace) -> int:
    """Discover and headless-smoke-scan project routes."""
    repo_path = normalize_target_path(args.repo)
    params = parse_param_pairs(getattr(args, "param", None))
    pattern = getattr(args, "pattern", None)
    if getattr(args, "discover_only", False):
        discover = resolve_symbol("discover_project_routes", "tools.brigade.smoke_routes")
        for r in discover(repo_path, pattern=pattern, params=params):
            print(f"{r.concrete_url_path} ({r.framework}) [{r.source_file}]")
        return 0
    out_path = resolve_cli_out_path(repo_path, getattr(args, "out", None))
    scan = resolve_symbol("run_route_smoke_scan", "tools.brigade.smoke_routes")
    report = scan(
        repo_path=repo_path, base_url=getattr(args, "base_url", "http://localhost:3000") or "http://localhost:3000",
        pattern=pattern, params=params, auth_cookie=getattr(args, "auth_cookie", None), out_path=out_path,
        settle_budget_ms=int(getattr(args, "settle_budget_ms", 1500) or 1500),
        heap_budget_mb=float(getattr(args, "heap_budget_mb", 80.0) or 80.0),
    )
    if ((not report.all_navigable) or (getattr(report, "slow_routes", 0) > 0)) and not getattr(args, "no_triage", False):
        resolve_symbol("triage_smoke_failures", "tools.brigade.smoke_routes")(repo_path, report)
    fmt = getattr(args, "format", "toon") or "toon"
    print(resolve_symbol("format_smoke_report", "tools.brigade.smoke_routes")(report, fmt=fmt))
    return 0 if report.all_navigable else 1


def cmd_security_audit(args: argparse.Namespace) -> int:
    """Run incremental 4-class security audit."""
    repo_path = normalize_target_path(args.repo)
    raw_scopes = list(getattr(args, "scope", None) or [])
    report = resolve_symbol("run_security_audit", "tools.brigade.security_audit")(
        repo_path=repo_path, scopes=raw_scopes or None, diff_only=bool(getattr(args, "diff_only", False)),
        base_ref=getattr(args, "base", None), recursive=bool(getattr(args, "recursive", False)),
        profile=getattr(args, "profile", "standard") or "standard",
    )
    if not report.passed and not getattr(args, "no_triage", False):
        resolve_symbol("triage_security_findings", "tools.brigade.security_audit")(repo_path, report)
    fmt = getattr(args, "format", "toon") or "toon"
    print(resolve_symbol("format_security_report", "tools.brigade.security_audit")(report, fmt=fmt))
    return 0 if report.passed else 1
