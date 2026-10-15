#!/usr/bin/env python3
"""
CLI Driver for edge-distill: Pattern & Playbook Miner & Incident Flight Recorder.
Provides:
- Live flight recorder journaling (`start`, `log`, `status`, `resolve`)
- Domain discovery and playbook proposal generation (`propose`)
- Direct one-shot distillation (`run`)
"""

import sys
import os
import argparse
from pathlib import Path
from typing import Optional, List

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import setup_utf8_console, normalize_target_path, toon_encode
setup_utf8_console()


try:
    from .miner import DistillMiner
    from .generator import PlaybookGenerator
    from .journal import DistillJournal
    from .session_miner import SessionMiner
    from .models import DistillReport, PlaybookProposal
except ImportError:
    from tools.distill.miner import DistillMiner
    from tools.distill.generator import PlaybookGenerator
    from tools.distill.journal import DistillJournal
    from tools.distill.session_miner import SessionMiner
    from tools.distill.models import DistillReport, PlaybookProposal


def cmd_mine_sessions(
    repo_path: Optional[Path] = None,
    by_project: bool = False,
    output_path: Optional[str] = None,
    brain_roots: Optional[List[str]] = None,
    format: str = "human",
) -> int:
    """Mines Antigravity sessions and prints terminal report, saving to JSON."""
    repo = repo_path or Path.cwd()
    roots = [Path(r) for r in brain_roots] if brain_roots else None
    miner = SessionMiner(brain_roots=roots, repo_path=repo)
    data = miner.mine_sessions()

    out_file = miner.save_sessions_json(data, output_path=output_path)
    if format == "toon":
        print(toon_encode({"sessions_summary": data}))
    else:
        report_text = miner.format_sessions_report(data, by_project=by_project)
        print("\n" + report_text)
    print(f"\n💾 Oturum verisi kaydedildi: {out_file}\n")
    return 0


def cmd_mine_intents(
    repo_path: Optional[Path] = None,
    output_path: Optional[str] = None,
    brain_roots: Optional[List[str]] = None,
    format: str = "human",
) -> int:
    """Mines architectural intents and prints intent mirror report, saving to JSON."""
    repo = repo_path or Path.cwd()
    roots = [Path(r) for r in brain_roots] if brain_roots else None
    miner = SessionMiner(brain_roots=roots, repo_path=repo)
    data = miner.mine_sessions()

    out_file = miner.save_sessions_json(data, output_path=output_path)
    if format == "toon":
        print(toon_encode({"intents_summary": data}))
    else:
        report_text = miner.format_intents_report(data)
        print("\n" + report_text)
    print(f"\n💾 Analiz verisi kaydedildi: {out_file}\n")
    return 0



def cmd_start_session(repo_path: Path, goal: str, operational_domain: str = "reconcile") -> int:
    """Starts continuous flight recorder session."""
    journal_mgr = DistillJournal(repo_path)
    session = journal_mgr.start_session(
        goal=goal or "Crisis intervention & feature synchronization",
        operational_domain=operational_domain or "reconcile",
    )
    dom_str = (session.operational_domain or "reconcile").upper()
    print("\n" + "=" * 65)
    print("⏺️  EDGE DISTILL — FLIGHT RECORDER ENGAGED (KARA KUTU BAŞLATILDI)")
    print("=" * 65)
    print(f"Session ID:         {session.session_id}")
    print(f"Operational Domain: {dom_str}")
    print(f"Goal:               {session.goal}")
    print(f"Baseline Commit:    {session.baseline_commit}")
    print(f"Status:             {session.status}")
    print(f"Started At:         {session.started_at}")
    print("-" * 65)
    print("💡 Operasyon devam ederken adımları kaydetmek için:")
    print("   edge-distill log <repo> --step 'Eksik seam yazıldı' --tag SEAM_CREATION")
    print("   Problem çözüldüğünde bitirmek için:")
    print("   edge-distill resolve <repo> --notes 'Davranış senkronize edildi'")
    print("=" * 65 + "\n")
    return 0


def cmd_log_step(repo_path: Path, step: str, tag: str = "OBSERVATION") -> int:
    """Logs an action to the active flight recorder."""
    journal_mgr = DistillJournal(repo_path)
    entry = journal_mgr.log_step(step=step, tag=tag)
    print(f"📝 [LOGGED {entry.tag}] ({entry.timestamp[11:19]}) : {entry.step}")
    return 0


def cmd_session_status(repo_path: Path) -> int:
    """Shows status of current flight recorder session."""
    journal_mgr = DistillJournal(repo_path)
    session = journal_mgr.get_active_session()
    print("\n" + "=" * 65)
    print("📊 EDGE DISTILL — FLIGHT RECORDER STATUS")
    print("=" * 65)
    if not session:
        print("Kayıtlı aktif bir uçuş kaydı (session) bulunmamaktadır.")
        print("Başlatmak için: edge-distill start <repo> --goal <hedef>")
    else:
        dom_str = (session.operational_domain or "reconcile").upper()
        print(f"Session ID:         {session.session_id}")
        print(f"Status:             {session.status}")
        print(f"Operational Domain: {dom_str}")
        print(f"Goal:               {session.goal}")
        print(f"Baseline Commit:    {session.baseline_commit}")
        print(f"Started At:         {session.started_at}")
        print(f"Total Steps Logged: {len(session.journal_entries)}")
        print("-" * 65)
        print("📜 Recent Steps:")
        for e in session.journal_entries[-5:]:
            print(f"  - [{e.tag}] {e.step}")
    print("=" * 65 + "\n")
    return 0


def cmd_resolve_session(repo_path: Path, notes: str) -> int:
    """Resolves session upon 'problem solved' sign-off."""
    journal_mgr = DistillJournal(repo_path)
    session = journal_mgr.resolve_session(resolution_notes=notes)
    print("\n" + "=" * 65)
    print("✅ EDGE DISTILL — PROBLEM RESOLVED (KARA KUTU MÜHÜRLENDİ)")
    print("=" * 65)
    print(f"Session ID:         {session.session_id}")
    print(f"Status:             {session.status}")
    print(f"Resolution Notes:   {session.resolution_notes}")
    print(f"Final Commit:       {session.final_commit}")
    print(f"Resolved At:        {session.resolved_at}")
    print("-" * 65)
    print("🎯 Şimdi kaydedilen verilerden yeni Playbook Proposal'ı üretmek için:")
    print("   edge-distill propose <repo>")
    print("=" * 65 + "\n")
    return 0


def cmd_generate_proposal(repo_path: Path, output_path: str = None) -> int:
    """Mines the completed flight recorder session and generates a Playbook Proposal."""
    miner = DistillMiner(repo_path)
    proposal = miner.mine_session_proposal()
    generator = PlaybookGenerator(repo_path)
    out_file = generator.generate_proposal(proposal, output_path=output_path)

    print("\n" + "=" * 65)
    print("📜 EDGE DISTILL — OPERATIONAL PLAYBOOK PROPOSAL GENERATED")
    print("=" * 65)
    print(f"Proposal ID:        {proposal.proposal_id}")
    print(f"Target Domain:      {proposal.domain_name.upper()} (Discovered/Stabilized Domain)")
    print(f"Title:              {proposal.title}")
    print(f"Chronological Steps:{len(proposal.chronological_steps)}")
    print(f"Rescue Moves Mined: {len(proposal.rescue_loops)}")
    print(f"Negative Constraints:{len(proposal.negative_constraints)}")
    print("-" * 65)
    print(f"📄 Proposal Dosyası: {out_file}")
    print("=" * 65 + "\n")
    return 0


def run_distill(
    repo_path: Path,
    domain: str = None,
    track: str = "core",
    ticket_id: str = None,
    output_path: str = None,
    max_commits: int = 15,
) -> int:
    """Core function to mine and generate domain playbook."""
    miner = DistillMiner(repo_path)
    report = miner.mine(
        domain=domain,
        track=track,
        ticket_id=ticket_id,
        max_commits=max_commits,
    )

    generator = PlaybookGenerator(repo_path)
    out_file = generator.generate(report, output_path=output_path)

    print("\n" + "=" * 65)
    print("🏛️  EDGE DISTILL — PATTERN & PLAYBOOK MINER")
    print("=" * 65)
    print(f"Repository:         {repo_path}")
    print(f"Mined Domain:       {report.domain} [{report.track.upper()}]")
    print(f"Target Controller:  {report.target_file}")
    print(f"Base Branch:        {report.base_branch}")
    print(f"Active Ticket:      {report.ticket_id or 'None'}")
    print("-" * 65)
    print(f"🛟  Rescue Loops Mined:         {len(report.rescue_loops)}")
    for rl in report.rescue_loops[:3]:
        print(f"    - [{rl.stage}] {rl.rule_enforced}")
    print(f"🚫 Negative Constraints Mined:  {len(report.negative_constraints)}")
    for nc in report.negative_constraints[:3]:
        print(f"    - [{nc.severity}] {nc.title}")
    print(f"🔄 AST Diff Patterns Mined:     {len(report.diff_patterns)}")
    print(f"🔧 Compiler Fixes Identified:   {len(report.compiler_fixes)}")
    print("-" * 65)
    print(f"📄 Generated Playbook: {out_file}")
    print("=" * 65 + "\n")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    raw_args = list(argv if argv is not None else sys.argv[1:])
    subcommands = {"start", "log", "status", "resolve", "propose", "run", "sessions", "intents"}

    # If first argument is not a known subcommand and not a help flag, treat as 'run'
    if raw_args and raw_args[0] not in subcommands and not raw_args[0].startswith("-"):
        raw_args = ["run"] + raw_args

    parser = argparse.ArgumentParser(
        prog="edge-distill",
        description="Edge Distill: Pattern & Playbook Miner & Incident Flight Recorder",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # start
    p_start = subparsers.add_parser("start", help="Start a continuous flight recorder session")
    p_start.add_argument("repo", help="Path to target repository")
    p_start.add_argument("--goal", default="Crisis intervention & feature synchronization", help="Goal of this session")
    p_start.add_argument("--domain", default="reconcile", help="Operational domain (feature, refactor, reconcile)")

    # log
    p_log = subparsers.add_parser("log", help="Log a step or decision into active session")
    p_log.add_argument("repo", help="Path to target repository")
    p_log.add_argument("--step", required=True, help="Description of action or discovery")
    p_log.add_argument("--tag", default="OBSERVATION", choices=["OBSERVATION", "SEAM_CREATION", "BEHAVIOR_SYNC", "BUG_FIX", "RESCUE_MOVE", "GATE_CHECK"], help="Tag category")

    # status
    p_status = subparsers.add_parser("status", help="View status of flight recorder session")
    p_status.add_argument("repo", help="Path to target repository")

    # resolve
    p_res = subparsers.add_parser("resolve", help="Sign-off session when problem is solved")
    p_res.add_argument("repo", help="Path to target repository")
    p_res.add_argument("--notes", default="Problem successfully resolved and behaviors synchronized.", help="Resolution notes")

    # propose
    p_prop = subparsers.add_parser("propose", help="Distill flight recorder into an operational playbook proposal")
    p_prop.add_argument("repo", help="Path to target repository")
    p_prop.add_argument("--output", help="Custom output path for proposal")

    # sessions
    p_sess = subparsers.add_parser("sessions", help="Mine and classify Antigravity conversation sessions")
    p_sess.add_argument("repo", nargs="?", default=".", help="Path to target repository (default: current dir)")
    p_sess.add_argument("--by-project", action="store_true", help="Group and display sessions chronologically by project")
    p_sess.add_argument("--format", choices=["human", "toon"], default="human", help="Output format: human (default) or toon (token-frugal)")
    p_sess.add_argument("--output", help="Custom output path for sessions.json")
    p_sess.add_argument("--brain-roots", nargs="+", help="Override brain root directories to scan")

    # intents
    p_intents = subparsers.add_parser("intents", help="Analyze recurring architectural intents and directives mirror")
    p_intents.add_argument("repo", nargs="?", default=".", help="Path to target repository (default: current dir)")
    p_intents.add_argument("--format", choices=["human", "toon"], default="human", help="Output format: human (default) or toon (token-frugal)")
    p_intents.add_argument("--output", help="Custom output path for sessions.json")
    p_intents.add_argument("--brain-roots", nargs="+", help="Override brain root directories to scan")

    # run (legacy one-shot)
    p_run = subparsers.add_parser("run", help="One-shot playbook distillation from existing data")
    p_run.add_argument("repo", help="Path to target repository")
    p_run.add_argument("--domain", help="Target domain (e.g. bookings, customers)")
    p_run.add_argument("--track", default="core", choices=["core", "ui"], help="Debt track")
    p_run.add_argument("--ticket", help="Target ticket ID")
    p_run.add_argument("--output", help="Custom output path for generated playbook")
    p_run.add_argument("--max-commits", type=int, default=15, help="Max commits to inspect")

    args = parser.parse_args(raw_args)

    repo_path = normalize_target_path(args.repo)
    if not repo_path.exists():
        print(f"❌ Error: Repository path does not exist: {repo_path}", file=sys.stderr)
        return 1

    # Route subcommands
    if args.subcommand == "start":
        return cmd_start_session(repo_path, args.goal, args.domain)

    elif args.subcommand == "log":
        return cmd_log_step(repo_path, args.step, args.tag)

    elif args.subcommand == "status":
        return cmd_session_status(repo_path)

    elif args.subcommand == "resolve":
        return cmd_resolve_session(repo_path, args.notes)

    elif args.subcommand == "propose":
        return cmd_generate_proposal(repo_path, args.output)

    elif args.subcommand == "sessions":
        return cmd_mine_sessions(
            repo_path=repo_path,
            by_project=args.by_project,
            output_path=args.output,
            brain_roots=args.brain_roots,
            format=getattr(args, "format", "human"),
        )

    elif args.subcommand == "intents":
        return cmd_mine_intents(
            repo_path=repo_path,
            output_path=args.output,
            brain_roots=args.brain_roots,
            format=getattr(args, "format", "human"),
        )


    elif args.subcommand == "run":
        return run_distill(
            repo_path=repo_path,
            domain=args.domain,
            track=args.track,
            ticket_id=args.ticket,
            output_path=args.output,
            max_commits=args.max_commits,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
