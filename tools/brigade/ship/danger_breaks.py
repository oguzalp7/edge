"""Ship-prep submodule: danger_breaks."""

from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.danger_paths import _strip_line_comments_for_diff
from tools.brigade.ship.danger_diff import _extract_export_summary

def _split_diff_by_file(diff_text: str) -> List[Tuple[str, List[str], List[str]]]:
    chunks: List[Tuple[str, List[str], List[str]]] = []
    cur_file = "<diff>"
    rem: List[str] = []
    add: List[str] = []

    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            if rem or add:
                chunks.append((cur_file, rem, add))
            parts = line.split()
            cur_file = parts[-1][2:] if parts and parts[-1].startswith("b/") else "<diff>"
            rem, add = [], []
        elif line.startswith("-") and not line.startswith("---"):
            rem.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            add.append(line[1:])
    if rem or add:
        chunks.append((cur_file, rem, add))
    return chunks


def _detect_exported_api_breaks(diff_text: str) -> List[str]:
    if not diff_text or not diff_text.strip():
        return []

    reasons: List[str] = []
    for fpath, rem_lines, add_lines in _split_diff_by_file(diff_text):
        low = fpath.lower()
        if any(marker in low for marker in (".test.", ".spec.", ".md", ".json")):
            continue
        rem_text = _strip_line_comments_for_diff(rem_lines)
        add_text = _strip_line_comments_for_diff(add_lines)
        if not rem_text.strip():
            continue

        rem = _extract_export_summary(rem_text)
        add = _extract_export_summary(add_text)

        for sym in sorted(rem["named_exports"] - add["named_exports"]):
            reasons.append(f"Exported symbol removed ({fpath}): {sym}")
        for fn_name, rem_sigs in sorted(rem["func_sigs"].items()):
            if fn_name in add["func_sigs"] and not rem_sigs.issubset(add["func_sigs"][fn_name]):
                reasons.append(f"Exported function signature changed ({fpath}): {fn_name}")
        for alias, mod in sorted(rem["star_exports"] - add["star_exports"]):
            label = f"* as {alias} from {mod}" if alias else f"* from {mod}"
            reasons.append(f"Wildcard re-export removed ({fpath}): {label}")
        if rem["has_default"] and not add["has_default"]:
            reasons.append(f"Default export removed ({fpath})")
        if rem["module_export_keys"] and add["module_export_keys"]:
            for key in sorted(rem["module_export_keys"] - add["module_export_keys"]):
                reasons.append(f"CommonJS module.exports key removed ({fpath}): {key}")
        elif rem["has_module_exports"] and not add["has_module_exports"]:
            reasons.append(f"CommonJS module.exports removed ({fpath})")

    return reasons
