"""Ship-prep submodule: render_sections."""

from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.models import IndexChange, RealizationAudit, SpecDigest, SpecShipPlan
from tools.brigade.ship.render_refactor import _format_refactor_summary_block

def _format_realization_subsection(audit: Optional[RealizationAudit]) -> List[str]:
    if not audit:
        return []
    lines = [
        "",
        "### Spec Expectations vs. Realization",
        (
            f"- **Files:** `{len(audit.realized_files)}` realized · "
            f"`{len(audit.untouched_expected_files)}` untouched expected · "
            f"`{len(audit.unplanned_extra_files)}` unplanned scope delta"
        ),
    ]
    if audit.file_tree_diff:
        lines.append(audit.file_tree_diff)
    if audit.criteria_rows:
        lines.extend([
            "| ID | Spec Expectation | Status | Realized Evidence / Notes |",
            "| :--- | :--- | :--- | :--- |",
        ])
        for row in audit.criteria_rows:
            exp_clean = str(row["expectation"]).replace("|", "\\|")
            ev_clean = str(row["evidence"]).replace("|", "\\|")
            lines.append(f"| `{row['id']}` | {exp_clean} | {row['status']} | {ev_clean} |")
    return lines


def _format_architecture_subsection(spec_digests: List[SpecDigest]) -> List[str]:
    mermaids: List[str] = []
    callstacks: List[str] = []
    for digest in spec_digests:
        mermaids.extend(digest.mermaid_blocks[:2])
        callstacks.extend(digest.callstack_blocks[:3])
    if not mermaids and not callstacks:
        return []
    lines = ["", "### Architecture & Call-Stack Flow"]
    for m_block in mermaids[:2]:
        lines.extend(["```mermaid", m_block, "```"])
    for c_block in callstacks[:3]:
        lines.extend(["```text", c_block, "```"])
    return lines


def _format_included_specs_subsection(included_plans: List[SpecShipPlan]) -> List[str]:
    if not included_plans:
        return []
    lines = ["", "### Included Specs & Realization"]
    for plan in included_plans:
        title = plan.spec_digest.title if plan.spec_digest and plan.spec_digest.title else plan.spec_slug
        audit = plan.realization_audit
        if audit is not None:
            stats = (
                f"{len(audit.actual_code_files)} code file(s), "
                f"{len(audit.realized_files)} realized / "
                f"{len(audit.untouched_expected_files)} untouched / "
                f"{len(audit.unplanned_extra_files)} unplanned"
            )
        else:
            stats = f"{len(plan.matched_files)} matched file(s)"
        proof_badge = f"✅ {len(plan.verified_proofs)} proof(s)" if plan.verified_proofs else "—"
        lines.append(f"- **{title}** (`{plan.spec_slug}`, branch `{plan.pr_branch}`): {stats} · QA: {proof_badge}")
    return lines


def _format_summary_section(
    head_branch: str,
    base_branch: str,
    code_count: int,
    index_changes: List[IndexChange],
    context_terms: List[str],
    spec_digests: List[SpecDigest],
    audit: Optional[RealizationAudit] = None,
    included_plans: Optional[List[SpecShipPlan]] = None,
    refactor_receipts: Optional[List[Dict[str, Any]]] = None,
    door_type: str = "",
    blast_radius: Optional[Dict[str, Any]] = None,
) -> List[str]:
    lines = [
        "## Summary",
        f"- **Branch:** `{head_branch}` -> `{base_branch}` ({code_count} code file(s) changed)",
    ]
    if index_changes:
        idx_summary = ", ".join(f"`{c.kind} {c.symbol}`" for c in index_changes[:8])
        lines.append(f"- **Navigation Index (`specs/INDEX.md`):** {idx_summary}")
    if context_terms:
        lines.append(f"- **Domain Vocabulary (`CONTEXT.md`):** {', '.join(context_terms)}")
    for digest in spec_digests:
        lines.append(f"- **Spec (`{digest.path}`):** {digest.title}" + (f" — {digest.summary}" if digest.summary else ""))
    if refactor_receipts:
        lines.extend(_format_refactor_summary_block(refactor_receipts, door_type=door_type, blast_radius=blast_radius))
    lines.extend(_format_realization_subsection(audit))
    if audit is None and included_plans:
        lines.extend(_format_included_specs_subsection(included_plans))
    lines.extend(_format_architecture_subsection(spec_digests))
    return lines
