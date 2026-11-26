"""
Scalar normalization and TOON v4.4 primitive/key formatting helpers.
"""

import re
from enum import Enum
from pathlib import Path
from typing import Any

NUMBER_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")
_KEY_BAD_CHARS = frozenset(':"[]{},')


def _is_primitive(val: Any) -> bool:
    return val is None or isinstance(val, (bool, int, float, str))


def _normalize(val: Any) -> Any:
    """Recursively converts host types, dataclasses, Paths, Enums, and custom models to JSON primitives."""
    if hasattr(val, "to_dict") and callable(val.to_dict):
        return _normalize(val.to_dict())
    if isinstance(val, Enum):
        return val.value
    if isinstance(val, Path) or hasattr(val, "__fspath__"):
        return str(val)
    if isinstance(val, dict):
        return {str(k): _normalize(v) for k, v in val.items()}
    if isinstance(val, (list, tuple, set)):
        return [_normalize(x) for x in val]
    return val if _is_primitive(val) else str(val)


def _format_float(n: float) -> str:
    if n != n or n == float("inf") or n == float("-inf"):
        return "null"
    if n == 0.0 or n == -0.0:
        return "0"
    abs_n = abs(n)
    if 1e-6 <= abs_n < 1e21:
        return str(int(n)) if n.is_integer() else f"{n:.10f}".rstrip("0").rstrip(".")
    return f"{n:e}".replace("e+", "e+")


def _format_number(n: int | float) -> str:
    """Formats a number per TOON v4.4 canonical number rules (§2)."""
    if isinstance(n, bool):
        return "true" if n else "false"
    if isinstance(n, int):
        return str(n)
    if isinstance(n, float):
        return _format_float(n)
    return str(n)


def _needs_quotes(s: str, delimiter: str = ",") -> bool:
    """Determines if a string token requires double quotes (§7.2)."""
    if not s or s in ("true", "false", "null") or NUMBER_PATTERN.match(s):
        return True
    if s[0] in (" ", "\t", "[", "{", "#") or s[-1] in (" ", "\t") or s == "-" or s.startswith("- "):
        return True
    return any(ch in s for ch in (delimiter, ":", '"', "\n", "\r"))


def _quote_string(s: str) -> str:
    """Escapes and wraps a string in double quotes (§7.1)."""
    escaped = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def format_primitive(val: Any, delimiter: str = ",") -> str:
    """Formats a single primitive scalar value (null, bool, number, string)."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return _format_number(val)
    s = str(val)
    return _quote_string(s) if _needs_quotes(s, delimiter) else s


def _format_key(key: str) -> str:
    """Formats an object or header key token."""
    s = str(key)
    if not s or s[0] in (" ", "#") or s[-1] == " " or any(ch in _KEY_BAD_CHARS for ch in s):
        return _quote_string(s)
    return s
