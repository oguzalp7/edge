"""
Canonical DOMAIN.md and CONTEXT.md ontology models and parsers for edge-drift.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

LEGACY_ERROR_TAGS: Tuple[str, ...] = (
    "@inputs",
    "@outputs",
    "@glossary",
    "@route",
    "@spec",
    "@base_commit",
    "@domain_jargon",
)
LEGACY_WARNING_TAGS: Tuple[str, ...] = ("@module",)
LEGACY_FRONTMATTER_TAGS: Tuple[str, ...] = LEGACY_ERROR_TAGS + LEGACY_WARNING_TAGS
INV_PAT_DEF_RE = re.compile(r"^\s*-\s+\*\*\[((?:INV|PAT)-[A-Z0-9]+(?:-[A-Z0-9]+)+)\]\*\*")
_DOMAIN_HEADING_RE = re.compile(r"^\s*#\s+Domain:\s*(.+?)\s*$")
_PATHS_META_RE = re.compile(r"^\s*-\s+\*\*Paths:\*\*\s*(.+)$")
_OWNER_META_RE = re.compile(r"^\s*-\s+\*\*Owner\s*/\s*DRI:\*\*\s*(.+)$")
_CONCEPTS_META_RE = re.compile(r"^\s*-\s+\*\*Concepts:\*\*\s*(.+)$")
_ENFORCED_BY_RE = re.compile(r"^\s*\*Enforced by:\*\s*(.+)$")
_MD_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")
_CONCEPT_BULLET_RE = re.compile(r"^\s*[-*]\s+`?([a-z0-9][a-z0-9_-]*)`?\s*:")


@dataclass
class CanonicalDomainDoc:
    """Canonical domain deed parsed from docs/<domain>/DOMAIN.md."""
    domain: str
    doc_path: str
    tracked_paths: List[str] = field(default_factory=list)
    owner: str = ""
    concepts: List[str] = field(default_factory=list)
    invariant_ids: List[str] = field(default_factory=list)
    pattern_ids: List[str] = field(default_factory=list)
    enforced_by: List[str] = field(default_factory=list)


@dataclass
class OntologyIssue:
    """Single ontology validation finding (ERROR or WARNING)."""
    severity: str
    code: str
    file_path: str
    detail: str


@dataclass
class OntologyReport:
    """Aggregated deterministic ontology validation output."""
    skipped: bool = False
    context_concepts: List[str] = field(default_factory=list)
    domain_docs: List[CanonicalDomainDoc] = field(default_factory=list)
    issues: List[OntologyIssue] = field(default_factory=list)
    invariant_index: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "ERROR" for issue in self.issues)


def _split_csv_tokens(raw_value: str) -> List[str]:
    return [item.strip().strip("`").strip() for item in raw_value.split(",") if item.strip().strip("`").strip()]


def _append_unique(target: List[str], item: str) -> None:
    if item and item not in target:
        target.append(item)


def _parse_canonical_meta_line(line: str, doc: CanonicalDomainDoc) -> bool:
    for regex, attr, is_csv in (
        (_DOMAIN_HEADING_RE, "domain", False),
        (_PATHS_META_RE, "tracked_paths", True),
        (_OWNER_META_RE, "owner", False),
        (_CONCEPTS_META_RE, "concepts", True),
    ):
        match = regex.match(line)
        if not match:
            continue
        val = match.group(1).strip()
        if is_csv:
            getattr(doc, attr).extend(_split_csv_tokens(val))
        else:
            setattr(doc, attr, val.strip("`") if attr == "domain" else val)
        return True
    return False


def parse_canonical_domain_doc(
    markdown_text: str,
    doc_path: str,
    fallback_domain: str = "",
) -> CanonicalDomainDoc:
    """Parses a canonical docs/<domain>/DOMAIN.md contract without YAML frontmatter."""
    cleaned = markdown_text.lstrip("\ufeff")
    doc = CanonicalDomainDoc(domain=fallback_domain, doc_path=doc_path)
    for line in cleaned.splitlines():
        if _parse_canonical_meta_line(line, doc):
            continue
        m_def = INV_PAT_DEF_RE.match(line)
        if m_def:
            tag_id = m_def.group(1)
            target = doc.invariant_ids if tag_id.startswith("INV-") else doc.pattern_ids
            _append_unique(target, tag_id)
            continue
        m_enf = _ENFORCED_BY_RE.match(line)
        if m_enf:
            for item in _split_csv_tokens(m_enf.group(1)):
                _append_unique(doc.enforced_by, item.split("::", 1)[0].strip())
    if not doc.domain:
        doc.domain = fallback_domain
    return doc


def _parse_domain_map_row(line: str, domain_globs: Dict[str, List[str]]) -> None:
    stripped = line.strip()
    if not stripped.startswith("|") or _MD_TABLE_SEP_RE.match(stripped):
        return
    cells = [c.strip() for c in stripped.strip("|").split("|")]
    if len(cells) < 2:
        return
    domain_name = cells[0].strip("`").strip()
    if not domain_name or domain_name.lower() == "domain":
        return
    globs = _split_csv_tokens(cells[1])
    if globs:
        domain_globs[domain_name] = globs


def _parse_glossary_row(line: str, concept_ids: List[str]) -> None:
    stripped = line.strip()
    m_bullet = _CONCEPT_BULLET_RE.match(stripped)
    if m_bullet:
        _append_unique(concept_ids, m_bullet.group(1))
        return
    if not stripped.startswith("|") or _MD_TABLE_SEP_RE.match(stripped):
        return
    cells = [c.strip() for c in stripped.strip("|").split("|")]
    if cells:
        cid = cells[0].strip("`").strip()
        if cid and cid.lower() != "concept":
            _append_unique(concept_ids, cid)


def parse_context_glossary(markdown_text: str) -> Tuple[Dict[str, List[str]], List[str]]:
    """Parses root CONTEXT.md into (domain_globs, concept_ids)."""
    cleaned = markdown_text.lstrip("\ufeff")
    domain_globs: Dict[str, List[str]] = {}
    concept_ids: List[str] = []
    section = ""
    for line in cleaned.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            section = "domain_map" if heading == "domain map" else ("glossary" if heading == "closed concept glossary" else "other")
            continue
        if section == "domain_map":
            _parse_domain_map_row(line, domain_globs)
        elif section == "glossary":
            _parse_glossary_row(line, concept_ids)
    return domain_globs, concept_ids
