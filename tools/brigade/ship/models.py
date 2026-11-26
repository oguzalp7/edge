"""Ship-prep submodule: models."""

from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional, Tuple

@dataclass
class IndexChange:
    kind: str       # "@route" | "Page" | "@module" | "Action" | "Schema" | "@spec" | "other"
    symbol: str
    raw_line: str


@dataclass
class SpecDigest:
    path: str
    title: str
    summary: str
    mermaid_blocks: List[str] = field(default_factory=list)
    matrix_rows: List[str] = field(default_factory=list)
    callstack_blocks: List[str] = field(default_factory=list)
    acceptance_criteria: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class RealizationAudit:
    actual_code_files: List[str] = field(default_factory=list)
    realized_files: List[str] = field(default_factory=list)
    untouched_expected_files: List[str] = field(default_factory=list)
    unplanned_extra_files: List[str] = field(default_factory=list)
    file_tree_diff: str = ""
    criteria_rows: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class SpecShipPlan:
    spec_slug: str
    spec_path: str
    pr_branch: str
    pr_title: str
    expected_files: List[str] = field(default_factory=list)
    matched_files: List[str] = field(default_factory=list)
    index_changes: List[IndexChange] = field(default_factory=list)
    verified_proofs: List[Dict[str, Any]] = field(default_factory=list)
    failed_proofs: List[Dict[str, Any]] = field(default_factory=list)
    spec_digest: Optional[SpecDigest] = None
    pr_body: str = ""
    show_me_body: str = ""
    ticket_id: Optional[str] = None
    commit_shas: List[str] = field(default_factory=list)
    realization_audit: Optional[RealizationAudit] = None
    kind: str = "spec"
    refactor_receipt: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ShipPrepResult:
    base_branch: str
    head_branch: str
    door_type: str
    blast_radius: Dict[str, Any]
    index_changes: List[IndexChange]
    context_terms: List[str]
    specs_linked: List[str]
    verified_proofs: List[Dict[str, Any]]
    failed_proofs: List[Dict[str, Any]]
    examiner_receipt: Optional[Dict[str, Any]]
    intent: str
    scenario_contract: List[str]
    pr_body: str
    show_me_body: str
    spec_digests: List[SpecDigest] = field(default_factory=list)
    spec_plans: List[SpecShipPlan] = field(default_factory=list)
    split_branches_created: List[str] = field(default_factory=list)
    selected_spec: Optional[str] = None
    smoke_report: Optional[Dict[str, Any]] = None
    security_report: Optional[Dict[str, Any]] = None


def _empty_result(base_branch: str, head_branch: str = "") -> ShipPrepResult:
    return ShipPrepResult(
        base_branch=base_branch,
        head_branch=head_branch,
        door_type="Two-way door (Reversible Code / Configuration Change)",
        blast_radius={"changed_file_count": 0, "changed_files": [], "layers": [], "domains": []},
        index_changes=[],
        context_terms=[],
        specs_linked=[],
        verified_proofs=[],
        failed_proofs=[],
        examiner_receipt=None,
        intent="",
        scenario_contract=[],
        pr_body="",
        show_me_body="",
    )


def call_run_command(*args: Any, **kwargs: Any) -> Any:
    """Routes subprocess calls through tools.brigade.ship_prep.run_command so monkeypatches intercept."""
    import sys
    from tools.common import run_command as _default_run_command
    facade = sys.modules.get("tools.brigade.ship_prep")
    fn = getattr(facade, "run_command", _default_run_command) if facade is not None else _default_run_command
    return fn(*args, **kwargs)

