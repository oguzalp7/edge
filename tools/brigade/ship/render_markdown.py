"""Ship-prep submodule: render_markdown."""

from typing import List, Dict, Any, Optional, Tuple
import shlex

from tools.brigade.ship.models import IndexChange, RealizationAudit, SpecDigest, SpecShipPlan
from tools.brigade.ship.realization import compute_realization_audit
from tools.brigade.ship.render_sections import _format_summary_section
from tools.brigade.ship.render_evidence import _format_evidence_section

def _format_markdown_sections(
    head_branch: str,
    base_branch: str,
    code_count: int,
    index_changes: List[IndexChange],
    context_terms: List[str],
    specs_linked: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    gate_status: str,
    spec_digests: Optional[List[SpecDigest]] = None,
    audit: Optional[RealizationAudit] = None,
    included_plans: Optional[List[SpecShipPlan]] = None,
    smoke_report: Optional[Dict[str, Any]] = None,
    security_report: Optional[Dict[str, Any]] = None,
    refactor_receipts: Optional[List[Dict[str, Any]]] = None,
    door_type: str = "",
    blast_radius: Optional[Dict[str, Any]] = None,
    pr_issue_links: str = "",
) -> str:
    """Renders lean 2-section PR body (## Summary + ## Evidence only; no ## Merge Danger)."""
    lines = _format_summary_section(
        head_branch,
        base_branch,
        code_count,
        index_changes,
        context_terms,
        spec_digests or [],
        audit=audit,
        included_plans=included_plans,
        refactor_receipts=refactor_receipts,
        door_type=door_type,
        blast_radius=blast_radius,
    )
    lines.extend(
        _format_evidence_section(
            specs_linked,
            verified_proofs,
            failed_proofs,
            examiner_receipt,
            gate_status,
            smoke_report=smoke_report,
            security_report=security_report,
            refactor_receipts=refactor_receipts,
        )
    )
    if pr_issue_links:
        lines.extend(["", pr_issue_links])
    return "\n".join(lines)


def _render_plan_bodies(
    plan: SpecShipPlan,
    base_branch: str,
    context_terms: List[str],
    plan_receipt: Optional[Dict[str, Any]],
    gate_status: str,
    door_type: str = "",
    blast_radius: Optional[Dict[str, Any]] = None,
    pr_issue_links: str = "",
) -> None:
    if plan.realization_audit is None:
        plan.realization_audit = compute_realization_audit(plan, plan.spec_digest, plan_receipt)
    code_count = len(plan.realization_audit.actual_code_files)
    digests = [plan.spec_digest] if plan.spec_digest else []
    ref_list = [plan.refactor_receipt] if plan.refactor_receipt else []
    pr_body = _format_markdown_sections(
        plan.pr_branch, base_branch, code_count, plan.index_changes,
        context_terms, [plan.spec_path], plan.verified_proofs, plan.failed_proofs,
        plan_receipt, gate_status, digests, audit=plan.realization_audit,
        refactor_receipts=ref_list, door_type=door_type, blast_radius=blast_radius,
        pr_issue_links=pr_issue_links,
    )
    ship_cmd = (
        f"git push -u origin {shlex.quote(plan.pr_branch)}\n"
        f"gh pr create --base {shlex.quote(base_branch)} --head {shlex.quote(plan.pr_branch)} --title {shlex.quote(plan.pr_title)}"
    )
    plan.pr_body = pr_body
    plan.show_me_body = f"{pr_body}\n\n## Ship Command\n```bash\n{ship_cmd}\n```"
