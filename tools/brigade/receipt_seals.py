"""Seal 1 (Intent/Door) and Seal 2 (Metric Delta) validators for RefactorReceipt."""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from tools.brigade.receipt_git import get_diff_changed_files, get_git_head_sha
from tools.brigade.receipt_models import HIGHER_IS_BETTER_METRICS, compute_changed_files_hash
from tools.common import normalize_target_path


def _check_git_freshness(recorded_sha: str, recorded_hash: str, git_root: Path, base_ref: Optional[str]) -> Optional[Tuple[bool, str, Dict[str, Any]]]:
    git_dir = normalize_target_path(git_root)
    head_sha = get_git_head_sha(git_dir)
    if head_sha and recorded_sha != head_sha:
        return False, f"Stale receipt: commit_sha '{recorded_sha}' != current HEAD '{head_sha}'.", {"error": "STALE_RECEIPT_COMMIT", "recorded_sha": recorded_sha, "head_sha": head_sha}
    if base_ref:
        cur_files = get_diff_changed_files(git_dir, base_ref)
        cur_hash = compute_changed_files_hash(cur_files)
        if cur_files and cur_hash != recorded_hash:
            return False, "Stale receipt: changed_files_hash does not match current branch diff.", {"error": "STALE_RECEIPT_DIFF", "current_hash": cur_hash, "recorded_hash": recorded_hash}
    return None


def _check_metric_target(key: str, target_val: Any, after_val: Any) -> Optional[Tuple[bool, str, Dict[str, Any]]]:
    if after_val is None:
        return False, f"Seal 2 failed: required target metric '{key}' is null/missing.", {"error": "NULL_TARGET_METRIC", "metric": key}
    if not isinstance(after_val, (int, float)) or not isinstance(target_val, (int, float)):
        return False, f"Seal 2 failed: non-numeric value for metric '{key}'.", {"error": "INVALID_METRIC_VALUE", "metric": key}
    failed = (after_val < target_val) if key in HIGHER_IS_BETTER_METRICS else (after_val > target_val)
    if failed:
        op = "is below" if key in HIGHER_IS_BETTER_METRICS else "exceeds"
        return False, f"Seal 2 failed: '{key}'={after_val} {op} target {target_val}.", {"error": "METRIC_TARGET_FAILED", "metric": key, "after": after_val, "target": target_val}
    return None


def verify_seal_1_intent(
    data: Dict[str, Any], repo_path: Optional[Path] = None, base_ref: Optional[str] = None, work_dir: Optional[Path] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Verify Seal 1 behavior lock, changed_files_hash, and git commit freshness."""
    seal_1 = data.get("seal_1_intent")
    if not isinstance(seal_1, dict):
        return False, "Missing or invalid seal_1_intent.", {"error": "MISSING_SEAL_1"}
    if seal_1.get("behavior_preserved") is not True:
        return False, "Seal 1 failed: behavior_preserved must be True.", {"error": "BEHAVIOR_NOT_PRESERVED"}
    changed_files = seal_1.get("changed_files")
    if not isinstance(changed_files, list):
        return False, "Seal 1 failed: changed_files must be a list.", {"error": "INVALID_CHANGED_FILES"}
    expected_hash, recorded_hash = compute_changed_files_hash(changed_files), str(seal_1.get("changed_files_hash") or "")
    if not recorded_hash or recorded_hash != expected_hash:
        return False, "Seal 1 failed: changed_files_hash mismatch (tampered or stale).", {"error": "CHANGED_FILES_HASH_MISMATCH", "expected_hash": expected_hash, "recorded_hash": recorded_hash}
    git_root = work_dir or repo_path
    if git_root is not None:
        stale = _check_git_freshness(str(seal_1.get("commit_sha") or ""), recorded_hash, git_root, base_ref)
        if stale:
            return stale
    return True, "Seal 1 intent and door lock verified.", {"changed_files_hash": recorded_hash}


def verify_seal_2_metrics(data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """Verify Seal 2 metric targets against measured post-refactor metrics."""
    seal_2 = data.get("seal_2_metrics")
    if not isinstance(seal_2, dict):
        return False, "Missing or invalid seal_2_metrics.", {"error": "MISSING_SEAL_2"}
    after = seal_2.get("after")
    if not isinstance(after, dict):
        return False, "Seal 2 failed: missing 'after' metrics.", {"error": "MISSING_AFTER_METRICS"}
    targets = {} if seal_2.get("metric_targets") is None else seal_2.get("metric_targets")
    if not isinstance(targets, dict):
        return False, "Seal 2 failed: metric_targets must be a dict.", {"error": "INVALID_METRIC_TARGETS"}
    for key, target_val in targets.items():
        err = _check_metric_target(key, target_val, after.get(key))
        if err:
            return err
    return True, "Seal 2 metric delta verified.", {"after": after, "metric_targets": targets}
