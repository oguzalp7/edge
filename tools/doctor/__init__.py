"""
Cross-OS environment preflight, hook health verification, and machine configuration CLI.
"""

from typing import Any

from .checks import build_capability_matrix, check_hooks_health, probe_all_tools, probe_binary
from .models import CapabilityEntry, DoctorReport, HooksHealthResult, ToolProbeResult

__all__ = [
    "CapabilityEntry",
    "DoctorReport",
    "HooksHealthResult",
    "ToolProbeResult",
    "build_capability_matrix",
    "check_hooks_health",
    "main",
    "probe_all_tools",
    "probe_binary",
    "run_doctor",
]


def __getattr__(name: str) -> Any:
    if name in ("main", "run_doctor"):
        from . import cli

        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
