"""Ship-prep submodule: spec_expected_sections."""

from typing import List, Dict, Any, Optional, Tuple
import re

from tools.brigade.ship.paths import _norm_rel_path

def _parse_inline_yaml_list(val: str) -> List[str]:
    return [_norm_rel_path(x.strip().strip("'\"`")) for x in val[1:-1].split(",") if x.strip()]


def _read_yaml_block_items(lines: Any) -> List[str]:
    items: List[str] = []
    for sub in lines:
        st = sub.strip()
        if st.startswith("- "):
            val = _norm_rel_path(st[2:].strip().strip("'\"`"))
            if val:
                items.append(val)
        elif st and not st.startswith("#"):
            break
    return items


def _extract_frontmatter_expected(text: str) -> List[str]:
    if not text.startswith("---"):
        return []
    parts = text.split("---", 2)
    if len(parts) < 3:
        return []
    lines = iter(parts[1].splitlines())
    for raw in lines:
        s = raw.strip()
        if not s.startswith("expected_files:"):
            continue
        val = s[len("expected_files:"):].strip()
        if val.startswith("[") and val.endswith("]"):
            return [i for i in _parse_inline_yaml_list(val) if i]
        return _read_yaml_block_items(lines)
    return []


def _parse_bullet_path(line: str) -> Optional[str]:
    if not line.startswith(("- ", "* ")):
        return None
    parts = line[2:].split()
    if not parts:
        return None
    norm = _norm_rel_path(parts[0].strip("`',\""))
    return norm if norm and ("/" in norm or "." in norm) else None


def _extract_section_expected(lines: List[str]) -> List[str]:
    items: List[str] = []
    in_sec = False
    for raw in lines:
        s = raw.strip()
        if re.match(r"^#{2,3}\s+(?:\d+\.\s*)?expected\s+files", s, re.IGNORECASE):
            in_sec = True
            continue
        if in_sec and (s.startswith("#") or s == "---"):
            break
        if in_sec:
            parsed = _parse_bullet_path(s)
            if parsed:
                items.append(parsed)
    return items
