"""Dual-layer refactor ticket creation and 4-seal receipt commands."""

import argparse
from typing import Any, Dict, Optional

from tools.brigade.cli_ops._facade import resolve_symbol
from tools.common import normalize_target_path


def _parse_metric_targets(raw_targets: Optional[str]) -> Dict[str, Any]:
    targets: Dict[str, Any] = {}
    for tok in (raw_targets or "").split(","):
        if "=" not in tok:
            continue
        key, raw_val = tok.split("=", 1)
        k, v_s = key.strip(), raw_val.strip()
        if not k or not v_s:
            continue
        try:
            targets[k] = int(v_s) if "." not in v_s else float(v_s)
        except ValueError:
            continue
    return targets


def cmd_create_refactor_ticket(args: argparse.Namespace) -> int:
    """Create dual-layer refactor ticket and optional tasks-axi entry."""
    from tools.brigade.tasks_bridge import create_refactor_ticket

    repo_path = normalize_target_path(args.repo)
    rules = [r.strip() for r in (getattr(args, "rules", "") or "").split(",") if r.strip()]
    files = [f.strip() for f in (getattr(args, "files", "") or "").split(",") if f.strip()]
    ok, ticket_path, tasks_id = create_refactor_ticket(
        repo_path=repo_path, slug=args.slug, track=args.track, target_rules=rules, target_files=files,
        metric_targets=_parse_metric_targets(getattr(args, "targets", "")), door_type=getattr(args, "door", "two-way") or "two-way",
        sync_tasks=getattr(args, "sync_tasks", None), hold_captain=bool(getattr(args, "hold_captain", False)),
        parent_issue=getattr(args, "parent_issue", None), offline=bool(getattr(args, "offline", False)),
    )
    if not ok:
        print(f"❌ Failed to create refactor ticket at {ticket_path}")
        return 1
    print(f"✅ Refactor ticket written: {ticket_path}")
    if tasks_id:
        print(f"   Linked tasks-axi ID: {tasks_id}")
    return 0


def cmd_seal_refactor(args: argparse.Namespace) -> int:
    """Synthesize 4-seal machine-generated RefactorReceipt."""
    from tools.brigade.refactor_receipt import build_and_write_refactor_receipt

    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(normalize_target_path(args.repo))
    ticket = fsm.state.active_ticket
    base_ref = getattr(args, "base", None) or fsm.state.base_branch or "development"
    slug = getattr(args, "slug", None) or (fsm._derive_refactor_slug(ticket) if ticket else "refactor")
    surgeon_cid = (ticket.surgeon_cid if ticket else None) or fsm._resolve_station_cid("surgeon")
    receipt, json_path, md_path = build_and_write_refactor_receipt(
        target_repo=fsm.target_repo, work_dir=fsm._get_work_dir(), slug=slug, base_branch=base_ref,
        ticket=ticket, examiner_receipt=fsm.state.examiner_receipt, surgeon_cid=surgeon_cid,
    )
    print(f"✅ RefactorReceipt sealed: {json_path} & {md_path}")
    print(f"   Commit: {receipt.seal_1_intent.get('commit_sha', '')[:12]}")
    print(f"   Gate passed: {receipt.seal_3_gate.get('all_passed')}")
    return 0
