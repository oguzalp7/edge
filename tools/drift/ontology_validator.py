"""
Deterministic zero-LLM ontology validator orchestrating CONTEXT.md, DOMAIN.md, and code headers.
"""

from pathlib import Path
from typing import Dict, List, Set, Union

from tools.common.paths import normalize_target_path
from tools.drift.header_scanner import (
    _ONTOLOGY_PRUNE_DIRS,
    _TEST_INDEX_PRUNE_DIRS,
    _scan_files_for_headers,
    _walk_code_tree,
)
from tools.drift.leak_scanner import _validate_domain_doc_entry
from tools.drift.models import CanonicalDomainDoc, OntologyIssue, OntologyReport, parse_canonical_domain_doc
from tools.drift.spec_discovery import _load_context_domain_globs


def _collect_canonical_domain_files(norm_repo: Path) -> List[Path]:
    """Returns sorted docs/<domain>/DOMAIN.md files, excluding docs/domains/DOMAIN.md."""
    docs_dir = norm_repo / "docs"
    if not docs_dir.is_dir():
        return []
    found: List[Path] = []
    for sub in sorted(docs_dir.iterdir()):
        if not sub.is_dir() or sub.name.lower() == "domains":
            continue
        dom_file = sub / "DOMAIN.md"
        if dom_file.is_file():
            found.append(dom_file)
    return found


def validate_ontology(repo_path: Union[Path, str]) -> OntologyReport:
    """Deterministic zero-LLM validator for CONTEXT.md, docs/*/DOMAIN.md, and 1-3L headers."""
    norm_repo = normalize_target_path(repo_path)
    canonical_files = _collect_canonical_domain_files(norm_repo)
    context_globs, context_concepts, has_context = _load_context_domain_globs(norm_repo)
    if not has_context and not canonical_files:
        return OntologyReport(skipped=True)

    valid_concepts = set(context_concepts)
    domain_docs: List[CanonicalDomainDoc] = []
    issues: List[OntologyIssue] = []
    valid_invariants: Set[str] = set()
    tracked_globs: List[str] = []

    for dom_file in canonical_files:
        rel_doc = dom_file.relative_to(norm_repo).as_posix()
        dom_text = dom_file.read_text(encoding="utf-8-sig", errors="replace")
        doc = parse_canonical_domain_doc(dom_text, doc_path=rel_doc, fallback_domain=dom_file.parent.name)
        domain_docs.append(doc)
        valid_invariants.update(doc.invariant_ids)
        tracked_globs.extend(context_globs.get(doc.domain) or doc.tracked_paths)
        issues.extend(_validate_domain_doc_entry(doc, dom_text, valid_concepts, context_globs, has_context))

    invariant_index: Dict[str, List[str]] = {}
    code_glob_filter = tracked_globs if (tracked_globs or canonical_files) else None
    code_files = _walk_code_tree(norm_repo, norm_repo, _ONTOLOGY_PRUNE_DIRS, code_glob_filter)
    issues.extend(_scan_files_for_headers(code_files, valid_concepts, valid_invariants, invariant_index))
    test_files = _walk_code_tree(norm_repo / "tests", norm_repo, _TEST_INDEX_PRUNE_DIRS)
    issues.extend(_scan_files_for_headers(test_files, valid_concepts, valid_invariants, invariant_index, invariants_only=True))

    sorted_index = {k: sorted(set(v)) for k, v in sorted(invariant_index.items())}
    return OntologyReport(
        skipped=False,
        context_concepts=context_concepts,
        domain_docs=domain_docs,
        issues=issues,
        invariant_index=sorted_index,
    )
