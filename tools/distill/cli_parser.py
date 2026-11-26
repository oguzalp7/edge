"""Argparse subparser definitions for edge-distill."""

import argparse
from typing import Any


def register_harvest_candidate_parsers(subparsers: Any) -> None:
    """Register harvest, candidates, promote, and mark-processed parsers."""
    p_harvest = subparsers.add_parser("harvest", help="Harvest zero-token signals")
    p_harvest.add_argument("repo", nargs="?", default=".", help="Target repository")
    p_harvest.add_argument("--project", help="Target project path")
    p_harvest.add_argument("--mode", choices=["auto", "project", "factory"], default="auto", help="Operational mode")
    p_harvest.add_argument("--all-projects", action="store_true", help="Harvest all projects")
    p_harvest.add_argument("--current", help="Force harvest current session")
    p_harvest.add_argument("--format", choices=["toon", "json", "human"], default="toon", help="Output format")
    p_harvest.add_argument("--reprocess", action="store_true", help="Reprocess historical sessions")
    p_harvest.add_argument("--output", help="Output file path")
    p_harvest.add_argument("--max-sessions", type=int, default=50, help="Max sessions to analyze")
    p_harvest.add_argument("--since-hours", type=int, default=None, help="Only inspect transcripts modified within N hours")

    p_cand = subparsers.add_parser("candidates", help="Manage candidate pool")
    p_cand.add_argument("action", nargs="?", default="list", choices=["list", "record"], help="Action")
    p_cand.add_argument("--rule", help="Candidate rule text")
    p_cand.add_argument("--role", default="coder", help="Target role")
    p_cand.add_argument("--project", help="Source project path")
    p_cand.add_argument("--format", choices=["toon", "json", "human"], default="toon", help="Output format")

    p_promote = subparsers.add_parser("promote", help="Promote candidate rule")
    p_promote.add_argument("--candidate", required=True, help="Candidate ID")
    p_promote.add_argument("--plugin-root", help="Plugin root path")
    p_promote.add_argument("--force", action="store_true", help="Force promotion")

    p_mark = subparsers.add_parser("mark-processed", help="Mark session as processed")
    p_mark.add_argument("--session", action="append", help="Session ID(s)")
    p_mark.add_argument("--project", help="Project path")
    p_mark.add_argument("--mode", choices=["project", "factory"], default="project", help="Watermark mode")
    p_mark.add_argument("--clear-factory-inbox", action="store_true", help="Clear factory inbox")


def register_session_inbox_parsers(subparsers: Any) -> None:
    """Register check-budget, sessions, intents, and inbox parsers."""
    p_budget = subparsers.add_parser("check-budget", help="Check physical line budget")
    p_budget.add_argument("path", help="Path to rubric markdown file or directory")
    p_budget.add_argument("--max-lines", type=int, help="Optional line limit override")

    for name, help_text in (("sessions", "Mine Antigravity sessions"), ("intents", "Mine architectural intents")):
        p_sub = subparsers.add_parser(name, help=help_text)
        p_sub.add_argument("repo", nargs="?", default=".", help="Target repository")
        if name == "sessions":
            p_sub.add_argument("--by-project", action="store_true", help="Group by project")
        p_sub.add_argument("--brain-roots", nargs="+", help="Brain root paths")
        p_sub.add_argument("--format", choices=["human", "toon"], default="human", help="Output format")
        p_sub.add_argument("--output", help="Output file")

    p_inbox = subparsers.add_parser("inbox", help="Inspect, prune, or clear factory inbox")
    p_inbox.add_argument("action", nargs="?", default="list", choices=["list", "prune", "clear"], help="Action")
    p_inbox.add_argument("--pending-only", action="store_true", help="List only unresolved signals")
    p_inbox.add_argument("--dry-run", action="store_true", help="Preview prune counts without modifying disk")
    p_inbox.add_argument("--no-drop-exit-zero", action="store_true", help="Keep exit=0 harness signals")
    p_inbox.add_argument("--no-drop-benign-tools", action="store_true", help="Keep benign tool signals")
    p_inbox.add_argument("--resolved-only", action="store_true", help="Only prune already-resolved signals")
    p_inbox.add_argument("--max-age-days", type=int, default=None, help="Drop signals older than N days")
    p_inbox.add_argument("--project", default=None, help="Scope prune to project path")
    p_inbox.add_argument("--format", choices=["human", "json"], default="human", help="Output format")


def build_parser() -> argparse.ArgumentParser:
    """Build complete edge-distill CLI argument parser."""
    parser = argparse.ArgumentParser(prog="edge-distill", description="Edge Distill v2")
    subparsers = parser.add_subparsers(dest="subcommand")
    register_harvest_candidate_parsers(subparsers)
    register_session_inbox_parsers(subparsers)
    return parser
