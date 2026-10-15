"""
Common infrastructure module for Edge Tools.
"""

from .console import setup_utf8_console
from .paths import normalize_target_path, to_wsl_path, is_wsl_path
from .runner import run_command
from .toon import encode as toon_encode, dumps as toon_dumps

__all__ = [
    "setup_utf8_console",
    "normalize_target_path",
    "to_wsl_path",
    "is_wsl_path",
    "run_command",
    "toon_encode",
    "toon_dumps",
]

