"""Ship-prep submodule: spec_callstack."""

from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.constants import _CALLSTACK_HEADING_RE, _FENCE_BLOCK_RE, _HEADING_LEVEL_RE
from tools.brigade.ship.spec_summary import _flush_flow_buf, _is_flow_or_tree_line

def _append_unique_block(blocks: List[str], text: str) -> None:
    if text and text not in blocks:
        blocks.append(text)


def _collect_section_callstacks(section_lines: List[str]) -> List[str]:
    blocks: List[str] = []
    flow_buf: List[str] = []
    in_fence, fence_lang, fence_buf = False, "", []
    for raw in section_lines:
        s = raw.strip()
        if s.startswith("```"):
            _flush_flow_buf(flow_buf, blocks)
            if not in_fence:
                in_fence, fence_lang, fence_buf = True, s[3:].strip().lower(), []
                continue
            if fence_lang != "mermaid":
                _append_unique_block(blocks, "\n".join(fence_buf).strip())
            in_fence = False
            continue
        if in_fence:
            fence_buf.append(raw.rstrip())
        elif _is_flow_or_tree_line(s):
            flow_buf.append(raw.rstrip())
        else:
            _flush_flow_buf(flow_buf, blocks)
    _flush_flow_buf(flow_buf, blocks)
    return blocks


def _collect_heading_callstack_blocks(lines: List[str]) -> List[str]:
    blocks: List[str] = []
    sec_lines: List[str] = []
    sec_level: Optional[int] = None
    for raw in lines:
        s = raw.strip()
        hm = _HEADING_LEVEL_RE.match(s)
        if _CALLSTACK_HEADING_RE.match(s):
            blocks.extend(_collect_section_callstacks(sec_lines))
            sec_lines, sec_level = [], len(hm.group(1)) if hm else 2
            continue
        if sec_level is not None and ((hm and len(hm.group(1)) <= sec_level) or s == "---"):
            blocks.extend(_collect_section_callstacks(sec_lines))
            sec_lines, sec_level = [], None
            continue
        if sec_level is not None:
            sec_lines.append(raw)
    if sec_level is not None:
        blocks.extend(_collect_section_callstacks(sec_lines))
    return blocks


def _is_fallback_callstack_block(lang: str, body: str) -> bool:
    if lang == "mermaid" or not body:
        return False
    if "├──" in body or "└──" in body:
        return True
    arrow_lines = sum(1 for ln in body.splitlines() if "->" in ln or "→" in ln)
    return arrow_lines >= 2


def _extract_callstack_blocks(text: str, lines: List[str], has_mermaid: bool = False) -> List[str]:
    blocks = _collect_heading_callstack_blocks(lines)
    if not blocks and not has_mermaid:
        for m in _FENCE_BLOCK_RE.finditer(text):
            lang, body = m.group(1).strip().lower(), m.group(2).strip()
            if _is_fallback_callstack_block(lang, body) and body not in blocks:
                blocks.append(body)
    unique: List[str] = []
    for b in blocks:
        if b not in unique:
            unique.append(b)
    return unique[:3]
