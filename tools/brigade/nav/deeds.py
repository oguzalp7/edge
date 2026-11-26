"""Navigation submodule: deeds."""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tools.brigade.nav.constants import matches_tracked_paths, parse_canonical_domain_doc, parse_context_glossary, parse_domain_frontmatter
from tools.brigade.nav.constants import _GLOSSARY_CANDIDATES, _INDEX_CANDIDATES
from tools.brigade.nav.stale import _annotate_stale_links

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


def _load_nav_context_globs(repo_root: Path) -> Dict[str, List[str]]:
    context_file = repo_root / "CONTEXT.md"
    if not context_file.is_file():
        return {}
    try:
        globs, _ = parse_context_glossary(context_file.read_text(encoding="utf-8-sig", errors="replace"))
        return globs
    except Exception:
        return {}


def _extract_domain_deed_rows(
    repo_root: Path,
    rel_paths: List[str],
    dom_clean: str,
    limit: int = 3,
) -> List[str]:
    context_globs = _load_nav_context_globs(repo_root)
    collected: List[str] = []
    for deed_file, is_canonical in _iter_nav_domain_deeds(repo_root):
        if len(collected) >= limit:
            break
        try:
            text = deed_file.read_text(encoding="utf-8-sig", errors="replace")
        except Exception:
            continue
        deed_domain, tracked_paths, body = _parse_deed_for_nav(deed_file, is_canonical, text, repo_root)
        effective_paths = context_globs.get(deed_domain) or tracked_paths
        if _deed_matches(deed_file, deed_domain, effective_paths, rel_paths, dom_clean):
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
