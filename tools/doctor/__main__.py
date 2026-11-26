#!/usr/bin/env python3
"""
Entrypoint for `python3 -m tools.doctor`.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
