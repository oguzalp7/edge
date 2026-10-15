#!/usr/bin/env python3
"""
Bridge for edge-distill within brigade package.
"""

from tools.distill.models import RescueLoop, NegativeConstraint, DiffPattern, DistillReport
from tools.distill.miner import DistillMiner
from tools.distill.generator import PlaybookGenerator
from tools.distill.cli import run_distill, main

__all__ = [
    "RescueLoop",
    "NegativeConstraint",
    "DiffPattern",
    "DistillReport",
    "DistillMiner",
    "PlaybookGenerator",
    "run_distill",
    "main",
]

if __name__ == "__main__":
    import sys
    sys.exit(main())
