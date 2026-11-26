"""Candidate pool, promotion, and watermark subcommands for edge-distill."""

import argparse
import json
from pathlib import Path
import sys

from tools.common import normalize_target_path
from tools.distill.cli_harvest import cmd_harvest, run_distill
from tools.distill.state import CandidatePool, DistillStateManager, FactoryInbox


def cmd_candidates(args: argparse.Namespace) -> int:
    """List or record cross-project candidate rules."""
    action, pool = getattr(args, "action", "list"), CandidatePool()
    if action == "record":
        rule = getattr(args, "rule", None)
        if not rule:
            print("Error: --rule is required for record action", file=sys.stderr)
            return 1
        cand = pool.record_candidate(
            rule_text=rule, target_role=getattr(args, "role", "coder"),
            project_path=str(normalize_target_path(getattr(args, "project", "."))),
        )
        print(f"Recorded candidate {cand.candidate_id}: {cand.status}")
        return 0
    cands, fmt = pool.list_candidates(), getattr(args, "format", "toon")
    if fmt == "json":
        print(json.dumps([c.to_dict() for c in cands], indent=2))
    elif fmt == "toon":
        for c in cands:
            print(c.to_toon())
    else:
        for c in cands:
            print(f"{c.candidate_id} [{c.status}] ({c.target_role}): {c.rule_text}")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """Promote an eligible candidate rule into target rubric."""
    cid = getattr(args, "candidate", None)
    if not cid:
        print("Error: --candidate is required", file=sys.stderr)
        return 1
    root = getattr(args, "plugin_root", None)
    pool = CandidatePool(plugin_root=Path(root) if root else None)
    try:
        ok = pool.promote_candidate(candidate_id=cid, force=getattr(args, "force", False))
        print(f"Promoted candidate {cid}" if ok else f"Candidate {cid} not eligible for promotion")
        return 0
    except ValueError as exc:
        print(f"Error promoting candidate {cid}: {exc}", file=sys.stderr)
        return 1


def cmd_mark_processed(args: argparse.Namespace) -> int:
    """Mark session IDs processed or clear the factory inbox."""
    clear_inbox, mode = getattr(args, "clear_factory_inbox", False), getattr(args, "mode", "project")
    raw_sessions = getattr(args, "session", []) or []
    if isinstance(raw_sessions, str):
        raw_sessions = [raw_sessions]
    sessions = [s.strip() for raw in raw_sessions for s in raw.split(",") if s.strip()]
    if not sessions and not clear_inbox:
        print("Error: --session or --clear-factory-inbox is required", file=sys.stderr)
        return 1
    if clear_inbox or mode == "factory":
        FactoryInbox().clear()
        print("Cleared factory inbox")
    if sessions:
        proj = getattr(args, "project", None)
        proj_str = str(normalize_target_path(proj)) if proj else None
        manager = DistillStateManager()
        for sid in sessions:
            manager.mark_session_processed(session_id=sid, project_path=proj_str, mode=mode)
            print(f"Marked session {sid} as processed ({mode} mode)")
    return 0
