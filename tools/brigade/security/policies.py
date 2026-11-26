"""Submodule: policies (auth policy literal extraction and upstream refutation)."""

import re
from typing import List, Optional, Set, Tuple

from tools.brigade.security.call_args import _extract_action_policy_args
from tools.brigade.security.constants import (
    _ABAC_GUARD_RE,
    _POLICY_AUTH_FIELD_RE,
    _POLICY_KEY_START_RE,
    _POLICY_OBJ_START_RE,
    _READ_ONLY_REPO_METHOD_RE,
    _RUN_ACTION_CALL_RE,
    _TOKEN_GUARD_RE,
)


def _close_policy_key_if_done(
    active_obj: Optional[str], active_key: Optional[str], key_depth: Optional[int],
    brace_depth: int, prev_depth: int, key_buf: List[str], auth_policies: Set[str],
) -> Tuple[Optional[str], Optional[int], List[str]]:
    if not (active_obj and active_key and key_depth is not None):
        return active_key, key_depth, key_buf
    if brace_depth <= key_depth and prev_depth >= key_depth:
        if _POLICY_AUTH_FIELD_RE.search("\n".join(key_buf)):
            auth_policies.add(f"{active_obj}.{active_key}")
        return None, None, []
    return active_key, key_depth, key_buf


def _extract_auth_policies(masked_lines: List[str]) -> Set[str]:
    """Extracts `<OBJ>.<key>` entries from top-level policy objects declaring minAuthLevel/authLevel/requireAuth."""
    auth_policies: Set[str] = set()
    brace_depth, active_obj, active_key, key_depth, key_buf = 0, None, None, None, []
    for mline in masked_lines:
        if active_obj is None and brace_depth == 0 and (m_obj := _POLICY_OBJ_START_RE.match(mline.strip())):
            active_obj = m_obj.group(1)
        if active_obj is not None and active_key is None and brace_depth == 1 and (m_key := _POLICY_KEY_START_RE.match(mline)):
            active_key, key_depth, key_buf = m_key.group(1), 1, [mline]
        elif active_obj is not None and active_key is not None:
            key_buf.append(mline)
        prev_depth = brace_depth
        brace_depth = max(0, brace_depth + mline.count("{") - mline.count("}"))
        active_key, key_depth, key_buf = _close_policy_key_if_done(
            active_obj, active_key, key_depth, brace_depth, prev_depth, key_buf, auth_policies
        )
        if active_obj is not None and brace_depth == 0:
            active_obj, active_key, key_depth, key_buf = None, None, None, []
    return auth_policies


def _upstream_refutation_reason(
    upstream: str,
    sink_name: str,
    sink_window: str,
    auth_policies: Set[str],
    guard_helpers: Set[str],
    allow_read_only_run_action: bool = True,
) -> Optional[str]:
    if _ABAC_GUARD_RE.search(upstream):
        return "Refuted: auth/ABAC guard verified upstream before sink"
    if _TOKEN_GUARD_RE.search(upstream):
        return "Refuted: cryptographic token guard verified upstream before sink"
    for helper in guard_helpers:
        if re.search(rf"\b{re.escape(helper)}\s*\(", upstream):
            return f"Refuted: intra-file guard helper '{helper}' verified upstream before sink"
    for action_fn, policy_arg in _extract_action_policy_args(upstream):
        if policy_arg in auth_policies or _POLICY_AUTH_FIELD_RE.search(policy_arg):
            desc = "inline options enforce" if policy_arg.startswith("{") else f"policy '{policy_arg}' enforces"
            return f"Refuted: {action_fn} {desc} auth level"
        if allow_read_only_run_action and _READ_ONLY_REPO_METHOD_RE.match(sink_name):
            return f"Refuted: non-mutating repository read wrapped in {action_fn}"
    if allow_read_only_run_action and _READ_ONLY_REPO_METHOD_RE.match(sink_name) and "publicOnly" in sink_window:
        return "Refuted: publicOnly read-only repository query"
    return None
