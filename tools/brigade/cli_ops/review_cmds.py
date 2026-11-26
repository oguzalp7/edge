"""Examiner review finding and seal commands."""

import argparse

from tools.brigade.cli_ops._facade import resolve_symbol
from tools.brigade.models import ExaminerReceipt, ReviewFinding
from tools.common import normalize_target_path


def cmd_add_finding(args: argparse.Namespace) -> int:
    """Append a review finding to BrigadeState."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    finding = ReviewFinding(
        axis=args.axis, severity=args.severity.upper(), file_path=args.file,
        rule=args.rule, description=args.desc,
        suggested_fix=args.fix or "Remediate finding in code.", line_number=args.line,
    )
    fsm.state.review_findings.append(finding)
    fsm.save()
    print(f"✅ Added {args.severity.upper()} finding ({args.axis}) in {args.file}")
    return 0


def cmd_clear_findings(args: argparse.Namespace) -> int:
    """Clear all review findings from BrigadeState."""
    repo_path = normalize_target_path(args.repo)
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    count = len(fsm.state.review_findings)
    fsm.state.review_findings = []
    fsm.save()
    print(f"✅ Cleared {count} review findings.")
    return 0


def cmd_seal_review(args: argparse.Namespace) -> int:
    """Seal 3-axis Examiner review verdict into BrigadeState."""
    repo_path = normalize_target_path(args.repo)
    verdict = str(getattr(args, "verdict", "") or "").strip().upper()
    summary = str(getattr(args, "summary", "") or "").strip()
    if verdict not in ("PASS", "FAIL"):
        print(f"❌ Invalid verdict '{args.verdict}'. Expected PASS or FAIL.")
        return 1
    if not summary:
        print("❌ Non-empty --summary is required to seal review.")
        return 1
    raw_ev = getattr(args, "evidence_reviewed", "") or ""
    evidence = [e.strip() for e in raw_ev.split(",") if e.strip()]
    fsm = resolve_symbol("BrigadeFSM", "tools.brigade.fsm")(repo_path)
    ticket_id = fsm.state.active_ticket.ticket_id if fsm.state.active_ticket else None
    ex_cid = getattr(args, "examiner_cid", None)
    if not ex_cid and "examiner" in fsm.state.stations:
        ex_cid = getattr(fsm.state.stations["examiner"], "conversation_id", None) or None
    fsm.state.examiner_receipt = ExaminerReceipt(
        verdict=verdict, summary=summary, ticket_id=ticket_id, evidence_reviewed=evidence, examiner_cid=ex_cid,
    )
    fsm.save()
    print(f"✅ Examiner review sealed: [{verdict}] (ticket: {ticket_id or 'N/A'})")
    return 0
