#!/usr/bin/env python3
"""
Bridge for edge-distill within brigade package.
"""

from tools.distill.models import (
    RescueLoop,
    NegativeConstraint,
    DiffPattern,
    DistillReport,
    StationEscapeSignal,
    ToolFrictionSignal,
    RepeatedEscalation,
    CandidateRule,
    DistillWatermarkState,
    FrictionDigest,
)
from tools.distill.harvester import TranscriptGraphHarvester
from tools.distill.state import (
    DistillStateManager,
    LexicalStackGate,
    CandidatePool,
    check_line_budget,
)
from tools.distill.cli import run_distill, main

__all__ = [
    "RescueLoop",
    "NegativeConstraint",
    "DiffPattern",
    "DistillReport",
    "StationEscapeSignal",
    "ToolFrictionSignal",
    "RepeatedEscalation",
    "CandidateRule",
    "DistillWatermarkState",
    "FrictionDigest",
    "TranscriptGraphHarvester",
    "DistillStateManager",
    "LexicalStackGate",
    "CandidatePool",
    "check_line_budget",
    "run_distill",
    "main",
]

if __name__ == "__main__":
    import sys
    sys.exit(main())
