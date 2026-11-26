"""Ship-prep submodule: danger_paths."""

from typing import List, Dict, Any, Optional, Tuple
import re

from tools.brigade.ship.constants import _AUTH_SEGMENT_RE
from tools.brigade.ship.paths import _norm_rel_path

def _is_one_way_door_path(norm_path: str) -> bool:
    low = norm_path.lower()
    if low.startswith("drizzle/") or "/drizzle/" in low:
        return True
    if low.startswith("src/db/schema") or "/db/schema/" in low or low.endswith("/db/schema"):
        return True
    return low.endswith(".sql")


def _is_refactor_auth_path(norm_path: str) -> bool:
    return bool(_AUTH_SEGMENT_RE.search(_norm_rel_path(norm_path)))


def _after_block_end(s: str) -> Optional[str]:
    after = s.split("*/", 1)[1].strip()
    return after if after and not after.startswith("//") else None


def _strip_line_comments_for_diff(lines: List[str]) -> str:
    cleaned: List[str] = []
    in_block = False
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if in_block or s.startswith("/*"):
            in_block = "*/" not in s
            if not in_block and (after := _after_block_end(s)):
                cleaned.append(after)
            continue
        if not s.startswith(("//", "*")):
            cleaned.append(raw)
    return "\n".join(cleaned)


def _extract_balanced_parens(text: str, open_idx: int) -> str:
    depth = 0
    chars: List[str] = []
    for ch in text[open_idx:]:
        if ch == "(":
            depth += 1
            if depth > 1:
                chars.append(ch)
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
            chars.append(ch)
        elif depth >= 1:
            chars.append(ch)
    return re.sub(r"\s+", " ", "".join(chars)).strip().rstrip(",").strip()
