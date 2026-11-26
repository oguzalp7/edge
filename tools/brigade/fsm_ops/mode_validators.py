"""Surgery exit validation modes A, B, and C."""

from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from tools.brigade.fsm_ops.spec_files import _is_non_prod_file


def _check_missing_expected_files(
    expected_files: List[str],
    all_changed_files: List[str],
) -> Tuple[List[str], bool]:
    from tools.drift.models import matches_tracked_paths

    missing = []
    has_glob = False
    for entry in expected_files:
        norm = entry.replace("\\", "/").strip()
        if norm.startswith("./"):
            norm = norm[2:]
        if "*" in norm or "?" in norm:
            has_glob = True
            if not any(matches_tracked_paths([f], [norm]) for f in all_changed_files):
                missing.append(entry)
        elif norm not in all_changed_files:
            missing.append(entry)
    return missing, has_glob


def _validate_mode_a(
    expected_files: List[str],
    target_file_norm: str,
    all_changed_files: List[str],
    prod_changed_files: List[str],
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validates Mode A: 100% expected_files modified + scope drift protection."""
    from tools.drift.models import matches_tracked_paths

    missing, has_glob = _check_missing_expected_files(expected_files, all_changed_files)
    if missing:
        return (
            False,
            f"Incomplete Feature Implementation: Expected file(s) not modified/created: {missing}",
            {"missing_files": missing, "changed_files": all_changed_files},
        )

    if has_glob and not prod_changed_files:
        return (
            False,
            "Incomplete Feature Implementation: No production files were modified or created in dynamic slice.",
            {"missing_files": expected_files, "changed_files": all_changed_files},
        )

    allowed = list(expected_files)
    if target_file_norm and target_file_norm not in allowed:
        allowed.append(target_file_norm)

    unexpected = [pf for pf in prod_changed_files if not matches_tracked_paths([pf], allowed)]
    if unexpected:
        return (
            False,
            f"Deterministic Spec-Code Scope Drift: Modified production files outside expected_files: {unexpected}",
            {"unexpected_files": unexpected, "changed_files": all_changed_files},
        )

    return True, "", {}


def _validate_mode_b(
    target_file_norm: str,
    all_changed_files: List[str],
    target_file_raw: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validates Mode B: Single target_file modified."""
    if target_file_norm not in all_changed_files:
        return (
            False,
            f"Target file '{target_file_raw}' was not modified or created.",
            {"modified_files": all_changed_files},
        )
    return True, "", {}


def _validate_mode_c(
    prod_changed_files: List[str],
    all_changed_files: List[str],
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validates Mode C: At least 1 production file modified in dynamic slice."""
    if not prod_changed_files:
        return (
            False,
            "No production files were modified or created in dynamic slice.",
            {"changed_files": all_changed_files},
        )
    return True, "", {}
