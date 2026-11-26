"""
Cross-OS environment preflight, hook health verification, and machine configuration CLI.
"""

from .checks import build_capability_matrix, check_hooks_health, probe_all_tools, probe_binary
from .cli import main, run_doctor
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
