#!/usr/bin/env python3
"""
Scanner and Gated Auditor for edge-drift:
Detects architectural and invariant drift between canonical domain contracts
and live code implementation via git diff gating and read-only LLM audit.
"""

import os
import re
import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union
from datetime import datetime, timezone

from tools.common.paths import normalize_target_path
from tools.common.runner import run_command
from tools.drift.models import (
    CanonicalDomainDoc,
    DomainContract,
    DomainDriftRecord,
    DriftCheckResult,
    DriftStateStore,
    LEGACY_ERROR_TAGS,
    LEGACY_WARNING_TAGS,
    OntologyIssue,
    OntologyReport,
    SpecDiscoveryReport,
    matches_tracked_paths,
    parse_canonical_domain_doc,
    parse_context_glossary,
    parse_domain_frontmatter,
)

DRIFT_MODEL: str = "gemini-3.8-flash-high"

EXCLUDED_SPEC_NAMES = {
    "readme.md",
    "architecture.md",
    "instructions.md",
    "coding_standards.md",
}

_ONTOLOGY_PRUNE_DIRS = {
    ".git",
    "node_modules",
    ".edge",
    ".next",
    "dist",
    "build",
    "__pycache__",
    "tests",
}
_ONTOLOGY_CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
_CODING_COOKIE_RE = re.compile(r"^#.*coding[:=]")
_HEADER_TAG_RE = re.compile(r"^\s*(?:#|//|\*)?\s*(@[a-z_]+)\b(.*)$")
_INV_TOKEN_RE = re.compile(r"\[?((?:INV|PAT)-[A-Z0-9]+(?:-[A-Z0-9]+)+)\]?")
_DIRECTIVE_LINES = {'"use client";', "'use client';", '"use strict";', "'use strict';", '"use client"', "'use client'", '"use strict"', "'use strict'"}


def archive_ephemeral_spec(
    repo_path: Union[Path, str],
    spec_path: Union[Path, str],
) -> Optional[Path]:
    """
    Safely moves a temporary/completed slice spec file into <repo>/.edge/archive/specs/<filename>.
    If a file with the same name already exists in archive, appends timestamp.
    Returns destination Path or None if source file does not exist.
    """
    norm_repo = normalize_target_path(repo_path)
    spec_file = Path(spec_path)
    if not spec_file.is_absolute():
        spec_file = norm_repo / spec_file

    if not spec_file.exists() or not spec_file.is_file():
        return None

    archive_dir = norm_repo / ".edge" / "archive" / "specs"
    archive_dir.mkdir(parents=True, exist_ok=True)

    dest = archive_dir / spec_file.name
    if dest.exists():
        stem = spec_file.stem
        suffix = spec_file.suffix
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = archive_dir / f"{stem}_{ts}{suffix}"

    try:
        shutil.move(str(spec_file), str(dest))
        return dest
    except Exception:
        try:
            shutil.copy2(str(spec_file), str(dest))
            spec_file.unlink()
            return dest
        except Exception:
            return None


def _discover_domain_contract_files(
    norm_repo: Path,
) -> List[Tuple[str, Path, bool]]:
    """
    Discovers canonical docs/<domain>/DOMAIN.md (excluding docs/domains/DOMAIN.md)
    and legacy docs/domains/*.md contracts, preferring canonical DOMAIN.md on overlap.
    Returns sorted list of (domain_name, path, is_canonical).
    """
    docs_dir = norm_repo / "docs"
    if not docs_dir.is_dir():
        return []

    canonical_by_domain: Dict[str, Tuple[str, Path, bool]] = {}
    for sub in sorted(docs_dir.iterdir()):
        if not sub.is_dir() or sub.name.lower() == "domains":
            continue
        dom_file = sub / "DOMAIN.md"
        if not dom_file.is_file():
            continue
        rel = dom_file.relative_to(norm_repo).as_posix()
        try:
            text = dom_file.read_text(encoding="utf-8-sig", errors="replace")
            parsed = parse_canonical_domain_doc(text, doc_path=rel, fallback_domain=sub.name)
            dom_name = parsed.domain or sub.name
        except Exception:
            dom_name = sub.name
        if dom_name.lower() == "domains":
            continue
        canonical_by_domain[dom_name.lower()] = (dom_name, dom_file, True)

    entries: List[Tuple[str, Path, bool]] = list(canonical_by_domain.values())
    legacy_dir = docs_dir / "domains"
    if legacy_dir.is_dir():
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

    entries.sort(key=lambda item: item[1].relative_to(norm_repo).as_posix())
    return entries


def discover_specs(repo_path: Union[Path, str]) -> SpecDiscoveryReport:
    """
    Finds canonical docs/<domain>/DOMAIN.md & docs/domains/*.md contracts vs scattered
    ephemeral/task specs under .edge/specs/*.md, specs/*.md, and docs/**/*.md.
    """
    norm_repo = normalize_target_path(repo_path)
    contracts = _discover_domain_contract_files(norm_repo)
    domain_contracts = [p.relative_to(norm_repo).as_posix() for _, p, _ in contracts]

    candidate_paths: List[Path] = []
    for sub in (norm_repo / ".edge" / "specs", norm_repo / "specs", norm_repo / "docs"):
        if sub.exists():
            candidate_paths.extend(sub.glob("**/*.md"))

    ephemeral_candidates: List[str] = []
    seen: Set[str] = set()
    for p in sorted(candidate_paths):
        if not p.is_file():
            continue
        rel = p.relative_to(norm_repo).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        if rel.startswith(("docs/domains/", ".edge/archive/")):
            continue
        if rel.startswith("docs/") and p.name.lower() == "domain.md":
            continue
        if p.name.lower() in EXCLUDED_SPEC_NAMES:
            continue
        ephemeral_candidates.append(rel)

    return SpecDiscoveryReport(
        domain_contracts=domain_contracts,
        ephemeral_candidates=sorted(ephemeral_candidates),
    )


def get_head_sha(repo_path: Path) -> str:
    """Gets current git HEAD SHA."""
    code, out, _ = run_command(["git", "rev-parse", "HEAD"], cwd=repo_path)
    return out.strip() if code == 0 else ""


def get_changed_files_since(repo_path: Path, base_sha: str) -> Optional[List[str]]:
    """
    Returns list of files changed between base_sha and HEAD via git diff --name-only.
    Returns None if git command fails.
    """
    if not base_sha:
        return None
    code, out, _ = run_command(["git", "diff", "--name-only", f"{base_sha}..HEAD"], cwd=repo_path)
    if code != 0:
        return None
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def _render_drift_report(
    head_sha: str,
    results: List[DriftCheckResult],
) -> str:
    """Renders consolidated markdown report for .edge/drift/latest-drift-report.md."""
    now_iso = datetime.now(timezone.utc).isoformat()
    lines = [
        "# 🛡️ Edge Drift Report",
        "",
        f"- **Generated At:** `{now_iso}`",
        f"- **Repository HEAD:** `{head_sha}`",
        f"- **Domains Audited:** {len(results)}",
        "",
        "## Domain Status Matrix",
        "",
        "| Domain | Status | LLM Audited | Changed Files | Summary |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in results:
        llm_str = "Yes" if r.llm_invoked else "No"
        changed_count = len(r.changed_files)
        lines.append(
            f"| `{r.domain}` | `{r.status}` | {llm_str} | {changed_count} | {r.summary} |"
        )

    lines.append("")
    lines.append("## Detailed Audit Findings")
    lines.append("")

    for r in results:
        lines.append(f"### Domain: `{r.domain}`")
        lines.append(f"- **Status:** `{r.status}`")
        lines.append(f"- **Summary:** {r.summary}")
        if r.changed_files:
            lines.append("- **Tracked Changed Files:**")
            for f in r.changed_files:
                lines.append(f"  - `{f}`")
        if r.findings_markdown:
            lines.append("")
            lines.append("#### Findings:")
            lines.append(r.findings_markdown.strip())
        lines.append("")

    return "\n".join(lines)


def _write_drift_report(
    norm_repo: Path,
    head_sha: str,
    results: List[DriftCheckResult],
) -> None:
    """Writes .edge/drift/latest-drift-report.md atomically."""
    report_content = _render_drift_report(head_sha, results)
    drift_dir = norm_repo / ".edge" / "drift"
    drift_dir.mkdir(parents=True, exist_ok=True)
    report_file = drift_dir / "latest-drift-report.md"
    tmp_report = drift_dir / f"latest-drift-report.md.tmp.{os.getpid()}"
    with open(tmp_report, "w", encoding="utf-8") as f:
        f.write(report_content)
    os.replace(tmp_report, report_file)


def _load_domain_contract(
    norm_repo: Path,
    domain_name: str,
    contract_file: Path,
    is_canonical: bool,
) -> Union[DomainContract, DriftCheckResult]:
    """Reads and parses a canonical DOMAIN.md or legacy docs/domains/*.md contract."""
    try:
        content = contract_file.read_text(encoding="utf-8-sig")
    except Exception as e:
        return DriftCheckResult(
            domain=domain_name,
            status="ERROR",
            summary=f"Failed to read contract: {e}",
        )

    rel_doc_path = contract_file.relative_to(norm_repo).as_posix()
    if is_canonical:
        parsed = parse_canonical_domain_doc(
            content, doc_path=rel_doc_path, fallback_domain=domain_name
        )
        return DomainContract(
            domain=parsed.domain,
            doc_path=rel_doc_path,
            tracked_paths=parsed.tracked_paths,
            body=content,
        )

    parsed_domain, tracked_paths, body_text = parse_domain_frontmatter(
        content, fallback_domain=contract_file.stem
    )
    return DomainContract(
        domain=parsed_domain,
        doc_path=rel_doc_path,
        tracked_paths=tracked_paths,
        body=body_text,
    )


def _build_drift_audit_prompt(
    contract: DomainContract,
    files_to_audit: List[str],
) -> str:
    return f"""You are the Edge Drift Auditor. Your role is strictly read-only verification.
Compare the domain contract '{contract.doc_path}' against the live implementation in the repository.

Tracked paths for domain '{contract.domain}':
{json.dumps(contract.tracked_paths, indent=2)}

Recently changed or tracked files under review:
{json.dumps(files_to_audit, indent=2)}

Audit the code against the contract across these 4 categories:
1. BROKEN_INVARIANT: Live code violates an invariant stated in the domain contract.
2. LOGIC_SHORTCUT: A temporary shortcut, hack, or leak was introduced bypassing domain boundaries.
3. ANCHOR_DRIFT: An intentional anchor or deferred scope was altered or prematurely implemented.
4. DOC_OUTDATED: Live code legitimately evolved or was refactored, but the domain document was not updated.

OUTPUT FORMAT REQUIREMENTS:
- If the live code is 100% aligned with the contract and no drift or violation is found, output exactly:
NO_DRIFT
- If drift or violations exist, list findings with the category prefix, e.g.:
- [BROKEN_INVARIANT] Description of violation in <file>
- [LOGIC_SHORTCUT] Description of shortcut in <file>
- [ANCHOR_DRIFT] Description in <file>
- [DOC_OUTDATED] Description in <file>
"""


def _audit_single_contract(
    norm_repo: Path,
    contract: DomainContract,
    head_sha: str,
    state_store: DriftStateStore,
    model: str,
    timeout: int,
) -> DriftCheckResult:
    """Runs zero-token git-diff gate and optional read-only agy audit for one domain."""
    if not contract.tracked_paths:
        return DriftCheckResult(
            domain=contract.domain,
            status="UNTRACKED",
            summary=f"UNTRACKED (no tracked_paths configured in {contract.doc_path})",
        )

    record = state_store.get_record(contract.domain)
    files_to_audit = contract.tracked_paths
    if record and record.last_checked_sha:
        if record.last_checked_sha == head_sha:
            return DriftCheckResult(
                domain=contract.domain,
                status="CLEAN",
                summary="CLEAN (no code changes)",
            )
        changed = get_changed_files_since(norm_repo, record.last_checked_sha)
        if changed is not None:
            matched = matches_tracked_paths(changed, contract.tracked_paths)
            if not matched:
                state_store.update_record(
                    domain=contract.domain,
                    sha=head_sha,
                    doc_path=contract.doc_path,
                    tracked_paths=contract.tracked_paths,
                )
                return DriftCheckResult(
                    domain=contract.domain,
                    status="CLEAN",
                    summary="CLEAN (no tracked code changes)",
                )
            files_to_audit = matched

    cmd = ["agy", "--mode", "plan", "--model", model, "-p", _build_drift_audit_prompt(contract, files_to_audit)]
    code, stdout, stderr = run_command(cmd, cwd=norm_repo, timeout=timeout)
    if code != 0:
        return DriftCheckResult(
            domain=contract.domain,
            status="ERROR",
            changed_files=files_to_audit,
            llm_invoked=True,
            summary=f"Error executing agy: {stderr or stdout}",
        )

    output = stdout.strip()
    has_violations = any(
        cat in output
        for cat in ("BROKEN_INVARIANT", "LOGIC_SHORTCUT", "ANCHOR_DRIFT", "DOC_OUTDATED")
    )
    if "NO_DRIFT" in output and not has_violations:
        state_store.update_record(
            domain=contract.domain,
            sha=head_sha,
            doc_path=contract.doc_path,
            tracked_paths=contract.tracked_paths,
        )
        return DriftCheckResult(
            domain=contract.domain,
            status="CLEAN",
            changed_files=files_to_audit,
            llm_invoked=True,
            summary="CLEAN (audit verified no drift)",
        )

    return DriftCheckResult(
        domain=contract.domain,
        status="DRIFT_DETECTED",
        changed_files=files_to_audit,
        llm_invoked=True,
        summary=f"DRIFT_DETECTED across {len(files_to_audit)} tracked files",
        findings_markdown=output,
    )


def check_drift(
    repo_path: Union[Path, str],
    model: str = DRIFT_MODEL,
    timeout: int = 180,
) -> List[DriftCheckResult]:
    """
    Audits canonical docs/<domain>/DOMAIN.md and legacy docs/domains/*.md contracts
    against live code with zero-token git-diff gating.
    """
    norm_repo = normalize_target_path(repo_path)
    contract_entries = _discover_domain_contract_files(norm_repo)
    head_sha = get_head_sha(norm_repo) if contract_entries else ""
    results: List[DriftCheckResult] = []

    if not contract_entries:
        _write_drift_report(norm_repo, head_sha, results)
        return results

    if not head_sha:
        for domain_name, _, _ in contract_entries:
            results.append(
                DriftCheckResult(
                    domain=domain_name,
                    status="ERROR",
                    summary="Unable to resolve git HEAD SHA (empty HEAD)",
                )
            )
        _write_drift_report(norm_repo, head_sha, results)
        return results

    state_store = DriftStateStore.load_from_repo(norm_repo)
    for domain_name, contract_file, is_canonical in contract_entries:
        loaded = _load_domain_contract(norm_repo, domain_name, contract_file, is_canonical)
        if isinstance(loaded, DriftCheckResult):
            results.append(loaded)
        else:
            results.append(
                _audit_single_contract(norm_repo, loaded, head_sha, state_store, model, timeout)
            )

    _write_drift_report(norm_repo, head_sha, results)
    return results


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


def _validate_domain_doc_entry(
    norm_repo: Path,
    doc: CanonicalDomainDoc,
    valid_concepts: Set[str],
    context_globs: Dict[str, List[str]],
    has_context_file: bool,
) -> List[OntologyIssue]:
    """Validates one CanonicalDomainDoc against CONTEXT.md and enforcer files."""
    issues: List[OntologyIssue] = []
    if has_context_file or doc.concepts:
        for concept in doc.concepts:
            if concept not in valid_concepts:
                issues.append(
                    OntologyIssue(
                        severity="ERROR",
                        code="UNKNOWN_CONCEPT",
                        file_path=doc.doc_path,
                        detail=f"Unknown concept '{concept}' not in CONTEXT.md",
                    )
                )

    if doc.domain in context_globs:
        ctx_paths = [g.strip() for g in context_globs[doc.domain]]
        dom_paths = [g.strip() for g in doc.tracked_paths]
        if ctx_paths != dom_paths:
            issues.append(
                OntologyIssue(
                    severity="WARNING",
                    code="GLOB_MISMATCH",
                    file_path=doc.doc_path,
                    detail=f"CONTEXT.md globs differ from {doc.doc_path} Paths:",
                )
            )

    for enforcer in doc.enforced_by:
        if any(ch in enforcer for ch in ("*", "?", "{", "[")):
            continue
        if not (norm_repo / enforcer).exists():
            issues.append(
                OntologyIssue(
                    severity="WARNING",
                    code="MISSING_ENFORCER",
                    file_path=doc.doc_path,
                    detail=f"Missing enforcer path '{enforcer}'",
                )
            )
    return issues


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
    """
    Extracts leading header comment/docstring lines within top `max_lines`,
    skipping shebang/coding/directives and stopping at the first executable code line.
    """
    lines = text.splitlines()[:max_lines]
    header_lines: List[str] = []
    idx = 0
    while idx < len(lines):
        stripped = lines[idx].strip()
        if (
            not stripped
            or stripped.startswith("#!")
            or _CODING_COOKIE_RE.match(stripped)
            or stripped in _DIRECTIVE_LINES
        ):
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
                issues.append(
                    OntologyIssue("ERROR", "UNKNOWN_CONCEPT", rel_path, f"Unknown concept '{cid}'")
                )
    elif tag == "@invariants":
        for inv_id in _INV_TOKEN_RE.findall(rest):
            if inv_id not in valid_invariants:
                issues.append(
                    OntologyIssue(
                        "ERROR",
                        "UNKNOWN_INVARIANT",
                        rel_path,
                        f"Unknown invariant '{inv_id}'",
                    )
                )
    return issues


def _walk_tracked_code_files(
    norm_repo: Path,
    tracked_globs: List[str],
) -> List[Tuple[str, Path]]:
    """Walks repo via os.walk with prune set, returning tracked code files."""
    files: List[Tuple[str, Path]] = []
    for root, dirs, filenames in os.walk(norm_repo):
        dirs[:] = sorted(d for d in dirs if d not in _ONTOLOGY_PRUNE_DIRS)
        for fname in sorted(filenames):
            fpath = Path(root) / fname
            if fpath.suffix.lower() not in _ONTOLOGY_CODE_SUFFIXES:
                continue
            rel = fpath.relative_to(norm_repo).as_posix()
            if tracked_globs and not matches_tracked_paths([rel], tracked_globs):
                continue
            files.append((rel, fpath))
    return files


def validate_ontology(repo_path: Union[Path, str]) -> OntologyReport:
    """
    Deterministic zero-LLM validator for CONTEXT.md, docs/*/DOMAIN.md,
    and 1-3L code header tags (@intent, @concepts, @invariants, legacy tags).
    Skips cleanly when neither CONTEXT.md nor docs/*/DOMAIN.md exists.
    """
    norm_repo = normalize_target_path(repo_path)
    context_path = norm_repo / "CONTEXT.md"
    canonical_files = _collect_canonical_domain_files(norm_repo)

    if not context_path.is_file() and not canonical_files:
        return OntologyReport(skipped=True)

    context_globs: Dict[str, List[str]] = {}
    context_concepts: List[str] = []
    if context_path.is_file():
        ctx_text = context_path.read_text(encoding="utf-8-sig", errors="replace")
        context_globs, context_concepts = parse_context_glossary(ctx_text)
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
        tracked_globs.extend(doc.tracked_paths)
        issues.extend(
            _validate_domain_doc_entry(norm_repo, doc, valid_concepts, context_globs, context_path.is_file())
        )

    for rel_path, fpath in _walk_tracked_code_files(norm_repo, tracked_globs):
        text = fpath.read_text(encoding="utf-8-sig", errors="replace")
        for hdr_line in _extract_header_lines(text, max_lines=30):
            m = _HEADER_TAG_RE.match(hdr_line)
            if m:
                issues.extend(
                    _validate_header_tag(m.group(1), m.group(2), rel_path, valid_concepts, valid_invariants)
                )

    return OntologyReport(
        skipped=False,
        context_concepts=context_concepts,
        domain_docs=domain_docs,
        issues=issues,
    )


def consolidate_domain(
    repo_path: Union[Path, str],
    domain: str,
    tracked_paths: List[str],
    source_specs: Optional[List[Path]] = None,
    archive_sources: bool = False,
    model: str = DRIFT_MODEL,
    timeout: int = 180,
) -> Tuple[bool, Path, str]:
    """
    Distills source specifications and live code into a canonical Domain Deed ("Tapu")
    under <repo>/docs/domains/<domain>.md with deterministic frontmatter and sections.
    Updates DriftStateStore with current HEAD SHA and optionally archives source specs.
    """
    norm_repo = normalize_target_path(repo_path)
    domains_dir = norm_repo / "docs" / "domains"
    domains_dir.mkdir(parents=True, exist_ok=True)
    target_path = domains_dir / f"{domain}.md"

    # Read sources if provided
    sources_text = ""
    valid_source_paths: List[Path] = []
    if source_specs:
        for s in source_specs:
            s_path = Path(s)
            if not s_path.is_absolute():
                s_path = norm_repo / s_path
            if s_path.exists() and s_path.is_file():
                valid_source_paths.append(s_path)
                try:
                    with open(s_path, "r", encoding="utf-8") as f:
                        sources_text += f"\n--- SOURCE SPEC: {s_path.name} ---\n" + f.read() + "\n"
                except Exception:
                    pass

    paths_yaml = "\n".join(f"  - {p}" for p in tracked_paths)
    prompt = f"""You are the Edge Domain Architect. Consolidate and distill the domain specification for '{domain}'.
Synthesize the provided source specifications and live code matching tracked paths into a canonical Domain Deed ('Tapu').

Tracked Paths for '{domain}':
{json.dumps(tracked_paths, indent=2)}

Source Specifications Content:
{sources_text if sources_text else "No prior source specs provided. Synthesize from live domain code."}

Generate the canonical domain contract document with:
1. Leading YAML Frontmatter:
---
domain: {domain}
tracked_paths:
{paths_yaml}
---

2. Required Markdown Sections:
# {domain.capitalize()} Domain Contract

## Core Invariants
(State absolute rules, immutable business constraints, and non-negotiables)

## Domain Boundaries
(Explicit definitions of what belongs in this domain, data ownership, and what must be rejected or routed elsewhere)

## Intentional Anchors & Deferred Scope
(Record intentional technical debt, future phase boundaries, and deliberate seams)
"""
    cmd = ["agy", "--mode", "plan", "--model", model, "-p", prompt]
    code, stdout, stderr = run_command(cmd, cwd=norm_repo, timeout=timeout)

    if code != 0:
        return False, target_path, f"Failed to run agy: {stderr or stdout}"

    content = stdout.strip()
    # If wrapped in ```markdown ... ```, unwrap
    if content.startswith("```markdown") and content.endswith("```"):
        content = content[len("```markdown"): -3].strip()
    elif content.startswith("```") and content.endswith("```"):
        content = content[3:-3].strip()

    # Verify frontmatter is present; if not, prepend deterministic frontmatter
    if not content.startswith("---"):
        frontmatter = f"---\ndomain: {domain}\ntracked_paths:\n{paths_yaml}\n---\n\n"
        content = frontmatter + content

    # Atomically write target document
    tmp_target = target_path.with_name(f"{target_path.name}.tmp.{os.getpid()}")
    with open(tmp_target, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_target, target_path)

    # Update drift state store
    head_sha = get_head_sha(norm_repo)
    rel_doc_path = target_path.relative_to(norm_repo).as_posix()
    state_store = DriftStateStore.load_from_repo(norm_repo)
    state_store.update_record(
        domain=domain,
        sha=head_sha,
        doc_path=rel_doc_path,
        tracked_paths=tracked_paths,
    )

    # Archive source specs if requested
    if archive_sources and valid_source_paths:
        for s_path in valid_source_paths:
            archive_ephemeral_spec(norm_repo, s_path)

    return True, target_path, f"Successfully consolidated domain '{domain}' into {rel_doc_path}"
