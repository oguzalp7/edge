"""
Code and test header (@concepts, @invariants, legacy tags) scanner for edge-drift.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tools.drift.models import (
    LEGACY_ERROR_TAGS,
    LEGACY_WARNING_TAGS,
    OntologyIssue,
    matches_tracked_paths,
)

_ONTOLOGY_PRUNE_DIRS = {".git", "node_modules", ".edge", ".next", "dist", "build", "__pycache__", "tests"}
_TEST_INDEX_PRUNE_DIRS = {".git", "node_modules", ".edge", ".next", "dist", "build", "__pycache__"}
_ONTOLOGY_CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
_CODING_COOKIE_RE = re.compile(r"^#.*coding[:=]")
_HEADER_TAG_RE = re.compile(r"^\s*(?:#|//|\*)?\s*(@[a-z_]+)\b(.*)$")
_INV_TOKEN_RE = re.compile(r"\[?((?:INV|PAT)-[A-Z0-9]+(?:-[A-Z0-9]+)+)\]?")
_DIRECTIVE_LINES = {'"use client";', "'use client';", '"use strict";', "'use strict';", '"use client"', "'use client'", '"use strict"', "'use strict'"}


def _consume_delimited_block(
    lines: List[str],
    start_idx: int,
    open_len: int,
    end_token: str,
) -> Tuple[List[str], int]:
    """Extracts lines inside a docstring or /* ... */ comment block."""
    first = lines[start_idx].strip()[open_len:]
    if end_token in first:
        inner = first.split(end_token, 1)[0].strip()
        return ([inner] if inner else []), start_idx + 1

    collected: List[str] = [first] if first else []
    idx = start_idx + 1
    while idx < len(lines):
        curr = lines[idx]
        if end_token in curr:
            before = curr.split(end_token, 1)[0].strip()
            if before:
                collected.append(before)
            return collected, idx + 1
        collected.append(curr)
        idx += 1
    return collected, idx


def _extract_header_lines(text: str, max_lines: int = 30) -> List[str]:
    """Extracts leading header comment/docstring lines within top max_lines."""
    lines = text.splitlines()[:max_lines]
    header_lines: List[str] = []
    idx = 0
    while idx < len(lines):
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("#!") or _CODING_COOKIE_RE.match(stripped) or stripped in _DIRECTIVE_LINES:
            idx += 1
            continue
        if stripped.startswith(('"""', "'''")):
            block, idx = _consume_delimited_block(lines, idx, 3, stripped[:3])
            header_lines.extend(block)
            continue
        if stripped.startswith("/*"):
            block, idx = _consume_delimited_block(lines, idx, 2, "*/")
            header_lines.extend(block)
            continue
        if stripped.startswith(("#", "//")):
            header_lines.append(stripped)
            idx += 1
            continue
        break
    return header_lines


def _validate_header_tag(
    tag: str,
    rest: str,
    rel_path: str,
    valid_concepts: Set[str],
    valid_invariants: Set[str],
    invariant_index: Optional[Dict[str, List[str]]] = None,
) -> List[OntologyIssue]:
    """Validates one anchored @tag line inside a file's leading header."""
    if tag in LEGACY_ERROR_TAGS:
        return [OntologyIssue("ERROR", "LEGACY_TAG", rel_path, f"Banned legacy tag {tag}")]
    if tag in LEGACY_WARNING_TAGS:
        return [OntologyIssue("WARNING", "LEGACY_TAG", rel_path, f"Legacy tag {tag}")]

    issues: List[OntologyIssue] = []
    if tag == "@concepts":
        for item in rest.split(","):
            cid = item.strip().strip("`").strip()
            if cid and cid not in valid_concepts:
                issues.append(OntologyIssue("ERROR", "UNKNOWN_CONCEPT", rel_path, f"Unknown concept '{cid}'"))
        return issues

    if tag == "@invariants":
        for inv_id in _INV_TOKEN_RE.findall(rest):
            if inv_id not in valid_invariants:
                issues.append(OntologyIssue("ERROR", "UNKNOWN_INVARIANT", rel_path, f"Unknown invariant '{inv_id}'"))
            elif invariant_index is not None:
                invariant_index.setdefault(inv_id, []).append(rel_path)
    return issues


def _walk_code_tree(
    scan_root: Path,
    norm_repo: Path,
    prune_dirs: Set[str],
    tracked_globs: Optional[List[str]] = None,
) -> List[Tuple[str, Path]]:
    """Walks a directory via os.walk with prune set, returning matching code files."""
    if not scan_root.is_dir():
        return []
    files: List[Tuple[str, Path]] = []
    for root, dirs, filenames in os.walk(scan_root):
        dirs[:] = sorted(d for d in dirs if d not in prune_dirs)
        for fname in sorted(filenames):
            fpath = Path(root) / fname
            if fpath.suffix.lower() not in _ONTOLOGY_CODE_SUFFIXES:
                continue
            rel = fpath.relative_to(norm_repo).as_posix()
            if tracked_globs is None or matches_tracked_paths([rel], tracked_globs):
                files.append((rel, fpath))
    return files


def _scan_files_for_headers(
    file_entries: List[Tuple[str, Path]],
    valid_concepts: Set[str],
    valid_invariants: Set[str],
    invariant_index: Dict[str, List[str]],
    invariants_only: bool = False,
) -> List[OntologyIssue]:
    """Scans top-30L headers across files for ontology tags and invariant indexing."""
    issues: List[OntologyIssue] = []
    for rel_path, fpath in file_entries:
        text = fpath.read_text(encoding="utf-8-sig", errors="replace")
        for hdr_line in _extract_header_lines(text, max_lines=30):
            m = _HEADER_TAG_RE.match(hdr_line)
            if not m:
                continue
            tag = m.group(1)
            if invariants_only and tag != "@invariants":
                continue
            issues.extend(
                _validate_header_tag(tag, m.group(2), rel_path, valid_concepts, valid_invariants, invariant_index)
            )
    return issues
