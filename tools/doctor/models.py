#!/usr/bin/env python3
"""
Data models for Edge Doctor preflight diagnostics and capability matrix.
@intent Define serializable dataclasses for tool probes, hook health, and capability tiers
@concepts doctor-preflight, cross-os-runtime-env
@invariants [INV-BRIGADE-CROSS-OS-ENV]
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ToolProbeResult:
    """Result of probing a single host or guest CLI binary."""

    name: str
    available: bool
    path: str = ""
    version: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "path": self.path,
            "version": self.version,
            "error": self.error,
        }


@dataclass
class CapabilityEntry:
    """Capability tier status derived from probed toolchain availability."""

    name: str
    status: str  # "native" | "passive" | "unavailable"
    detail: str = ""
    required_tools: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "required_tools": list(self.required_tools),
        }


@dataclass
class HooksHealthResult:
    """Verification outcome for root hooks.json and cross-OS dispatcher files."""

    ok: bool
    issues: List[str] = field(default_factory=list)
    plugin_root: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": list(self.issues),
            "plugin_root": self.plugin_root,
        }


@dataclass
class DoctorReport:
    """Top-level Edge Doctor preflight diagnostic report."""

    os_mode: str
    plugin_root: str
    recommended_profile: str
    hooks_health: Dict[str, Any]
    tools: Dict[str, Dict[str, Any]]
    capabilities: List[Dict[str, Any]]
    machine_config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "os_mode": self.os_mode,
            "plugin_root": self.plugin_root,
            "recommended_profile": self.recommended_profile,
            "hooks_health": dict(self.hooks_health),
            "tools": dict(self.tools),
            "capabilities": list(self.capabilities),
            "machine_config": dict(self.machine_config),
        }
