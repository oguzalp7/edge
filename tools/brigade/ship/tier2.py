"""Ship-prep submodule: tier2."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json

from tools.brigade.refactor_receipt import RefactorReceiptVerifier, compute_changed_files_hash
from tools.brigade.security_audit import run_security_audit, triage_security_findings
from tools.brigade.smoke_routes import SmokeScanReport, triage_smoke_failures
from tools.brigade.ship.constants import DEFAULT_STAGE_BRANCHES
from tools.brigade.ship.models import ShipPrepResult
from tools.brigade.ship.split_branches import create_split_branches

def _check_tier2_smoke_report(
    repo: Path,
    base_branch: str,
    require_smoke: bool,
    stage_branches: Optional[Dict[str, str]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    eff_stages = stage_branches or DEFAULT_STAGE_BRANCHES
    staging_branch = eff_stages.get("staging", "staging")
    raw_base = (base_branch or "").strip()
    clean_base = raw_base[7:] if raw_base.startswith("origin/") else raw_base
    if clean_base != staging_branch:
        return True, None, ""
    smoke_file = repo / ".edge" / "qa" / "smoke-routes.json"
    if not smoke_file.is_file():
        if require_smoke:
            return (
                False,
                None,
                "Tier 2 staging release blocked: Route smoke scan report missing at "
                ".edge/qa/smoke-routes.json. Run 'brigade smoke-routes .' first.",
            )
        return True, None, ""
    try:
        raw = json.loads(smoke_file.read_text(encoding="utf-8"))
        report = SmokeScanReport.from_dict(raw)
    except Exception:
        return False, None, "Tier 2 staging release blocked: Malformed smoke scan report at .edge/qa/smoke-routes.json."
    if not report.all_navigable:
        triage_smoke_failures(repo, report)
        return (
            False,
            report.to_dict(),
            f"Tier 2 staging release blocked: Route smoke scan failed "
            f"({report.failed_routes}/{report.total_routes} route(s) non-navigable).",
        )
    return True, report.to_dict(), ""


def _check_tier2_security_audit(
    repo: Path,
    base_branch: str,
    eff_base: str,
    changed_files: List[str],
    stage_branches: Optional[Dict[str, str]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    eff_stages = stage_branches or DEFAULT_STAGE_BRANCHES
    staging_branch = eff_stages.get("staging", "staging")
    raw_base = (base_branch or "").strip()
    clean_base = raw_base[7:] if raw_base.startswith("origin/") else raw_base
    if clean_base != staging_branch:
        return True, None, ""
    sec_report = run_security_audit(
        repo, diff_only=True, base_ref=eff_base, changed_files=changed_files
    )
    if not sec_report.passed:
        triage_security_findings(repo, sec_report)
        return (
            False,
            sec_report.to_dict(),
            f"Tier 2 staging release blocked: Security audit found "
            f"{sec_report.confirmed_count} confirmed vulnerability/ies.",
        )
    return True, sec_report.to_dict(), ""


def _run_tier2_gates(
    repo: Path,
    base_branch: str,
    eff_base: str,
    changed_files: List[str],
    require_smoke: bool,
    eff_stages: Dict[str, str],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    smoke_ok, smoke_report, smoke_err = _check_tier2_smoke_report(
        repo, base_branch, require_smoke, stage_branches=eff_stages
    )
    sec_ok, sec_report, sec_err = _check_tier2_security_audit(
        repo, base_branch, eff_base, changed_files, stage_branches=eff_stages
    )
    gate_err = smoke_err if not smoke_ok else (sec_err if not sec_ok else "")
    return smoke_report, sec_report, gate_err


def _validate_ship_result(
    result: ShipPrepResult,
    strict_proofs: bool,
    split_branches: bool,
    repo: Path,
    eff_base: str,
    ticket_map: Optional[Dict[str, str]] = None,
    gate_err: str = "",
) -> Tuple[bool, ShipPrepResult, str]:
    if gate_err:
        return False, result, gate_err
    if result.failed_proofs:
        return False, result, f"ProofVerifier rejected {len(result.failed_proofs)} QA proof receipt(s)."
    for plan in result.spec_plans:
        if plan.kind == "refactor" and plan.refactor_receipt is not None:
            v_ok, v_msg, _ = RefactorReceiptVerifier.verify_receipt(plan.refactor_receipt, strict=True)
            if not v_ok:
                return False, result, f"RefactorReceipt blocked ({plan.spec_slug}): {v_msg}"
    if strict_proofs and not result.verified_proofs and not result.examiner_receipt:
        return False, result, "Strict proofs mode failed: no verified QA proofs or ExaminerReceipt found."
    if split_branches:
        sp_ok, created, sp_err = create_split_branches(repo, eff_base, result.spec_plans, ticket_map=ticket_map)
        result.split_branches_created = created
        if not sp_ok:
            return False, result, sp_err
    return True, result, ""
