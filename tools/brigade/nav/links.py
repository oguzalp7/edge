"""Navigation submodule: links."""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tools.brigade.nav.constants import to_wsl_path
from tools.brigade.nav.constants import _LINK_TITLE_RE

def _normalize_repo_rel_path(raw: str, repo_root: Path) -> str:
    """Converts Windows/WSL/absolute paths into a clean repo-relative POSIX path."""
    if not raw:
        return ""
    wsl = to_wsl_path(raw).replace("\\", "/").strip()
    repo_wsl = to_wsl_path(repo_root.resolve()).replace("\\", "/").rstrip("/")
    if wsl.lower().startswith(repo_wsl.lower() + "/"):
        wsl = wsl[len(repo_wsl) + 1 :]
    elif wsl.lower() == repo_wsl.lower():
        return ""
    while wsl.startswith("./"):
        wsl = wsl[2:]
    return wsl.rstrip("/")


def _collect_target_tokens(
    repo_root: Path,
    target_paths: Optional[List[str]],
    domain: str,
    spec_path: str,
) -> Tuple[List[str], Set[str], str]:
    """Derives normalized repo-relative paths and lowercase matching tokens."""
    rel_paths: List[str] = []
    tokens: Set[str] = set()
    raw_items = list(target_paths or [])
    if spec_path:
        raw_items.append(spec_path)

    for raw in raw_items:
        rel = _normalize_repo_rel_path(str(raw), repo_root)
        if not rel:
            continue
        if rel not in rel_paths:
            rel_paths.append(rel)
        p = Path(rel)
        tokens.add(rel.lower())
        if p.name:
            tokens.add(p.name.lower())
        if p.stem:
            tokens.add(p.stem.lower())

    dom_clean = domain.strip().lower()
    if dom_clean:
        tokens.add(dom_clean)
    return rel_paths, tokens, dom_clean


def _strip_paired_backticks(line: str) -> str:
    """Removes paired `...` code spans while handling unclosed trailing backticks gracefully."""
    out: List[str] = []
    idx = 0
    n = len(line)
    while idx < n:
        if line[idx] == "`":
            end = line.find("`", idx + 1)
            if end != -1:
                idx = end + 1
                continue
            idx += 1
            continue
        out.append(line[idx])
        idx += 1
    return "".join(out)


def _scan_balanced_paren_target(text: str, start_idx: int) -> Tuple[str, int]:
    """Scans balanced parentheses starting immediately after ']('."""
    depth = 1
    idx = start_idx
    n = len(text)
    while idx < n and depth > 0:
        ch = text[idx]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth > 0:
            idx += 1
    if depth != 0:
        return "", start_idx
    return text[start_idx:idx].strip(), idx + 1


def _clean_link_target(raw_target: str) -> str:
    cleaned = _LINK_TITLE_RE.sub("", raw_target.strip()).strip()
    if cleaned.startswith("<") and cleaned.endswith(">"):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _extract_markdown_link_targets(line: str) -> List[str]:
    """Extracts Markdown link destinations with balanced-parenthesis support."""
    sanitized = _strip_paired_backticks(line)
    targets: List[str] = []
    pos = 0
    while True:
        marker = sanitized.find("](", pos)
        if marker == -1:
            break
        raw_target, next_pos = _scan_balanced_paren_target(sanitized, marker + 2)
        if raw_target:
            cleaned = _clean_link_target(raw_target)
            if cleaned:
                targets.append(cleaned)
        pos = next_pos if next_pos > marker + 2 else marker + 2
    return targets

