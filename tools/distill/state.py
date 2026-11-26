#!/usr/bin/env python3
"""Watermark State, LexicalStackGate, CandidatePool & Line Budget Facade for edge-distill v2."""

from tools.distill.budget import check_line_budget, collect_budget_targets
from tools.distill.candidate_pool import CandidatePool, LexicalStackGate
from tools.distill.factory_inbox import FactoryInbox
from tools.distill.inbox_filter import (
    BENIGN_WSL_RELAY_BANNER_RE,
    compute_signal_fingerprint as _compute_signal_fingerprint,
)
from tools.distill.lexical_gate import (
    append_rule_to_agent_rubric as _append_rule_to_agent_rubric,
    clean_rule_from_all_projects as _clean_rule_from_all_projects,
)
from tools.distill.state_io import (
    DistillStateManager,
    _default_candidates_path,
    _default_factory_inbox_path,
    _default_state_path,
    _is_ephemeral_test_path,
    _resolve_agent_rubric_path,
    _sanitize_signal_summary,
    _save_json_atomic,
)

__all__ = [
    "DistillStateManager",
    "FactoryInbox",
    "LexicalStackGate",
    "CandidatePool",
    "collect_budget_targets",
    "check_line_budget",
    "BENIGN_WSL_RELAY_BANNER_RE",
]
