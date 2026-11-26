#!/usr/bin/env python3
"""CLI Driver Facade for edge-distill v2."""

from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Optional

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import setup_utf8_console

setup_utf8_console()

from tools.distill.cli_cmds import (
    cmd_candidates,
    cmd_harvest,
    cmd_mark_processed,
    cmd_promote,
    run_distill,
)
from tools.distill.cli_ops import cmd_check_budget, cmd_inbox, cmd_intents, cmd_sessions
from tools.distill.cli_parser import build_parser

DISPATCH_MAP: Dict[str, Callable[[Any], int]] = {
    "harvest": cmd_harvest,
    "candidates": cmd_candidates,
    "promote": cmd_promote,
    "mark-processed": cmd_mark_processed,
    "check-budget": cmd_check_budget,
    "sessions": cmd_sessions,
    "intents": cmd_intents,
    "inbox": cmd_inbox,
}


def main(argv: Optional[List[str]] = None) -> int:
    """Parse CLI arguments and dispatch selected edge-distill subcommand."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.subcommand:
        parser.print_help()
        return 0
    handler = DISPATCH_MAP.get(args.subcommand)
    if not handler:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
