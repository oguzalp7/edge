"""Ship-prep submodule: spec_parser."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import re

from tools.brigade.ship.constants import _CRIT_ID_RE, _HEADING_LEVEL_RE, _MERMAID_BLOCK_RE, _TABLE_SEP_RE
from tools.brigade.ship.models import SpecDigest
from tools.brigade.ship.spec_summary import _extract_spec_matrix_rows, _extract_spec_title_and_summary
from tools.brigade.ship.spec_callstack import _extract_callstack_blocks

def _parse_crit_table_row(s: str) -> Optional[Dict[str, str]]:
    if not s.startswith("|") or _TABLE_SEP_RE.match(s):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    if not cells:
        return None
    m = _CRIT_ID_RE.search(cells[0])
    if not m:
        return None
    cid = m.group(1)
    if len(cells) >= 3:
        title = cells[1].strip("`*") or cid
        exp = cells[2].strip("`*") or title
    elif len(cells) == 2:
        title, exp = cid, cells[1].strip("`*")
    else:
        title, exp = cid, cells[0]
    return {"id": cid, "title": title, "expectation": exp}


def _parse_crit_line_item(s: str) -> Optional[Tuple[Dict[str, str], bool]]:
    if s.startswith("|") or not _CRIT_ID_RE.search(s):
        return None
    m = _CRIT_ID_RE.search(s)
    assert m is not None
    cid = m.group(1)
    is_heading = bool(_HEADING_LEVEL_RE.match(s))
    cleaned = re.sub(r"^#{1,6}\s+|^[-*]\s+", "", s).replace("**", "").replace("`", "").strip()
    after_id = cleaned.split(cid, 1)[1].lstrip(" :.-)").strip()
    if ":" in after_id:
        title_p, exp_p = after_id.split(":", 1)
        return {"id": cid, "title": title_p.strip("() ") or cid, "expectation": exp_p.strip() or title_p.strip()}, is_heading and not exp_p.strip()
    return {"id": cid, "title": after_id.strip("() ") or cid, "expectation": after_id.strip() or cid}, is_heading


def _collect_heading_bullets(lines: List[str], start_idx: int) -> str:
    bullets: List[str] = []
    for raw in lines[start_idx + 1:]:
        st = raw.strip()
        if not st:
            continue
        if st.startswith("#") or st == "---":
            break
        if st.startswith(("- ", "* ")):
            bullets.append(st[2:].replace("**", "").strip())
            if len(bullets) >= 2:
                break
    return "; ".join(bullets)


def _extract_acceptance_criteria(lines: List[str]) -> List[Dict[str, str]]:
    criteria: List[Dict[str, str]] = []
    seen_ids: set = set()
    for idx, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue
        entry = _parse_crit_table_row(s)
        needs_bullets = False
        if entry is None:
            parsed = _parse_crit_line_item(s)
            if parsed:
                entry, needs_bullets = parsed
        if not entry or entry["id"] in seen_ids:
            continue
        if needs_bullets:
            sub = _collect_heading_bullets(lines, idx)
            if sub:
                entry["expectation"] = sub
        seen_ids.add(entry["id"])
        criteria.append(entry)
    return criteria


def parse_spec_document(spec_path: Path, rel_path: str = "") -> SpecDigest:
    """Parses a Markdown specification into title, summary, Mermaid, call-stack blocks, and criteria."""
    eff_rel = rel_path or str(spec_path).replace("\\", "/")
    if not spec_path.is_file():
        return SpecDigest(path=eff_rel, title=spec_path.stem, summary="")
    text = spec_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    title, summary = _extract_spec_title_and_summary(lines, spec_path.stem)
    mermaids = [m.group(1).strip() for m in _MERMAID_BLOCK_RE.finditer(text) if m.group(1).strip()]
    matrix = _extract_spec_matrix_rows(lines)
    callstacks = _extract_callstack_blocks(text, lines, has_mermaid=bool(mermaids))
    criteria = _extract_acceptance_criteria(lines)
    return SpecDigest(
        path=eff_rel,
        title=title,
        summary=summary,
        mermaid_blocks=mermaids,
        matrix_rows=matrix,
        callstack_blocks=callstacks,
        acceptance_criteria=criteria,
    )
