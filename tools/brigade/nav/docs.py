"""Navigation submodule: docs."""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tools.brigade.nav.constants import _GLOSSARY_CANDIDATES, _INDEX_CANDIDATES, _MD_SEP_RE
from tools.brigade.nav.stale import _annotate_stale_links

def _find_first_existing(repo_root: Path, candidates: Tuple[str, ...]) -> Optional[Path]:
    for rel in candidates:
        p = repo_root / rel
        if p.is_file():
            return p
    return None


def _line_matches_tokens(stripped: str, tokens: Set[str]) -> bool:
    if not tokens:
        return False
    lowered = stripped.lower()
    return any(tok in lowered for tok in tokens)


def _is_table_header_row(lines: List[str], idx: int, stripped: str) -> bool:
    if not stripped.startswith("|") or idx + 1 >= len(lines):
        return False
    return bool(_MD_SEP_RE.match(lines[idx + 1].strip()))


def _is_skippable_doc_line(stripped: str) -> bool:
    if not stripped or stripped.startswith("#"):
        return True
    return bool(_MD_SEP_RE.match(stripped))


def _is_index_candidate(lines: List[str], idx: int, stripped: str, tokens: Set[str]) -> bool:
    if _is_skippable_doc_line(stripped) or _is_table_header_row(lines, idx, stripped):
        return False
    if not stripped.startswith(("|", "- ", "* ")):
        return False
    return _line_matches_tokens(stripped, tokens)


def _extract_index_rows(repo_root: Path, tokens: Set[str], limit: int = 5) -> List[str]:
    index_file = _find_first_existing(repo_root, _INDEX_CANDIDATES)
    if not index_file or not tokens:
        return []
    lines = index_file.read_text(encoding="utf-8", errors="replace").splitlines()
    matched: List[str] = []
    table_count = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not _is_index_candidate(lines, idx, stripped, tokens):
            continue
        if stripped.startswith("|"):
            if table_count >= limit:
                continue
            table_count += 1
        matched.append(_annotate_stale_links(stripped, index_file.parent, repo_root))
        if len(matched) >= 8:
            break
    return matched


def _is_glossary_row(stripped: str) -> bool:
    if stripped.startswith(("|", "- ", "* ")):
        return True
    return ":" in stripped


def _slice_closed_concept_glossary(lines: List[str]) -> List[str]:
    """Scopes lines to ## Closed Concept Glossary when that heading is present."""
    start_idx = next((i for i, l in enumerate(lines) if l.strip().lower() == "## closed concept glossary"), None)
    if start_idx is None:
        return lines
    scoped: List[str] = []
    for follow in lines[start_idx + 1 :]:
        if follow.strip().startswith("## "):
            break
        scoped.append(follow)
    return scoped


def _extract_glossary_rows(repo_root: Path, tokens: Set[str], limit: int = 4) -> List[str]:
    glossary_file = _find_first_existing(repo_root, _GLOSSARY_CANDIDATES)
    if not glossary_file or not tokens:
        return []
    raw_lines = glossary_file.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    lines = _slice_closed_concept_glossary(raw_lines) if glossary_file.name == "CONTEXT.md" else raw_lines
    matched: List[str] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if _is_skippable_doc_line(stripped) or _is_table_header_row(lines, idx, stripped):
            continue
        if _is_glossary_row(stripped) and _line_matches_tokens(stripped, tokens):
            matched.append(_annotate_stale_links(stripped, repo_root, repo_root))
            if len(matched) >= limit:
                break
    return matched
