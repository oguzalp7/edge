"""Submodule: scanners_abac."""

from typing import Any, Dict, List, Optional, Set, Tuple

from tools.brigade.security.constants import _ABAC_SINK_RE, _DATA_MUTATION_RE, _PRIV_BYPASS_RE
from tools.brigade.security.models import SecurityFinding
from tools.brigade.security.validate import _classify_surface_and_boundary
from tools.brigade.security.exclusions import _make_finding
from tools.brigade.security.js_masker import _mask_js_comments_and_strings
from tools.brigade.security.policies import _extract_auth_policies, _upstream_refutation_reason
from tools.brigade.security.refutation import _extract_top_level_fn_defs
from tools.brigade.security.call_graph import _compute_guard_and_caller_helpers

def _evaluate_abac_line(
    rel: str, idx: int, line: str, lines: List[str], fn_name: str, fn_start: int,
    boundary: str, auth_policies: Set[str], guard_helpers: Set[str], caller_guarded: Set[str],
) -> Optional[SecurityFinding]:
    if _PRIV_BYPASS_RE.search(line):
        return _make_finding("ACCESS_CONTROL_ABAC", "confirmed", "CRITICAL", rel, idx, fn_name, "privilege_bypass", line, boundary)
    if not (m_sink := _ABAC_SINK_RE.search(line)):
        return None
    sink_name = m_sink.group(1)
    upstream = "\n".join(lines[fn_start - 1 : idx])
    sink_window = " ".join(lines[idx - 1 : min(len(lines), idx + 4)])
    reason = _upstream_refutation_reason(
        upstream, sink_name=sink_name, sink_window=sink_window,
        auth_policies=auth_policies, guard_helpers=guard_helpers, allow_read_only_run_action=True,
    )
    if reason is None and fn_name in caller_guarded:
        reason = f"Refuted: private helper '{fn_name}' called exclusively from auth-guarded action(s)"
    if reason is not None:
        return _make_finding("ACCESS_CONTROL_ABAC", "rejected", None, rel, idx, fn_name, sink_name, line, boundary, rejection_reason=reason)
    sev = "CRITICAL" if ("delete" in line or "admin" in rel.lower()) else "HIGH"
    return _make_finding("ACCESS_CONTROL_ABAC", "confirmed", sev, rel, idx, fn_name, sink_name, line, boundary)


def _scan_abac_class(
    rel: str, content: str, lines: List[str], fn_map: Dict[int, Tuple[int, str]],
    excluded_lines: Optional[Set[int]] = None, allow_server_actions: bool = True,
) -> List[SecurityFinding]:
    surface, boundary = _classify_surface_and_boundary(rel, content, allow_server_actions=allow_server_actions)
    if surface not in ("server_action", "api_route"):
        return []
    excl = excluded_lines or set()
    masked_lines = _mask_js_comments_and_strings(content).splitlines()
    if len(masked_lines) < len(lines):
        masked_lines.extend([""] * (len(lines) - len(masked_lines)))
    fn_defs = _extract_top_level_fn_defs(lines, masked_lines, is_python=False)
    auth_policies = _extract_auth_policies(masked_lines)
    guard_helpers, caller_guarded = _compute_guard_and_caller_helpers(lines, fn_defs, auth_policies)
    findings: List[SecurityFinding] = []
    for idx, line in enumerate(lines, start=1):
        if idx in excl:
            continue
        fn_start, fn_name = fn_map[idx]
        if (finding := _evaluate_abac_line(rel, idx, line, lines, fn_name, fn_start, boundary, auth_policies, guard_helpers, caller_guarded)):
            findings.append(finding)
    return findings


def _scan_data_isolation_class(
    rel: str,
    lines: List[str],
    fn_map: Dict[int, Tuple[int, str]],
    excluded_lines: Optional[Set[int]] = None,
) -> List[SecurityFinding]:
    excl = excluded_lines or set()
    findings: List[SecurityFinding] = []
    for idx, line in enumerate(lines, start=1):
        if idx in excl:
            continue
        m_mut = _DATA_MUTATION_RE.search(line)
        if not m_mut:
            continue
        stmt_window = " ".join(lines[idx - 1 : min(len(lines), idx + 5)])
        if ".where(" not in stmt_window:
            _, fn_name = fn_map[idx]
            findings.append(_make_finding(
                "DATA_ISOLATION", "confirmed", "HIGH", rel, idx, fn_name, f"db.{m_mut.group(1)}(without .where)", line, "tenant_row"
            ))
    return findings
