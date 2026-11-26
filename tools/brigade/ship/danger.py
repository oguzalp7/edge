"""Ship-prep submodule: danger."""

from typing import List, Dict, Any, Optional, Tuple
import re

from tools.brigade.ship.constants import _LAYER_RULES
from tools.brigade.ship.paths import _norm_rel_path
from tools.brigade.ship.danger_paths import _is_one_way_door_path, _is_refactor_auth_path
from tools.brigade.ship.danger_breaks import _detect_exported_api_breaks

def _classify_layer(norm_path: str) -> str:
    low = norm_path.lower()
    if _is_one_way_door_path(norm_path):
        return "db"
    for layer, markers in _LAYER_RULES:
        if any(m in low for m in markers):
            return layer
    return "core"


def _extract_domains(norm_files: List[str]) -> List[str]:
    domains: List[str] = []
    for f in norm_files:
        parts = [p for p in f.split("/") if p and p not in ("src", "lib", "app", "tests", "unit")]
        if len(parts) >= 2:
            dom = parts[1] if parts[0] in ("actions", "components", "db", "tools") else parts[0]
            if dom not in domains and "." not in dom:
                domains.append(dom)
    return domains


def _parse_stat_counts(diff_stat: str) -> Tuple[int, int]:
    ins_m = re.search(r"(\d+)\s+insertion", diff_stat or "")
    del_m = re.search(r"(\d+)\s+deletion", diff_stat or "")
    return (int(ins_m.group(1)) if ins_m else 0), (int(del_m.group(1)) if del_m else 0)


def _collect_refactor_reasons(
    norm_files: List[str], ins: int, dels: int, diff_text: str, one_way_triggers: List[str]
) -> List[str]:
    reasons: List[str] = []
    for f in norm_files:
        if _is_refactor_auth_path(f):
            if f not in one_way_triggers:
                one_way_triggers.append(f)
            reasons.append(f"Security/auth path touched: {f}")
    reasons.extend(_detect_exported_api_breaks(diff_text))
    if len(norm_files) > 15:
        reasons.append(f"Large refactor blast radius: {len(norm_files)} files changed (> 15)")
    if (ins + dels) > 500:
        reasons.append(f"Large refactor diff size: {ins + dels} lines changed (> 500)")
    return reasons


def classify_merge_danger(
    changed_files: List[str],
    diff_stat: str = "",
    diff_text: str = "",
    is_refactor: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """Classifies merge door risk (Two-Way vs One-Way) and populates blast_radius telemetry."""
    norm_files = [_norm_rel_path(f) for f in changed_files if str(f).strip()]
    db_triggers = [f for f in norm_files if _is_one_way_door_path(f)]
    one_way_triggers = list(db_triggers)
    one_way_reasons: List[str] = [f"Database migration/schema touched: {f}" for f in db_triggers]
    ins, dels = _parse_stat_counts(diff_stat)
    if is_refactor:
        one_way_reasons.extend(_collect_refactor_reasons(norm_files, ins, dels, diff_text, one_way_triggers))
    if one_way_reasons:
        summary_reason = "; ".join(one_way_reasons[:2])
        door_type = f"One-way door ({summary_reason})" if is_refactor or not db_triggers else "One-way door (Database Migration / Schema Change)"
    else:
        door_type = "Two-way door (Reversible Code / Configuration Change)"
    blast_radius = {
        "changed_file_count": len(norm_files),
        "changed_files": norm_files,
        "layers": sorted({_classify_layer(f) for f in norm_files}),
        "domains": _extract_domains(norm_files),
        "one_way_triggers": one_way_triggers,
        "one_way_reasons": one_way_reasons,
        "insertions": ins,
        "deletions": dels,
        "diff_stat": diff_stat.strip(),
    }
    return door_type, blast_radius
