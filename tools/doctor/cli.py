#!/usr/bin/env python3
"""
CLI for Edge Doctor preflight check and machine configuration initialization.
@intent Run cross-OS diagnostics, emit JSON/text reports, and initialize ~/.edge/machine.json
@concepts doctor-preflight, cross-os-runtime-env
@invariants [INV-BRIGADE-CROSS-OS-ENV]
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import List, Optional

_PLUGIN_ROOT = str(Path(__file__).resolve().parents[2])
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from tools.common.env import (
    MachineConfig,
    cache_python_executable,
    detect_os_mode,
    get_plugin_root,
    load_machine_config,
    save_machine_config,
)
from tools.doctor.checks import build_capability_matrix, check_hooks_health, probe_all_tools
from tools.doctor.models import DoctorReport


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge doctor",
        description="Check cross-OS Edge runtime readiness and initialize ~/.edge/machine.json",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument("--init", action="store_true", help="Write ~/.edge/machine.json and cache Python path")
    parser.add_argument("--hooks-mode", choices=["session", "off", "strict"], default=None)
    parser.add_argument("--profile", choices=["lite", "core", "full"], default=None)
    parser.add_argument("--wsl-distro", default=None, help="Optional WSL distro name override")
    parser.add_argument("--plugin-root", default=None, help="Override plugin root path")
    return parser


def _apply_init_config(args: argparse.Namespace, os_mode: str, recommended: str) -> MachineConfig:
    cfg = load_machine_config()
    cfg.os_mode = cfg.os_mode or os_mode
    if args.hooks_mode is not None:
        cfg.hooks_mode = args.hooks_mode
    if args.profile is not None:
        cfg.install_profile = args.profile
    elif not cfg.install_profile:
        cfg.install_profile = recommended
    if args.wsl_distro is not None:
        cfg.wsl_distro = args.wsl_distro
    cfg.updated_at = datetime.now(timezone.utc).isoformat()
    save_machine_config(cfg)
    cache_python_executable()
    return cfg


def run_doctor(args: argparse.Namespace) -> DoctorReport:
    """Execute preflight probes, hooks check, and optional machine config init."""
    plugin_root = Path(args.plugin_root) if args.plugin_root else get_plugin_root()
    os_mode = detect_os_mode()
    probes = probe_all_tools()
    capabilities, recommended = build_capability_matrix(probes)
    hooks_health = check_hooks_health(plugin_root)
    cfg = _apply_init_config(args, os_mode, recommended) if args.init else load_machine_config()

    return DoctorReport(
        os_mode=os_mode,
        plugin_root=str(plugin_root),
        recommended_profile=recommended,
        hooks_health=hooks_health.to_dict(),
        tools={k: v.to_dict() for k, v in probes.items()},
        capabilities=[c.to_dict() for c in capabilities],
        machine_config=cfg.to_dict(),
    )


def _format_human_report(report: DoctorReport) -> str:
    hooks_ok = bool(report.hooks_health.get("ok"))
    lines = [
        f"Edge Doctor ({report.os_mode}) - Recommended Profile: {report.recommended_profile.upper()}",
        f"Plugin Root: {report.plugin_root}",
        f"Hooks Health: {'OK' if hooks_ok else 'BROKEN'}",
    ]
    for issue in report.hooks_health.get("issues", []):
        lines.append(f"  - Issue: {issue}")
    lines.append("Tools:")
    for name, info in report.tools.items():
        status = info.get("version") or ("found" if info.get("available") else "missing")
        lines.append(f"  - {name}: {'OK' if info.get('available') else 'NO'} ({status})")
    lines.append("Capabilities:")
    for cap in report.capabilities:
        lines.append(f"  - {cap['name']}: {cap['status']} ({cap['detail']})")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint returning 0 when hooks are healthy and 1 otherwise."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    report = run_doctor(args)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(_format_human_report(report))
    return 0 if report.hooks_health.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
