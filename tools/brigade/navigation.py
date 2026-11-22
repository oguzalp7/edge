"""
Isolated Navigation & Domain Context Resolver for Edge Brigade.
Slices repository navigation docs (specs/INDEX.md, CONTEXT.md, docs/domains/*.md)
and git co-change history into a bounded <=15-line context block with [STALE] link checking.
"""

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_ROOT_DIR = Path(__file__).resolve().parents[2]
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

try:
    from tools.common.paths import to_wsl_path
except ImportError:  # pragma: no cover - standalone fallback
    def to_wsl_path(path: object) -> str:
        return str(path).replace("\\", "/")

try:
    from tools.drift.models import (
        matches_tracked_paths,
        parse_canonical_domain_doc,
        parse_domain_frontmatter,
    )
except ImportError:  # pragma: no cover - lightweight stdlib fallback
    def parse_domain_frontmatter(markdown_text: str, fallback_domain: str = "") -> Tuple[str, List[str], str]:
        if not markdown_text.startswith("---"):
            return fallback_domain, [], markdown_text
        parts = markdown_text.split("---", 2)
        if len(parts) < 3:
            return fallback_domain, [], markdown_text
        return fallback_domain, [], parts[2].lstrip("\r\n")

    def parse_canonical_domain_doc(markdown_text: str, doc_path: str, fallback_domain: str = "") -> object:
        return None

    def matches_tracked_paths(changed_files: List[str], tracked_paths: List[str]) -> List[str]:
        return []


NAV_HEADER = "### 🧭 NAVIGATION & DOMAIN CONTEXT"
_INDEX_CANDIDATES = ("specs/INDEX.md", ".edge/INDEX.md", "INDEX.md")
_GLOSSARY_CANDIDATES = ("CONTEXT.md", "GLOSSARY.md")
_ENV_DOC_CANDIDATES = (".edge/env.md", "AGENTS.md")
_DRIZZLE_OUT_RE = re.compile(r'out\s*:\s*["\']([^"\']+)["\']')
_DRIZZLE_SCHEMA_RE = re.compile(r'schema\s*:\s*["\']([^"\']+)["\']')
_ENV_MIGRATION_PATH_RE = re.compile(r"`((?:src/)?db/migrations(?:/\*)?)`")
_LOCKFILES = {
    "package-lock.json",
    "uv.lock",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
}
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")
_MD_SEP_RE = re.compile(r"^\|[\s:\-|]+\|$")
_LINK_TITLE_RE = re.compile(r'\s+(?:"[^"]*"|\'[^\']*\')\s*$')


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


def _is_target_stale(target: str, containing_dir: Path, repo_root: Path) -> bool:
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return False
    clean = target.split("#", 1)[0].strip()
    if not clean:
        return False
    if clean.startswith("/") or _DRIVE_PATH_RE.match(clean):
        return True
    try:
        repo_resolved = repo_root.resolve()
        resolved = (containing_dir / clean).resolve()
        return not resolved.is_relative_to(repo_resolved) or not resolved.exists()
    except Exception:
        return True


def _annotate_stale_links(line: str, containing_dir: Path, repo_root: Path) -> str:
    clean_line = line.rstrip()
    for target in _extract_markdown_link_targets(clean_line):
        if _is_target_stale(target, containing_dir, repo_root):
            return f"{clean_line} [STALE]" if not clean_line.endswith("[STALE]") else clean_line
    return clean_line


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
    for idx, line in enumerate(lines):
        if line.strip().lower() == "## closed concept glossary":
            scoped: List[str] = []
            for follow in lines[idx + 1 :]:
                if follow.strip().startswith("## "):
                    break
                scoped.append(follow)
            return scoped
    return lines


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


def _deed_matches(
    deed_file: Path,
    deed_domain: str,
    tracked_paths: List[str],
    rel_paths: List[str],
    dom_clean: str,
) -> bool:
    stem_or_dir = deed_file.parent.name if deed_file.name.lower() == "domain.md" else deed_file.stem
    if dom_clean and (deed_domain.lower() == dom_clean or stem_or_dir.lower() == dom_clean):
        return True
    return bool(matches_tracked_paths(rel_paths, tracked_paths))


def _is_canonical_meta_bullet(stripped: str) -> bool:
    low = stripped.lower()
    return low.startswith(("- **paths:**", "- **owner / dri:**", "- **owner/dri:**", "- **concepts:**"))


def _extract_deed_body_lines(body: str, deed_dir: Path, repo_root: Path, cap: int) -> List[str]:
    bullets: List[str] = []
    prose: List[str] = []
    for raw in body.splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or s == "---" or _is_canonical_meta_bullet(s):
            continue
        annotated = _annotate_stale_links(s, deed_dir, repo_root)
        if s.startswith(("- ", "* ")):
            bullets.append(annotated)
        else:
            prose.append(annotated)
    return (bullets + prose)[:cap]


def _collect_canonical_nav_deeds(docs_dir: Path) -> Tuple[List[Tuple[Path, bool]], Set[str]]:
    deeds: List[Tuple[Path, bool]] = []
    seen_domains: Set[str] = set()
    for sub in sorted(docs_dir.iterdir()):
        if not sub.is_dir() or sub.name.lower() == "domains":
            continue
        dom_file = sub / "DOMAIN.md"
        if dom_file.is_file():
            deeds.append((dom_file, True))
            seen_domains.add(sub.name.lower())
    return deeds, seen_domains


def _collect_legacy_nav_deeds(legacy_dir: Path, seen_domains: Set[str]) -> List[Tuple[Path, bool]]:
    if not legacy_dir.is_dir():
        return []
    return [
        (p, False)
        for p in sorted(legacy_dir.glob("*.md"))
        if p.is_file() and p.name.lower() != "domain.md" and p.stem.lower() not in seen_domains
    ]


def _iter_nav_domain_deeds(repo_root: Path) -> List[Tuple[Path, bool]]:
    """Collects canonical docs/<domain>/DOMAIN.md (preferred) and legacy docs/domains/*.md."""
    docs_dir = repo_root / "docs"
    if not docs_dir.is_dir():
        return []
    deeds, seen_domains = _collect_canonical_nav_deeds(docs_dir)
    deeds.extend(_collect_legacy_nav_deeds(docs_dir / "domains", seen_domains))
    return deeds


def _parse_deed_for_nav(
    deed_file: Path,
    is_canonical: bool,
    text: str,
    repo_root: Path,
) -> Tuple[str, List[str], str]:
    if is_canonical:
        rel = deed_file.relative_to(repo_root).as_posix()
        parsed = parse_canonical_domain_doc(text, doc_path=rel, fallback_domain=deed_file.parent.name)
        if parsed is not None:
            return parsed.domain, parsed.tracked_paths, text
    return parse_domain_frontmatter(text, fallback_domain=deed_file.stem)


def _extract_domain_deed_rows(
    repo_root: Path,
    rel_paths: List[str],
    dom_clean: str,
    limit: int = 3,
) -> List[str]:
    collected: List[str] = []
    for deed_file, is_canonical in _iter_nav_domain_deeds(repo_root):
        if len(collected) >= limit:
            break
        try:
            text = deed_file.read_text(encoding="utf-8-sig", errors="replace")
        except Exception:
            continue
        deed_domain, tracked_paths, body = _parse_deed_for_nav(deed_file, is_canonical, text, repo_root)
        if _deed_matches(deed_file, deed_domain, tracked_paths, rel_paths, dom_clean):
            remaining = limit - len(collected)
            collected.extend(_extract_deed_body_lines(body, deed_file.parent, repo_root, remaining))
    return collected[:limit]


def _inventory_nav_docs(repo_root: Path) -> List[str]:
    docs: List[str] = []
    for rel in ("AGENTS.md", *_INDEX_CANDIDATES, *_GLOSSARY_CANDIDATES):
        if (repo_root / rel).is_file():
            docs.append(rel)
    deeds = _iter_nav_domain_deeds(repo_root)
    if any(is_canon for _, is_canon in deeds):
        docs.append("docs/*/DOMAIN.md")
    domains_dir = repo_root / "docs" / "domains"
    if domains_dir.is_dir() and any(p.name.lower() != "domain.md" for p in domains_dir.glob("*.md")):
        docs.append("docs/domains/")
    return docs


def _to_glob_path(raw: str, default: str) -> str:
    cleaned = raw.strip().replace("\\", "/").lstrip("./").rstrip("/")
    if not cleaned:
        return default
    if cleaned.endswith("/*"):
        return cleaned
    return f"{cleaned}/*"


def _resolve_drizzle_config_paths(root: Path) -> Optional[Tuple[str, str]]:
    for fname in ("drizzle.config.ts", "drizzle.config.js", "drizzle.config.mjs"):
        cfg = root / fname
        if cfg.is_file():
            text = cfg.read_text(encoding="utf-8", errors="replace")
            out_m = _DRIZZLE_OUT_RE.search(text)
            if out_m:
                sch_m = _DRIZZLE_SCHEMA_RE.search(text)
                schema_glob = _to_glob_path(sch_m.group(1), "src/db/schema/*") if sch_m else "src/db/schema/*"
                return (schema_glob, _to_glob_path(out_m.group(1), "drizzle/*"))
    return None


def resolve_migration_paths(repo_path: Optional[Path] = None) -> Tuple[str, str]:
    """Resolves (schema_glob, migration_glob) from drizzle.config.*, .edge/env.md, or AGENTS.md."""
    default_paths = ("src/db/schema/*", "drizzle/*")
    if repo_path is None:
        return default_paths
    root = Path(repo_path)
    if not root.is_dir():
        return default_paths
    drizzle_paths = _resolve_drizzle_config_paths(root)
    if drizzle_paths:
        return drizzle_paths
    for rel in _ENV_DOC_CANDIDATES:
        doc = root / rel
        if doc.is_file():
            m = _ENV_MIGRATION_PATH_RE.search(doc.read_text(encoding="utf-8", errors="replace"))
            if m:
                return ("src/db/schema/*", _to_glob_path(m.group(1), "drizzle/*"))
    return default_paths


def _extract_bullets_from_lines(lines: List[str], limit: int) -> List[str]:
    rows: List[str] = []
    for raw in lines:
        s = raw.strip()
        if s.startswith(("- ", "* ")):
            rows.append(s)
            if len(rows) >= limit:
                break
    return rows


def _extract_agents_env_section_lines(text: str) -> List[str]:
    section: List[str] = []
    in_section = False
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("#"):
            if in_section:
                break
            in_section = "repo environment" in s.lower()
            continue
        if in_section:
            section.append(s)
    return section


def _extract_repo_env_rows(repo_root: Path, limit: int = 4) -> List[str]:
    env_file = repo_root / ".edge" / "env.md"
    if env_file.is_file():
        text = env_file.read_text(encoding="utf-8", errors="replace")
        return _extract_bullets_from_lines(text.splitlines(), limit)
    agents_file = repo_root / "AGENTS.md"
    if agents_file.is_file():
        text = agents_file.read_text(encoding="utf-8", errors="replace")
        return _extract_bullets_from_lines(_extract_agents_env_section_lines(text), limit)
    return []


def _select_git_anchors(repo_root: Path, rel_paths: List[str]) -> List[str]:
    repo_resolved = repo_root.resolve()
    anchors: List[str] = []
    for rel in rel_paths:
        if not rel or rel.startswith("-") or rel.startswith("/"):
            continue
        try:
            candidate = (repo_root / rel).resolve()
        except Exception:
            continue
        if candidate.is_relative_to(repo_resolved) and candidate.exists():
            if rel not in anchors:
                anchors.append(rel)
                if len(anchors) >= 3:
                    break
    return anchors


def _is_excluded_cochange_path(path_str: str, anchor_set: Set[str]) -> bool:
    norm = path_str.replace("\\", "/").strip()
    if not norm or norm in anchor_set:
        return True
    if norm.startswith(".edge/") or norm == ".edge":
        return True
    if norm.startswith("node_modules/") or "/node_modules/" in norm:
        return True
    return Path(norm).name in _LOCKFILES


def _run_git_lines(repo_root: Path, args: List[str]) -> List[str]:
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if res.returncode != 0 or not res.stdout.strip():
        return []
    return res.stdout.splitlines()


def _extract_git_cochanges(repo_root: Path, rel_paths: List[str], limit: int = 5) -> List[str]:
    if not (repo_root / ".git").exists():
        return []
    anchors = _select_git_anchors(repo_root, rel_paths)
    if not anchors:
        return []
    shas = [s.strip() for s in _run_git_lines(repo_root, ["log", "-n", "20", "--pretty=format:%H", "--", *anchors]) if s.strip()]
    if not shas:
        return []

    changed_lines = _run_git_lines(repo_root, ["show", "--name-only", "--pretty=format:", *shas])
    anchor_set = set(anchors)
    counts: Counter[str] = Counter()
    for line in changed_lines:
        norm = line.replace("\\", "/").strip()
        if not _is_excluded_cochange_path(norm, anchor_set):
            counts[norm] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [f"- {path} (co-changed {cnt}x)" for path, cnt in ranked[:limit]]


def _assemble_prioritized_lines(
    index_or_pointer: List[str],
    deed_rows: List[str],
    cochange_rows: List[str],
    glossary_rows: List[str],
    env_rows: Tuple[str, ...] = (),
    max_lines: int = 15,
) -> str:
    body_buckets = (index_or_pointer, deed_rows, list(env_rows), cochange_rows, glossary_rows)
    if not any(body_buckets):
        return ""
    lines: List[str] = [NAV_HEADER]
    for bucket in body_buckets:
        room = max_lines - len(lines)
        if room <= 0:
            break
        lines.extend(bucket[:room])
    return "\n".join(lines)


def build_navigation_context(
    repo_path: Optional[Path],
    target_paths: Optional[List[str]] = None,
    domain: str = "",
    spec_path: str = "",
) -> str:
    """
    Builds a bounded <=15-line navigation and domain context block from repository docs
    and git co-change history. Returns '' when repo is invalid or no signals exist.
    """
    if repo_path is None:
        return ""
    root = Path(repo_path)
    if not root.exists() or not root.is_dir():
        return ""

    rel_paths, tokens, dom_clean = _collect_target_tokens(root, target_paths, domain, spec_path)
    index_rows = _extract_index_rows(root, tokens, limit=5)
    deed_rows = _extract_domain_deed_rows(root, rel_paths, dom_clean, limit=3)
    glossary_rows = _extract_glossary_rows(root, tokens, limit=4)
    env_rows = _extract_repo_env_rows(root, limit=4)
    cochange_rows = _extract_git_cochanges(root, rel_paths, limit=5)

    index_or_pointer = list(index_rows)
    if not any((index_rows, deed_rows, glossary_rows, env_rows)):
        available = _inventory_nav_docs(root)
        if available:
            index_or_pointer = [f"Navigation docs available: {', '.join(available)}"]

    return _assemble_prioritized_lines(
        index_or_pointer, deed_rows, cochange_rows, glossary_rows, tuple(env_rows)
    )
