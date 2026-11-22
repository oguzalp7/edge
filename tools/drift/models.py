#!/usr/bin/env python3
"""
Data models and frontmatter parsing for edge-drift:
Git-diff gated domain contract drift detector.

Contains:
- YAML frontmatter parser for docs/domains/<domain>.md (stdlib only)
- Path glob matching with ** recursive directory support
- Data contracts: DomainContract, DomainDriftRecord, DriftCheckResult, SpecDiscoveryReport
- DriftStateStore with atomic persistence
"""

import os
import re
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple, Union
from pathlib import Path
from datetime import datetime, timezone


def _glob_to_regex(pattern: str) -> re.Pattern:
    """
    Translates a glob pattern with support for ** recursive directory globs
    and * single-segment wildcards into a compiled regex.
    Normalizes separators to /.
    """
    p = pattern.replace("\\", "/").strip()
    if p.startswith("./"):
        p = p[2:]
    if p.endswith("/"):
        p = p + "**"

    tokens: List[str] = ["^"]
    i = 0
    n = len(p)
    while i < n:
        if p[i:i + 4] == "/**/":
            tokens.append("(?:/.*/|/)")
            i += 4
        elif p[i:i + 3] == "/**":
            tokens.append("(?:/.*)?")
            i += 3
        elif p[i:i + 2] == "**":
            tokens.append(".*")
            i += 2
        elif p[i] == "*":
            tokens.append("[^/]*")
            i += 1
        elif p[i] == "?":
            tokens.append("[^/]")
            i += 1
        else:
            tokens.append(re.escape(p[i]))
            i += 1

    tokens.append("$")
    return re.compile("".join(tokens))


def matches_tracked_paths(changed_files: List[str], tracked_paths: List[str]) -> List[str]:
    """
    Normalizes backslashes to /, strips leading ./, and accurately matches exact paths,
    * wildcards, and recursive ** directory globs (e.g. src/lib/bookings/** matches
    src/lib/bookings/repo.ts and src/lib/bookings/deep/util.ts).
    Returns the subset of changed_files that match any of tracked_paths.
    """
    if not changed_files or not tracked_paths:
        return []

    regexes = [_glob_to_regex(p) for p in tracked_paths if p.strip()]
    if not regexes:
        return []

    matched: List[str] = []
    for file_path in changed_files:
        norm_file = file_path.replace("\\", "/")
        if norm_file.startswith("./"):
            norm_file = norm_file[2:]
        norm_file = norm_file.strip()
        if not norm_file:
            continue

        for r in regexes:
            if r.match(norm_file):
                matched.append(file_path)
                break

    return matched


def parse_domain_frontmatter(
    markdown_text: str,
    fallback_domain: str = "",
) -> Tuple[str, List[str], str]:
    """
    Parses leading YAML frontmatter (--- ... ---) from docs/domains/<domain>.md,
    extracting domain (defaults to fallback_domain) and tracked_paths.
    Supports both inline list syntax:
      tracked_paths: ["src/lib/bookings/**", "src/actions/bookings.ts"]
    and block list syntax:
      tracked_paths:
        - src/lib/bookings/**
        - src/actions/bookings.ts
    Returns (domain, tracked_paths, body_text).
    """
    if not markdown_text.startswith("---"):
        return fallback_domain, [], markdown_text

    parts = markdown_text.split("---", 2)
    if len(parts) < 3:
        return fallback_domain, [], markdown_text

    frontmatter_str = parts[1]
    body_text = parts[2].lstrip("\r\n")

    domain = fallback_domain
    tracked_paths: List[str] = []

    lines = frontmatter_str.splitlines()
    in_tracked_paths_block = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if in_tracked_paths_block:
            if stripped.startswith("-"):
                item_val = stripped[1:].strip().strip("\"'")
                if item_val:
                    tracked_paths.append(item_val)
                continue
            elif ":" in line:
                in_tracked_paths_block = False
            else:
                continue

        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()

            if key == "domain":
                val_clean = val.strip("\"'")
                if val_clean:
                    domain = val_clean
            elif key == "tracked_paths":
                if val.startswith("[") and val.endswith("]"):
                    inner = val[1:-1].strip()
                    if inner:
                        items = [
                            item.strip().strip("\"'")
                            for item in inner.split(",")
                            if item.strip().strip("\"'")
                        ]
                        tracked_paths.extend(items)
                elif not val:
                    in_tracked_paths_block = True
                else:
                    item_val = val.strip("\"'")
                    if item_val:
                        tracked_paths.append(item_val)

    if not domain:
        domain = fallback_domain

    return domain, tracked_paths, body_text


@dataclass
class DomainContract:
    """
    Canonical domain contract ("Tapu") loaded from docs/domains/<domain>.md.
    """
    domain: str
    doc_path: str
    tracked_paths: List[str] = field(default_factory=list)
    body: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DomainContract":
        return cls(
            domain=data.get("domain", ""),
            doc_path=data.get("doc_path", ""),
            tracked_paths=data.get("tracked_paths", []) or [],
            body=data.get("body", ""),
        )


@dataclass
class DomainDriftRecord:
    """
    State record of a domain contract's last verified git commit SHA.
    """
    domain: str
    doc_path: str
    last_checked_sha: str
    last_checked_at: str
    tracked_paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DomainDriftRecord":
        return cls(
            domain=data.get("domain", ""),
            doc_path=data.get("doc_path", ""),
            last_checked_sha=data.get("last_checked_sha", ""),
            last_checked_at=data.get("last_checked_at", ""),
            tracked_paths=data.get("tracked_paths", []) or [],
        )


@dataclass
class DriftCheckResult:
    """
    Outcome of checking a domain contract against live code.
    """
    domain: str
    status: str  # "CLEAN" | "DRIFT_DETECTED" | "UNTRACKED" | "ERROR"
    changed_files: List[str] = field(default_factory=list)
    llm_invoked: bool = False
    summary: str = ""
    findings_markdown: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DriftCheckResult":
        return cls(
            domain=data.get("domain", ""),
            status=data.get("status", "CLEAN"),
            changed_files=data.get("changed_files", []) or [],
            llm_invoked=bool(data.get("llm_invoked", False)),
            summary=data.get("summary", ""),
            findings_markdown=data.get("findings_markdown", ""),
        )


@dataclass
class SpecDiscoveryReport:
    """
    Report distinguishing canonical domain deeds from ephemeral slice specs.
    """
    domain_contracts: List[str] = field(default_factory=list)
    ephemeral_candidates: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpecDiscoveryReport":
        return cls(
            domain_contracts=data.get("domain_contracts", []) or [],
            ephemeral_candidates=data.get("ephemeral_candidates", []) or [],
        )


@dataclass
class DriftStateStore:
    """
    Manages loading and atomic saving of <repo>/.edge/drift_state.json.
    """
    repo_path: Path
    records: Dict[str, DomainDriftRecord] = field(default_factory=dict)
    version: int = 1

    @classmethod
    def load_from_repo(cls, repo_path: Union[Path, str]) -> "DriftStateStore":
        norm_repo = Path(repo_path).resolve()
        state_file = norm_repo / ".edge" / "drift_state.json"
        if not state_file.exists():
            return cls(repo_path=norm_repo, records={})

        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data, norm_repo)
        except Exception:
            return cls(repo_path=norm_repo, records={})

    def get_record(self, domain: str) -> Optional[DomainDriftRecord]:
        return self.records.get(domain)

    def update_record(
        self,
        domain: str,
        sha: str,
        doc_path: str,
        tracked_paths: List[str],
    ) -> DomainDriftRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        rec = DomainDriftRecord(
            domain=domain,
            doc_path=doc_path,
            last_checked_sha=sha,
            last_checked_at=now_iso,
            tracked_paths=tracked_paths,
        )
        self.records[domain] = rec
        self.save()
        return rec

    def save(self) -> None:
        edge_dir = self.repo_path / ".edge"
        edge_dir.mkdir(parents=True, exist_ok=True)
        state_file = edge_dir / "drift_state.json"
        tmp_file = edge_dir / f"drift_state.json.tmp.{os.getpid()}"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, state_file)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "domains": {k: v.to_dict() for k, v in self.records.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], repo_path: Path) -> "DriftStateStore":
        version = data.get("version", 1)
        raw_domains = data.get("domains", {})
        records: Dict[str, DomainDriftRecord] = {}
        for k, v in raw_domains.items():
            if isinstance(v, dict):
                records[k] = DomainDriftRecord.from_dict(v)
        return cls(repo_path=repo_path, records=records, version=version)


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
    severity: str       # "ERROR" | "WARNING"
    code: str           # "UNKNOWN_CONCEPT" | "UNKNOWN_INVARIANT" | "LEGACY_TAG" | "MISSING_ENFORCER" | "GLOB_MISMATCH"
    file_path: str
    detail: str


@dataclass
class OntologyReport:
    """Aggregated deterministic ontology validation output."""
    skipped: bool = False
    context_concepts: List[str] = field(default_factory=list)
    domain_docs: List[CanonicalDomainDoc] = field(default_factory=list)
    issues: List[OntologyIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "ERROR" for issue in self.issues)


def _split_csv_tokens(raw_value: str) -> List[str]:
    """Splits comma-separated backtick/plain tokens and strips whitespace."""
    return [
        item.strip().strip("`").strip()
        for item in raw_value.split(",")
        if item.strip().strip("`").strip()
    ]


def _append_unique(target: List[str], item: str) -> None:
    if item and item not in target:
        target.append(item)


def _parse_canonical_meta_line(line: str, doc: CanonicalDomainDoc) -> bool:
    """Parses heading/metadata lines on CanonicalDomainDoc; returns True if matched."""
    m_dom = _DOMAIN_HEADING_RE.match(line)
    if m_dom:
        doc.domain = m_dom.group(1).strip().strip("`")
        return True
    m_paths = _PATHS_META_RE.match(line)
    if m_paths:
        doc.tracked_paths.extend(_split_csv_tokens(m_paths.group(1)))
        return True
    m_owner = _OWNER_META_RE.match(line)
    if m_owner:
        doc.owner = m_owner.group(1).strip()
        return True
    m_concepts = _CONCEPTS_META_RE.match(line)
    if m_concepts:
        doc.concepts.extend(_split_csv_tokens(m_concepts.group(1)))
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
    """Parses one Markdown table row inside ## Domain Map."""
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
    """Parses one bullet or table row inside ## Closed Concept Glossary."""
    stripped = line.strip()
    m_bullet = _CONCEPT_BULLET_RE.match(stripped)
    if m_bullet:
        _append_unique(concept_ids, m_bullet.group(1))
        return
    if stripped.startswith("|") and not _MD_TABLE_SEP_RE.match(stripped):
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells:
            cid = cells[0].strip("`").strip()
            if cid and cid.lower() != "concept":
                _append_unique(concept_ids, cid)


def parse_context_glossary(markdown_text: str) -> Tuple[Dict[str, List[str]], List[str]]:
    """
    Parses root CONTEXT.md into (domain_globs, concept_ids).
    Concept IDs are strictly scoped to ## Closed Concept Glossary.
    """
    cleaned = markdown_text.lstrip("\ufeff")
    domain_globs: Dict[str, List[str]] = {}
    concept_ids: List[str] = []
    section = ""

    for line in cleaned.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            if heading == "domain map":
                section = "domain_map"
            elif heading == "closed concept glossary":
                section = "glossary"
            else:
                section = "other"
            continue

        if section == "domain_map":
            _parse_domain_map_row(line, domain_globs)
        elif section == "glossary":
            _parse_glossary_row(line, concept_ids)

    return domain_globs, concept_ids
