"""Tests for tools.brigade.cli facade, lazy subcommand parser, and patch seams."""

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import tools.brigade.cli as brigade_cli
from tools.brigade.cli_ops.parser import COMMAND_MAP, build_parser


def test_cli_parser_registers_all_subcommands() -> None:
    parser = build_parser()
    for cmd_name in ("init", "register", "stations", "triage", "ticket", "advance", "status", "graph", "start-slice", "finish-slice", "prepare-ship", "smoke-routes", "security-audit", "tier", "distill"):
        assert cmd_name in COMMAND_MAP
    args = parser.parse_args(["tier", ".", "--action", "status", "--json"])
    assert args.command == "tier" and args.json is True


def test_cli_lazy_getattr_and_monkeypatch_seam(tmp_path: Path, capsys) -> None:
    assert callable(brigade_cli.cmd_prepare_ship)
    assert callable(brigade_cli.cmd_seal_review)
    fake_res = SimpleNamespace(success=True, model_used="opus", fallback_triggered=False, report_path="", summary="looks good", error="")
    with patch("tools.brigade.cli.run_spec_critique", return_value=fake_res) as mock_crit:
        rc = brigade_cli.cmd_critique_spec(Namespace(repo=str(tmp_path), spec="spec.md", issue=None))
    assert rc == 0
    assert mock_crit.called
    assert "looks good" in capsys.readouterr().out
