#!/usr/bin/env python3
"""
Scanner and Gated Auditor for edge-drift:
Detects architectural and invariant drift between canonical domain contracts
and live code implementation via git diff gating and read-only LLM audit.
"""

import os
import json
import shutil
from pathlib import Path
from typing import List, Optional, Tuple, Union
from datetime import datetime, timezone

from tools.common.paths import normalize_target_path
from tools.common.runner import run_command
from tools.drift.models import (
    DomainContract,
    DomainDriftRecord,
    DriftCheckResult,
    SpecDiscoveryReport,
    DriftStateStore,
    parse_domain_frontmatter,
    matches_tracked_paths,
)

DRIFT_MODEL: str = "gemini-3.8-flash-high"

EXCLUDED_SPEC_NAMES = {
    "readme.md",
    "architecture.md",
    "instructions.md",
    "coding_standards.md",
}


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


def discover_specs(repo_path: Union[Path, str]) -> SpecDiscoveryReport:
    """
    Finds canonical docs/domains/*.md contracts vs scattered ephemeral/task specs
    under .edge/specs/*.md, specs/*.md, and docs/**/*.md (excluding docs/domains/**,
    .edge/archive/**, README.md, ARCHITECTURE.md, INSTRUCTIONS.md, coding_standards.md).
    """
    norm_repo = normalize_target_path(repo_path)
    domain_contracts: List[str] = []
    ephemeral_candidates: List[str] = []

    domains_dir = norm_repo / "docs" / "domains"
    if domains_dir.exists() and domains_dir.is_dir():
        for p in sorted(domains_dir.glob("*.md")):
            if p.is_file():
                rel = p.relative_to(norm_repo).as_posix()
                domain_contracts.append(rel)

    candidate_paths: List[Path] = []

    # 1. .edge/specs/*.md
    edge_specs_dir = norm_repo / ".edge" / "specs"
    if edge_specs_dir.exists():
        candidate_paths.extend(edge_specs_dir.glob("**/*.md"))

    # 2. specs/*.md
    specs_dir = norm_repo / "specs"
    if specs_dir.exists():
        candidate_paths.extend(specs_dir.glob("**/*.md"))

    # 3. docs/**/*.md
    docs_dir = norm_repo / "docs"
    if docs_dir.exists():
        candidate_paths.extend(docs_dir.glob("**/*.md"))

    seen = set()
    for p in sorted(candidate_paths):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(norm_repo).as_posix()
        except ValueError:
            continue

        if rel in seen:
            continue
        seen.add(rel)

        # Exclude canonical domain docs
        if rel.startswith("docs/domains/"):
            continue
        # Exclude archived specs
        if rel.startswith(".edge/archive/"):
            continue
        # Exclude standard repository architecture docs
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


def check_drift(
    repo_path: Union[Path, str],
    model: str = DRIFT_MODEL,
    timeout: int = 180,
) -> List[DriftCheckResult]:
    """
    Audits canonical domain contracts in docs/domains/*.md against live code.
    Enforces Zero-Token Invariant: If git diff shows 0 changes matching domain tracked_paths,
    never invokes the LLM and advances last_checked_sha to HEAD.
    """
    norm_repo = normalize_target_path(repo_path)
    head_sha = get_head_sha(norm_repo)
    state_store = DriftStateStore.load_from_repo(norm_repo)

    domains_dir = norm_repo / "docs" / "domains"
    results: List[DriftCheckResult] = []

    if not domains_dir.exists() or not domains_dir.is_dir():
        # No domain contracts found
        report_content = _render_drift_report(head_sha, results)
        drift_dir = norm_repo / ".edge" / "drift"
        drift_dir.mkdir(parents=True, exist_ok=True)
        report_file = drift_dir / "latest-drift-report.md"
        tmp_report = drift_dir / f"latest-drift-report.md.tmp.{os.getpid()}"
        with open(tmp_report, "w", encoding="utf-8") as f:
            f.write(report_content)
        os.replace(tmp_report, report_file)
        return results

    contract_files = sorted(domains_dir.glob("*.md"))

    for contract_file in contract_files:
        if not contract_file.is_file():
            continue

        try:
            with open(contract_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            results.append(
                DriftCheckResult(
                    domain=contract_file.stem,
                    status="ERROR",
                    summary=f"Failed to read contract: {str(e)}",
                )
            )
            continue

        domain_name, tracked_paths, body_text = parse_domain_frontmatter(
            content, fallback_domain=contract_file.stem
        )
        rel_doc_path = contract_file.relative_to(norm_repo).as_posix()
        contract = DomainContract(
            domain=domain_name,
            doc_path=rel_doc_path,
            tracked_paths=tracked_paths,
            body=body_text,
        )

        if not contract.tracked_paths:
            results.append(
                DriftCheckResult(
                    domain=domain_name,
                    status="UNTRACKED",
                    changed_files=[],
                    llm_invoked=False,
                    summary=f"UNTRACKED (no tracked_paths configured in {rel_doc_path})",
                )
            )
            continue

        record = state_store.get_record(domain_name)
        files_to_audit: List[str] = []

        if record and record.last_checked_sha:
            if record.last_checked_sha == head_sha:
                # ZERO LLM CALLS: SHA has not moved
                results.append(
                    DriftCheckResult(
                        domain=domain_name,
                        status="CLEAN",
                        changed_files=[],
                        llm_invoked=False,
                        summary="CLEAN (no code changes)",
                    )
                )
                continue

            changed = get_changed_files_since(norm_repo, record.last_checked_sha)
            if changed is not None:
                matched = matches_tracked_paths(changed, contract.tracked_paths)
                if len(matched) == 0:
                    # CRITICAL ZERO-TOKEN INVARIANT:
                    # Code changed elsewhere, but no tracked domain files changed.
                    # MUST NOT invoke agy! Advance last_checked_sha = head_sha.
                    state_store.update_record(
                        domain=domain_name,
                        sha=head_sha,
                        doc_path=rel_doc_path,
                        tracked_paths=contract.tracked_paths,
                    )
                    results.append(
                        DriftCheckResult(
                            domain=domain_name,
                            status="CLEAN",
                            changed_files=[],
                            llm_invoked=False,
                            summary="CLEAN (no tracked code changes)",
                        )
                    )
                    continue
                else:
                    files_to_audit = matched
            else:
                files_to_audit = contract.tracked_paths
        else:
            # First check for this domain
            files_to_audit = contract.tracked_paths

        # Run LLM drift audit via agy
        prompt = f"""You are the Edge Drift Auditor. Your role is strictly read-only verification.
Compare the domain contract '{contract.doc_path}' against the live implementation in the repository.

Tracked paths for domain '{domain_name}':
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
        cmd = ["agy", "--mode", "plan", "--model", model, "-p", prompt]
        code, stdout, stderr = run_command(cmd, cwd=norm_repo, timeout=timeout)

        if code != 0:
            results.append(
                DriftCheckResult(
                    domain=domain_name,
                    status="ERROR",
                    changed_files=files_to_audit,
                    llm_invoked=True,
                    summary=f"Error executing agy: {stderr or stdout}",
                )
            )
            continue

        output = stdout.strip()
        has_violations = any(
            cat in output
            for cat in ["BROKEN_INVARIANT", "LOGIC_SHORTCUT", "ANCHOR_DRIFT", "DOC_OUTDATED"]
        )

        if "NO_DRIFT" in output and not has_violations:
            state_store.update_record(
                domain=domain_name,
                sha=head_sha,
                doc_path=rel_doc_path,
                tracked_paths=contract.tracked_paths,
            )
            results.append(
                DriftCheckResult(
                    domain=domain_name,
                    status="CLEAN",
                    changed_files=files_to_audit,
                    llm_invoked=True,
                    summary="CLEAN (audit verified no drift)",
                )
            )
        else:
            results.append(
                DriftCheckResult(
                    domain=domain_name,
                    status="DRIFT_DETECTED",
                    changed_files=files_to_audit,
                    llm_invoked=True,
                    summary=f"DRIFT_DETECTED across {len(files_to_audit)} tracked files",
                    findings_markdown=output,
                )
            )

    # Persist latest consolidated drift report atomically
    report_content = _render_drift_report(head_sha, results)
    drift_dir = norm_repo / ".edge" / "drift"
    drift_dir.mkdir(parents=True, exist_ok=True)
    report_file = drift_dir / "latest-drift-report.md"
    tmp_report = drift_dir / f"latest-drift-report.md.tmp.{os.getpid()}"
    with open(tmp_report, "w", encoding="utf-8") as f:
        f.write(report_content)
    os.replace(tmp_report, report_file)

    return results


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
