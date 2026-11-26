"""Ship-prep submodule: render_output."""

from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional, Tuple
import json
import shlex

from tools.brigade.ship.models import IndexChange, ShipPrepResult, SpecDigest, SpecShipPlan
from tools.brigade.ship.paths import _is_evidence_artifact_path
from tools.brigade.ship.render_markdown import _format_markdown_sections

def _render_top_level_bodies(
    sel_slug: Optional[str],
    selected_plans: List[SpecShipPlan],
    head_branch: str,
    base_branch: str,
    changed_files: List[str],
    index_changes: List[IndexChange],
    context_terms: List[str],
    specs_linked: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    gate_status: str,
    spec_digests: List[SpecDigest],
    smoke_report: Optional[Dict[str, Any]] = None,
    security_report: Optional[Dict[str, Any]] = None,
    door_type: str = "",
    blast_radius: Optional[Dict[str, Any]] = None,
    pr_issue_links: str = "",
) -> Tuple[str, str]:
    if sel_slug and len(selected_plans) == 1:
        return selected_plans[0].pr_body, selected_plans[0].show_me_body
    code_count = len([f for f in changed_files if not _is_evidence_artifact_path(f)])
    refactor_receipts = [p.refactor_receipt for p in selected_plans if p.kind == "refactor" and p.refactor_receipt]
    pr_body = _format_markdown_sections(
        head_branch,
        base_branch,
        code_count,
        index_changes,
        context_terms,
        specs_linked,
        verified_proofs,
        failed_proofs,
        examiner_receipt,
        gate_status,
        spec_digests,
        included_plans=selected_plans,
        smoke_report=smoke_report,
        security_report=security_report,
        refactor_receipts=refactor_receipts,
        door_type=door_type,
        blast_radius=blast_radius,
        pr_issue_links=pr_issue_links,
    )
    ship_cmd = f"gh pr create --base {shlex.quote(base_branch)} --head {shlex.quote(head_branch)}"
    return pr_body, f"{pr_body}\n\n## Ship Command\n```bash\n{ship_cmd}\n```"


def format_ship_output(result: ShipPrepResult, fmt: str = "pr") -> str:
    """Formats ShipPrepResult as 'pr', 'show-me', or 'json'."""
    if fmt == "show-me":
        return result.show_me_body
    if fmt == "json":
        payload = {
            "base_branch": result.base_branch,
            "head_branch": result.head_branch,
            "intent": result.intent,
            "scenario_contract": result.scenario_contract,
            "pr_body": result.pr_body,
            "show_me_body": result.show_me_body,
            "door_type": result.door_type,
            "blast_radius": result.blast_radius,
            "index_changes": [asdict(c) for c in result.index_changes],
            "context_terms": result.context_terms,
            "specs": result.specs_linked,
            "spec_digests": [asdict(d) for d in result.spec_digests],
            "spec_plans": [p.to_dict() for p in result.spec_plans],
            "split_branches_created": result.split_branches_created,
            "selected_spec": result.selected_spec,
            "verified_proofs": result.verified_proofs,
            "failed_proofs": result.failed_proofs,
            "examiner_receipt": result.examiner_receipt,
            "smoke_report": result.smoke_report,
            "security_report": result.security_report,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return result.pr_body
