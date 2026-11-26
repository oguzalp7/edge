"""
Git-diff gated drift audit and consolidated markdown report rendering for edge-drift.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Union

from tools.common.paths import normalize_target_path
from tools.common.runner import run_command
from tools.drift.models import DomainContract, DriftCheckResult, DriftStateStore, matches_tracked_paths
from tools.drift.spec_discovery import (
    _discover_domain_contract_files,
    _load_context_domain_globs,
    _load_domain_contract,
)

DRIFT_MODEL: str = "gemini-3.8-flash-high"


def get_head_sha(repo_path: Path, runner: Callable = run_command) -> str:
    """Gets current git HEAD SHA."""
    code, out, _ = runner(["git", "rev-parse", "HEAD"], cwd=repo_path)
    return out.strip() if code == 0 else ""


def get_changed_files_since(repo_path: Path, base_sha: str, runner: Callable = run_command) -> Optional[List[str]]:
    """Returns list of files changed between base_sha and HEAD, or None on git failure."""
    if not base_sha:
        return None
    code, out, _ = runner(["git", "diff", "--name-only", f"{base_sha}..HEAD"], cwd=repo_path)
    if code != 0:
        return None
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def _render_drift_report(head_sha: str, results: List[DriftCheckResult]) -> str:
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
        lines.append(f"| `{r.domain}` | `{r.status}` | {llm_str} | {len(r.changed_files)} | {r.summary} |")

    lines.extend(["", "## Detailed Audit Findings", ""])
    for r in results:
        lines.extend([f"### Domain: `{r.domain}`", f"- **Status:** `{r.status}`", f"- **Summary:** {r.summary}"])
        if r.changed_files:
            lines.append("- **Tracked Changed Files:**")
            lines.extend(f"  - `{f}`" for f in r.changed_files)
        if r.findings_markdown:
            lines.extend(["", "#### Findings:", r.findings_markdown.strip()])
        lines.append("")
    return "\n".join(lines)


def _write_drift_report(norm_repo: Path, head_sha: str, results: List[DriftCheckResult]) -> None:
    report_content = _render_drift_report(head_sha, results)
    drift_dir = norm_repo / ".edge" / "drift"
    drift_dir.mkdir(parents=True, exist_ok=True)
    report_file = drift_dir / "latest-drift-report.md"
    tmp_report = drift_dir / f"latest-drift-report.md.tmp.{os.getpid()}"
    with open(tmp_report, "w", encoding="utf-8") as f:
        f.write(report_content)
    os.replace(tmp_report, report_file)


def _build_drift_audit_prompt(contract: DomainContract, files_to_audit: List[str]) -> str:
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


def _resolve_files_to_audit(
    norm_repo: Path,
    contract: DomainContract,
    head_sha: str,
    state_store: DriftStateStore,
    runner: Callable,
) -> Union[DriftCheckResult, List[str]]:
    record = state_store.get_record(contract.domain)
    if not (record and record.last_checked_sha):
        return contract.tracked_paths
    if record.last_checked_sha == head_sha:
        return DriftCheckResult(domain=contract.domain, status="CLEAN", summary="CLEAN (no code changes)")
    changed = get_changed_files_since(norm_repo, record.last_checked_sha, runner=runner)
    if changed is None:
        return contract.tracked_paths
    matched = matches_tracked_paths(changed, contract.tracked_paths)
    if not matched:
        state_store.update_record(domain=contract.domain, sha=head_sha, doc_path=contract.doc_path, tracked_paths=contract.tracked_paths)
        return DriftCheckResult(domain=contract.domain, status="CLEAN", summary="CLEAN (no tracked code changes)")
    return matched


def _audit_single_contract(
    norm_repo: Path,
    contract: DomainContract,
    head_sha: str,
    state_store: DriftStateStore,
    model: str,
    timeout: int,
    runner: Callable = run_command,
) -> DriftCheckResult:
    if not contract.tracked_paths:
        return DriftCheckResult(domain=contract.domain, status="UNTRACKED", summary=f"UNTRACKED (no tracked_paths configured in {contract.doc_path})")

    resolved = _resolve_files_to_audit(norm_repo, contract, head_sha, state_store, runner)
    if isinstance(resolved, DriftCheckResult):
        return resolved

    cmd = ["agy", "--mode", "plan", "--model", model, "-p", _build_drift_audit_prompt(contract, resolved)]
    code, stdout, stderr = runner(cmd, cwd=norm_repo, timeout=timeout)
    if code != 0:
        return DriftCheckResult(domain=contract.domain, status="ERROR", changed_files=resolved, llm_invoked=True, summary=f"Error executing agy: {stderr or stdout}")

    output = stdout.strip()
    has_violations = any(cat in output for cat in ("BROKEN_INVARIANT", "LOGIC_SHORTCUT", "ANCHOR_DRIFT", "DOC_OUTDATED"))
    if "NO_DRIFT" in output and not has_violations:
        state_store.update_record(domain=contract.domain, sha=head_sha, doc_path=contract.doc_path, tracked_paths=contract.tracked_paths)
        return DriftCheckResult(domain=contract.domain, status="CLEAN", changed_files=resolved, llm_invoked=True, summary="CLEAN (audit verified no drift)")

    return DriftCheckResult(
        domain=contract.domain,
        status="DRIFT_DETECTED",
        changed_files=resolved,
        llm_invoked=True,
        summary=f"DRIFT_DETECTED across {len(resolved)} tracked files",
        findings_markdown=output,
    )


def check_drift(
    repo_path: Union[Path, str],
    model: str = DRIFT_MODEL,
    timeout: int = 180,
    runner: Callable = run_command,
) -> List[DriftCheckResult]:
    """Audits canonical docs/<domain>/DOMAIN.md and legacy docs/domains/*.md contracts."""
    norm_repo = normalize_target_path(repo_path)
    contract_entries = _discover_domain_contract_files(norm_repo)
    head_sha = get_head_sha(norm_repo, runner=runner) if contract_entries else ""
    results: List[DriftCheckResult] = []

    if not contract_entries:
        _write_drift_report(norm_repo, head_sha, results)
        return results

    if not head_sha:
        results = [
            DriftCheckResult(domain=domain_name, status="ERROR", summary="Unable to resolve git HEAD SHA (empty HEAD)")
            for domain_name, _, _ in contract_entries
        ]
        _write_drift_report(norm_repo, head_sha, results)
        return results

    context_globs, _, _ = _load_context_domain_globs(norm_repo)
    state_store = DriftStateStore.load_from_repo(norm_repo)
    for domain_name, contract_file, is_canonical in contract_entries:
        loaded = _load_domain_contract(norm_repo, domain_name, contract_file, is_canonical, context_globs)
        if isinstance(loaded, DriftCheckResult):
            results.append(loaded)
        else:
            results.append(_audit_single_contract(norm_repo, loaded, head_sha, state_store, model, timeout, runner=runner))

    _write_drift_report(norm_repo, head_sha, results)
    return results
