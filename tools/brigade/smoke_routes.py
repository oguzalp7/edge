"""Tier 2 Route Smoke Scanner, Multi-Framework Discovery & Auto-Triage facade."""

from __future__ import annotations

import importlib
from typing import Any, Tuple

from tools.brigade.smoke.models import DiscoveredRoute, RouteSmokeResult, SmokeScanReport
from tools.brigade.smoke.report import format_smoke_report
from tools.brigade.smoke.scanner import run_route_smoke_scan
from tools.brigade.smoke.triage import triage_smoke_failures
from tools.brigade.smoke.urls import discover_project_routes

__all__ = [
    "DiscoveredRoute",
    "RouteSmokeResult",
    "SmokeScanReport",
    "discover_project_routes",
    "run_route_smoke_scan",
    "triage_smoke_failures",
    "format_smoke_report",
]
_SMOKE_SUBMODULES: Tuple[str, ...] = ("constants", "models", "route_params", "discover", "urls", "probe", "scanner", "tickets", "triage", "report")


def __getattr__(name: str) -> Any:
    for sub in _SMOKE_SUBMODULES:
        mod = importlib.import_module(f"tools.brigade.smoke.{sub}")
        if name in mod.__dict__:
            return mod.__dict__[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
