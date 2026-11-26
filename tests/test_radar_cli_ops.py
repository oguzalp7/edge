import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from types import SimpleNamespace

from tools.radar.cli_ops import cmd_report, cmd_status


def test_radar_cli_ops_status_and_report(tmp_path: Path, capsys) -> None:
    ledger_dir = tmp_path / ".edge" / "ledger"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "meta.json").write_text(
        '{"updated_at": "2026-01-01", "overall_health_score": 95, "total_open_findings": 0, "channels": {}}',
        encoding="utf-8",
    )
    cmd_status(SimpleNamespace(target=str(tmp_path), format="json"))
    assert "overall_health_score" in capsys.readouterr().out

    out_md = tmp_path / "report.md"
    cmd_report(SimpleNamespace(target=str(tmp_path), top=5, format="markdown", out=str(out_md)))
    assert out_md.exists() and "Edge Radar" in out_md.read_text(encoding="utf-8")
