"""Submodule: call_graph."""

from typing import Any, Dict, List, Optional, Set, Tuple
import re

from tools.brigade.security.constants import _ABAC_GUARD_RE, _TOKEN_GUARD_RE
from tools.brigade.security.refutation import _FnDef
from tools.brigade.security.policies import _upstream_refutation_reason

def _find_fn_call_sites(lines: List[str], fn_defs: List[_FnDef], target_name: str) -> List[Tuple[_FnDef, int]]:
    call_pat = re.compile(rf"\b{re.escape(target_name)}\s*\(")
    sites: List[Tuple[_FnDef, int]] = []
    for other in fn_defs:
        if other.name == target_name:
            continue
        for line_no in range(other.start_line, other.end_line + 1):
            if call_pat.search(lines[line_no - 1]):
                sites.append((other, line_no))
    return sites


def _all_callers_guarded(
    lines: List[str], call_sites: List[Tuple[_FnDef, int]],
    caller_guarded: Set[str], auth_policies: Set[str], guard_helpers: Set[str],
) -> bool:
    for caller_fn, call_line in call_sites:
        if caller_fn.name in caller_guarded:
            continue
        upstream = "\n".join(lines[caller_fn.start_line - 1 : call_line])
        reason = _upstream_refutation_reason(
            upstream, sink_name="", sink_window="", auth_policies=auth_policies,
            guard_helpers=guard_helpers, allow_read_only_run_action=False,
        )
        if reason is None:
            return False
    return True


def _compute_guard_and_caller_helpers(
    lines: List[str], fn_defs: List[_FnDef], auth_policies: Set[str],
) -> Tuple[Set[str], Set[str]]:
    """Computes intra-file guard helpers and private helpers called exclusively under auth guards."""
    fn_bodies = {fn.name: "\n".join(lines[fn.start_line - 1 : fn.end_line]) for fn in fn_defs}
    guard_helpers: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for fn in fn_defs:
            if fn.is_exported or fn.name in guard_helpers:
                continue
            body = fn_bodies[fn.name]
            if _ABAC_GUARD_RE.search(body) or _TOKEN_GUARD_RE.search(body) or any(re.search(rf"\b{re.escape(gh)}\s*\(", body) for gh in guard_helpers):
                guard_helpers.add(fn.name)
                changed = True
    caller_guarded: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for fn in fn_defs:
            if fn.is_exported or fn.name in caller_guarded:
                continue
            sites = _find_fn_call_sites(lines, fn_defs, fn.name)
            if sites and _all_callers_guarded(lines, sites, caller_guarded, auth_policies, guard_helpers):
                caller_guarded.add(fn.name)
                changed = True
    return guard_helpers, caller_guarded
