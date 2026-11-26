"""
Common infrastructure module for Edge Tools.
"""

from .console import setup_utf8_console
from .fs import atomic_write_json, atomic_write_text, resolve_target_repo_root
from .paths import normalize_target_path, to_wsl_path, is_wsl_path
from .runner import run_command
from .toon import encode as toon_encode, dumps as toon_dumps

__all__ = [
    "setup_utf8_console",
    "resolve_target_repo_root",
    "atomic_write_text",
    "atomic_write_json",
    "normalize_target_path",
    "to_wsl_path",
    "is_wsl_path",
    "run_command",
    "toon_encode",
    "toon_dumps",
]

