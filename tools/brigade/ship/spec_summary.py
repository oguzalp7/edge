"""Ship-prep submodule: spec_summary."""

from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.constants import _TABLE_SEP_RE

def _extract_spec_title_and_summary(lines: List[str], fallback_title: str) -> Tuple[str, str]:
    title = fallback_title
    summary_lines: List[str] = []
    in_fence = False
    for raw in lines:
        s = raw.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s:
            continue
        if s.startswith("# ") and title == fallback_title:
            title = s[2:].strip()
            continue
        if not s.startswith(("#", "|", "---", ">")) and len(summary_lines) < 2:
            summary_lines.append(s)
    return title, " ".join(summary_lines)


def _extract_spec_matrix_rows(lines: List[str], limit: int = 7) -> List[str]:
    rows: List[str] = []
    for raw in lines:
        s = raw.strip()
        if s.startswith("|") and not _TABLE_SEP_RE.match(s):
            rows.append(s)
            if len(rows) >= limit:
                break
    return rows


def _is_flow_or_tree_line(line: str) -> bool:
    return any(g in line for g in ("├──", "└──", "│", "->", "→"))


def _flush_flow_buf(buf: List[str], blocks: List[str]) -> None:
    text = "\n".join(buf).strip()
    if text and text not in blocks:
        blocks.append(text)
    buf.clear()
