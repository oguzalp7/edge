"""Changed-file metrics and DRYER clone counting for Edge Verification Gate."""

from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from tools.gate_cc import compute_source_max_cc, count_source_sloc
from tools.gate_git import get_changed_rel_paths
from tools.gate_static import (
    PRODUCTION_CODE_SUFFIXES,
    count_sql_leaks,
    is_action_controller_path,
    is_eligible_prod_path,
)


def compute_dryer_clones(target_repo: Path, abs_changed_files: List[str]) -> Optional[int]:
    """Count DRYER structural AST clones scoped to changed production files."""
    from tools.audit import dryer as dryer_mod

    gate_mod = sys.modules.get("tools.gate")
    gate_ts = bool(getattr(gate_mod, "TREE_SITTER_AVAILABLE", True)) if gate_mod else True
    ts_avail = gate_ts and bool(getattr(dryer_mod, "TREE_SITTER_AVAILABLE", False))
    if not ts_avail:
        return None
    if not abs_changed_files:
        return 0
    scanner = dryer_mod.DryerScanner()
    pairs = scanner.scan_path(target_repo, scoped_files=abs_changed_files)
    if hasattr(scanner, "cluster_clones"):
        clusters = scanner.cluster_clones(pairs)
        if clusters:
            return len(clusters)
    return len(pairs)


def compute_changed_metrics(target_repo: Path, run_cmd: Any, base_ref: str) -> Dict[str, Any]:
    """Compute structured metrics scoped to changed production files."""
    rel_paths, _, _ = get_changed_rel_paths(target_repo, run_cmd, base_ref)
    prod_files = [
        rel for rel in (rel_paths or [])
        if is_eligible_prod_path(rel, PRODUCTION_CODE_SUFFIXES, require_src_prefix=False) and (target_repo / rel).is_file()
    ]
    db_leaks, max_cc, sloc = 0, 0, 0
    ts_abs, abs_changed = [], []
    for rel in prod_files:
        full_path = target_repo / rel
        resolved_str = str(full_path.resolve())
        abs_changed.append(resolved_str)
        suffix = full_path.suffix.lower()
        content = full_path.read_text(encoding="utf-8", errors="replace")
        if is_action_controller_path(rel):
            db_leaks += count_sql_leaks(content)
        file_cc, _ = compute_source_max_cc(content, suffix)
        max_cc = max(max_cc, file_cc)
        sloc += count_source_sloc(content, suffix)
        if suffix in (".ts", ".tsx") and not rel.lower().endswith(".d.ts"):
            ts_abs.append(resolved_str)
    type_score: Optional[float] = None
    if ts_abs:
        from tools.audit.ts_discipline import TsDisciplineAuditor
        type_score = TsDisciplineAuditor(target_repo).scan(target_repo, scoped_files=ts_abs).overall_score
    return {"db_leaks": db_leaks, "max_cc": max_cc, "dryer_clones": compute_dryer_clones(target_repo, abs_changed), "type_score": type_score, "sloc": sloc}
