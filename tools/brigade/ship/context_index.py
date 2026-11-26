"""Ship-prep submodule: context_index."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import re

from tools.brigade.ship.constants import BOLD_TERM_RE, INDEX_TOKEN_RE, _TABLE_SEP_RE
from tools.brigade.ship.models import IndexChange

def _extract_tokens_from_line(line: str) -> List[IndexChange]:
    changes: List[IndexChange] = []
    for match in INDEX_TOKEN_RE.finditer(line):
        kind = match.group(1).rstrip(":")
        symbol = match.group(2).strip()
        if symbol:
            changes.append(IndexChange(kind=kind, symbol=symbol, raw_line=line.strip()))
    return changes


def parse_index_diff(diff_text: str) -> List[IndexChange]:
    """Parses git diff (or raw INDEX.md lines) for @route, Page, @module, Action, Schema, @spec."""
    if not diff_text or not diff_text.strip():
        return []
    is_diff = any(marker in diff_text for marker in ("diff --git", "@@ ", "+++ "))
    changes: List[IndexChange] = []
    for raw in diff_text.splitlines():
        if is_diff:
            if not raw.startswith("+") or raw.startswith("+++"):
                continue
            line = raw[1:]
        else:
            line = raw
        changes.extend(_extract_tokens_from_line(line))
    return changes


def _collect_bold_terms_from_file(fpath: Path, terms: List[str]) -> None:
    if not fpath.is_file():
        return
    for line in fpath.read_text(encoding="utf-8", errors="ignore").splitlines():
        for match in BOLD_TERM_RE.finditer(line):
            term = match.group(1).strip()
            if term and term not in terms:
                terms.append(term)


def _filter_matching_terms(terms: List[str], search_tokens: List[str]) -> List[str]:
    matched: List[str] = []
    for t in terms:
        low_t = t.lower()
        if any(tok in low_t for tok in search_tokens):
            matched.append(t)
    return (matched or terms)[:12]


def _extract_closed_glossary_entries(lines: List[str]) -> Optional[List[Tuple[str, str]]]:
    """
    If ## Closed Concept Glossary heading exists, returns [(concept_id, full_row_text)].
    Returns None when the heading is absent so callers can fall back to legacy **bold** parsing.
    """
    start_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip().lower() == "## closed concept glossary"),
        None,
    )
    if start_idx is None:
        return None

    entries: List[Tuple[str, str]] = []
    for raw in lines[start_idx + 1 :]:
        s = raw.strip()
        if s.startswith("## "):
            break
        if not s or _TABLE_SEP_RE.match(s):
            continue
        if s.startswith(("- ", "* ")):
            m = re.match(r"^[-*]\s+`?([a-z0-9][a-z0-9_-]*)`?\s*:", s)
            if m:
                entries.append((m.group(1), s))
        elif s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            cid = cells[0].strip("`").strip() if cells else ""
            if cid and cid.lower() != "concept":
                entries.append((cid, s))
    return entries


def _read_context_terms(repo: Path, search_tokens: List[str]) -> List[str]:
    context_file = repo / "CONTEXT.md"
    if context_file.is_file():
        lines = context_file.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
        glossary_entries = _extract_closed_glossary_entries(lines)
        if glossary_entries is not None:
            if not search_tokens:
                return [cid for cid, _ in glossary_entries][:12]
            lowered_tokens = [tok.lower() for tok in search_tokens]
            return [
                cid
                for cid, row in glossary_entries
                if any(tok in row.lower() for tok in lowered_tokens)
            ][:12]

    terms: List[str] = []
    for fname in ("CONTEXT.md", "GLOSSARY.md"):
        _collect_bold_terms_from_file(repo / fname, terms)
    if not search_tokens:
        return terms[:12]
    return _filter_matching_terms(terms, search_tokens)


def _compute_search_tokens(blast_radius: Dict[str, Any], index_changes: List[IndexChange]) -> List[str]:
    tokens = list(blast_radius.get("domains", []))
    for ch in index_changes:
        tokens.append(ch.symbol.lower())
    return list(dict.fromkeys(tokens))
