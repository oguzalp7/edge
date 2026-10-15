"""
Console configuration and encoding utilities for Edge Tools.
"""

import sys


def setup_utf8_console():
    """Ensure stdout and stderr use UTF-8 on Windows consoles."""
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
