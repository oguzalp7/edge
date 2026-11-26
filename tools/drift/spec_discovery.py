"""
Domain contract discovery and CONTEXT.md glob loading for edge-drift.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from tools.common.paths import normalize_target_path
from tools.drift.models import (
    DomainContract,
    DriftCheckResult,
    SpecDiscoveryReport,
    parse_canonical_domain_doc,
    parse_context_glossary,
    parse_domain_frontmatter,
)
from tools.drift.spec_archive import archive_ephemeral_spec

EXCLUDED_SPEC_NAMES = {"readme.md", "architecture.md", "instructions.md", "coding_standards.md"}


def _collect_legacy_domain_entries(
    docs_dir: Path, canonical_by_domain: Dict[str, Tuple[str, Path, bool]]
) -> List[Tuple[str, Path, bool]]:
    legacy_dir = docs_dir / "domains"
    if not legacy_dir.is_dir():
        return []
    entries: List[Tuple[str, Path, bool]] = []
    for p in sorted(legacy_dir.glob("*.md")):
        if not p.is_file() or p.name.lower() == "domain.md":
            continue
        try:
            text = p.read_text(encoding="utf-8-sig", errors="replace")
            dom_name, _, _ = parse_domain_frontmatter(text, fallback_domain=p.stem)
        except Exception:
            dom_name = p.stem
        if dom_name.lower() in canonical_by_domain or p.stem.lower() in canonical_by_domain:
            continue
        entries.append((dom_name, p, False))
    return entries


def _discover_domain_contract_files(norm_repo: Path) -> List[Tuple[str, Path, bool]]:
    """Discovers canonical docs/<domain>/DOMAIN.md and legacy docs/domains/*.md contracts."""
    docs_dir = norm_repo / "docs"
    if not docs_dir.is_dir():
        return []
    canonical_by_domain: Dict[str, Tuple[str, Path, bool]] = {}
    for sub in sorted(docs_dir.iterdir()):
        dom_file = sub / "DOMAIN.md"
        if not sub.is_dir() or sub.name.lower() == "domains" or not dom_file.is_file():
            continue
        rel = dom_file.relative_to(norm_repo).as_posix()
        try:
            parsed = parse_canonical_domain_doc(dom_file.read_text(encoding="utf-8-sig", errors="replace"), doc_path=rel, fallback_domain=sub.name)
            dom_name = parsed.domain or sub.name
        except Exception:
            dom_name = sub.name
        if dom_name.lower() != "domains":
            canonical_by_domain[dom_name.lower()] = (dom_name, dom_file, True)

    entries = list(canonical_by_domain.values())
    entries.extend(_collect_legacy_domain_entries(docs_dir, canonical_by_domain))
    entries.sort(key=lambda item: item[1].relative_to(norm_repo).as_posix())
    return entries


def discover_specs(repo_path: Union[Path, str], include_cached_issues: bool = True) -> SpecDiscoveryReport:
    """Finds canonical domain deeds vs scattered ephemeral specs and cached issues."""
    norm_repo = normalize_target_path(repo_path)
    domain_contracts = [p.relative_to(norm_repo).as_posix() for _, p, _ in _discover_domain_contract_files(norm_repo)]
    candidate_paths = [
        p for sub in (norm_repo / ".edge" / "specs", norm_repo / "specs", norm_repo / "docs")
        if sub.exists() for p in sub.glob("**/*.md")
    ]
    ephemeral_candidates: List[str] = []
    seen: Set[str] = set()
    for p in sorted(candidate_paths):
        if not p.is_file():
            continue
        rel = p.relative_to(norm_repo).as_posix()
        if rel in seen or rel.startswith(("docs/domains/", ".edge/archive/")):
            continue
        seen.add(rel)
        if (rel.startswith("docs/") and p.name.lower() == "domain.md") or p.name.lower() in EXCLUDED_SPEC_NAMES:
            continue
        ephemeral_candidates.append(rel)

    if include_cached_issues:
        from tools.drift.tracker_specs import list_cached_issue_specs
        ephemeral_candidates.extend(c for c in list_cached_issue_specs(norm_repo) if c not in seen)

    return SpecDiscoveryReport(domain_contracts=domain_contracts, ephemeral_candidates=sorted(ephemeral_candidates))


def _load_context_domain_globs(norm_repo: Path) -> Tuple[Dict[str, List[str]], List[str], bool]:
    context_path = norm_repo / "CONTEXT.md"
    if not context_path.is_file():
        return {}, [], False
    domain_globs, concept_ids = parse_context_glossary(context_path.read_text(encoding="utf-8-sig", errors="replace"))
    return domain_globs, concept_ids, True


def _load_domain_contract(
    norm_repo: Path, domain_name: str, contract_file: Path, is_canonical: bool, context_globs: Optional[Dict[str, List[str]]] = None,
) -> Union[DomainContract, DriftCheckResult]:
    try:
        content = contract_file.read_text(encoding="utf-8-sig")
    except Exception as e:
        return DriftCheckResult(domain=domain_name, status="ERROR", summary=f"Failed to read contract: {e}")

    rel_doc_path = contract_file.relative_to(norm_repo).as_posix()
    if is_canonical:
        parsed = parse_canonical_domain_doc(content, doc_path=rel_doc_path, fallback_domain=domain_name)
        resolved = (context_globs or {}).get(parsed.domain) or parsed.tracked_paths
        return DomainContract(domain=parsed.domain, doc_path=rel_doc_path, tracked_paths=resolved, body=content)

    parsed_domain, tracked_paths, body_text = parse_domain_frontmatter(content, fallback_domain=contract_file.stem)
    resolved = (context_globs or {}).get(parsed_domain) or tracked_paths
    return DomainContract(domain=parsed_domain, doc_path=rel_doc_path, tracked_paths=resolved, body=body_text)
