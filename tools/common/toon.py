"""
Token-Oriented Object Notation (TOON) Encoder.
Implements the TOON v4.4 specification (https://github.com/toon-format/spec).
Provides token-frugal, deterministic serialization of JSON data structures for LLM prompts and Agent eXperience Interfaces (AXI).
"""

import re
from typing import Any, List, Dict, Tuple, Optional

# JSON number regex conforming to RFC 8259 §6
NUMBER_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")


from pathlib import Path
from enum import Enum


def _normalize(val: Any) -> Any:
    """Recursively converts host types, dataclasses, Paths, Enums, and custom models to standard JSON primitives."""
    if hasattr(val, "to_dict") and callable(val.to_dict):
        return _normalize(val.to_dict())
    if isinstance(val, Enum):
        return val.value
    if isinstance(val, (Path,)) or hasattr(val, "__fspath__"):
        return str(val)
    if isinstance(val, dict):
        return {str(k): _normalize(v) for k, v in val.items()}
    if isinstance(val, (list, tuple, set)):
        return [_normalize(x) for x in val]
    if _is_primitive(val):
        return val
    # Fallback to string representation for other host types
    return str(val)



def _format_number(n: int | float) -> str:
    """Formats a number per TOON v4.4 canonical number rules (§2)."""
    if isinstance(n, bool):
        return "true" if n else "false"
    if isinstance(n, int):
        return str(n)
    if isinstance(n, float):
        if n != n:  # NaN
            return "null"
        if n == float("inf") or n == float("-inf"):
            return "null"
        if n == 0.0 or n == -0.0:
            return "0"
        abs_n = abs(n)
        if 1e-6 <= abs_n < 1e21:
            # Check if it has no fractional part
            if n.is_integer():
                return str(int(n))
            s = f"{n:.10f}".rstrip("0").rstrip(".")
            return s
        return f"{n:e}".replace("e+", "e+")
    return str(n)


def _needs_quotes(s: str, delimiter: str = ",") -> bool:
    """Determines if a string token requires double quotes (§7.2)."""
    if s == "":
        return True
    if s in ("true", "false", "null"):
        return True
    if NUMBER_PATTERN.match(s):
        return True
    if s.startswith(" ") or s.endswith(" ") or s.startswith("\t") or s.endswith("\t"):
        return True
    if (
        s.startswith("- ")
        or s == "-"
        or s.startswith("[")
        or s.startswith("{")
        or s.startswith("#")
    ):
        return True
    if delimiter in s or ":" in s or '"' in s or "\n" in s or "\r" in s:
        return True
    return False


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
    if _needs_quotes(s, delimiter):
        return _quote_string(s)
    return s


def _format_key(key: str) -> str:
    """Formats an object or header key token."""
    s = str(key)
    if (
        s == ""
        or s.startswith(" ")
        or s.endswith(" ")
        or ":" in s
        or '"' in s
        or "[" in s
        or "]" in s
        or "{" in s
        or "}" in s
        or "," in s
        or s.startswith("#")
    ):
        return _quote_string(s)
    return s


def _is_primitive(val: Any) -> bool:
    return val is None or isinstance(val, (bool, int, float, str))


def _extract_uniform_fields(
    records: List[Dict[str, Any]]
) -> Optional[List[Tuple[str, Optional[List]]]]:
    """
    Checks if a list of dictionaries is uniform (identical field structure).
    Returns a list of (field_name, sub_fields_or_none) or None if not uniform.
    Supports nested field groups (§9.3).
    """
    if not records:
        return None
    first = records[0]
    if not isinstance(first, dict) or not first:
        return None

    keys = list(first.keys())

    # Build field descriptor from first record
    field_descriptors = []
    for k in keys:
        v = first[k]
        if _is_primitive(v):
            field_descriptors.append((k, None))
        elif isinstance(v, dict) and v:
            sub_fields = _extract_uniform_fields([v])
            if sub_fields is None:
                return None
            field_descriptors.append((k, sub_fields))
        else:
            return None

    # Verify all subsequent records match exact same structure
    for r in records[1:]:
        if not isinstance(r, dict):
            return None
        if list(r.keys()) != keys:
            return None
        for k, sub_desc in field_descriptors:
            val = r[k]
            if sub_desc is None:
                if not _is_primitive(val):
                    return None
            else:
                if not isinstance(val, dict):
                    return None
                if list(val.keys()) != [sub[0] for sub in sub_desc]:
                    return None
                for sub_k, sub_sub in sub_desc:
                    if sub_sub is not None:
                        return None  # Max 1 level nested groups for simplicity & predictability
                    if not _is_primitive(val[sub_k]):
                        return None

    return field_descriptors


def _render_field_header(field_descriptors: List[Tuple[str, Optional[List]]], delimiter: str = ",") -> str:
    """Constructs the field list string inside braces: {col1,nested{sub1,sub2},col3}."""
    parts = []
    for k, sub in field_descriptors:
        k_str = _format_key(k)
        if sub is None:
            parts.append(k_str)
        else:
            sub_parts = [_format_key(sk) for sk, _ in sub]
            parts.append(f"{k_str}{{{delimiter.join(sub_parts)}}}")
    return "{" + delimiter.join(parts) + "}"


def _flatten_row_values(
    record: Dict[str, Any], field_descriptors: List[Tuple[str, Optional[List]]], delimiter: str = ","
) -> List[str]:
    """Flattens a record into row cells matching depth-first leaf field order."""
    cells = []
    for k, sub in field_descriptors:
        val = record.get(k)
        if sub is None:
            cells.append(format_primitive(val, delimiter=delimiter))
        else:
            sub_dict = val if isinstance(val, dict) else {}
            for sub_k, _ in sub:
                cells.append(format_primitive(sub_dict.get(sub_k), delimiter=delimiter))
    return cells


class ToonEncoder:
    def __init__(self, indent_size: int = 2, delimiter: str = ","):
        self.indent_size = indent_size
        self.delimiter = delimiter

    def encode(self, data: Any) -> str:
        normalized = _normalize(data)
        lines: List[str] = []
        self._encode_root(normalized, lines)
        return "\n".join(lines)

    def _indent(self, level: int) -> str:
        return " " * (level * self.indent_size)

    def _encode_root(self, data: Any, lines: List[str]):
        if isinstance(data, list):
            self._encode_array_val("", data, lines, level=0, is_root=True)
        elif isinstance(data, dict):
            # Check if root dict qualifies for keyed tabular
            if len(data) >= 2:
                values = list(data.values())
                field_desc = _extract_uniform_fields(values)
                if field_desc is not None:
                    # Keyless keyed header: [N:]{...}:
                    field_str = _render_field_header(field_desc, delimiter=self.delimiter)
                    lines.append(f"[{len(data)}:]{field_str}:")
                    for k, v in data.items():
                        cells = _flatten_row_values(v, field_desc, delimiter=self.delimiter)
                        k_fmt = _format_key(k)
                        lines.append(f"{self._indent(1)}{k_fmt}: {self.delimiter.join(cells)}")
                    return

            # Standard root object
            for k, v in data.items():
                self._encode_object_entry(k, v, lines, level=0)
        else:
            # Primitive root
            lines.append(format_primitive(data, delimiter=self.delimiter))

    def _encode_object_entry(self, key: str, val: Any, lines: List[str], level: int):
        indent = self._indent(level)
        k_fmt = _format_key(key)

        if _is_primitive(val):
            lines.append(f"{indent}{k_fmt}: {format_primitive(val, delimiter=self.delimiter)}")
        elif isinstance(val, list):
            self._encode_array_val(k_fmt, val, lines, level=level, is_root=False)
        elif isinstance(val, dict):
            if not val:
                lines.append(f"{indent}{k_fmt}:")
            else:
                # Check keyed tabular form (§9.5)
                if len(val) >= 2:
                    values = list(val.values())
                    field_desc = _extract_uniform_fields(values)
                    if field_desc is not None:
                        field_str = _render_field_header(field_desc, delimiter=self.delimiter)
                        lines.append(f"{indent}{k_fmt}[{len(val)}:]{field_str}:")
                        for sub_k, sub_v in val.items():
                            cells = _flatten_row_values(sub_v, field_desc, delimiter=self.delimiter)
                            sub_k_fmt = _format_key(sub_k)
                            lines.append(f"{self._indent(level + 1)}{sub_k_fmt}: {self.delimiter.join(cells)}")
                        return

                # Normal nested object
                lines.append(f"{indent}{k_fmt}:")
                for sub_k, sub_v in val.items():
                    self._encode_object_entry(sub_k, sub_v, lines, level=level + 1)

    def _encode_array_val(
        self, key_str: str, arr: List[Any], lines: List[str], level: int, is_root: bool = False
    ):
        indent = self._indent(level)
        prefix = f"{indent}{key_str}" if key_str else indent

        if not arr:
            if is_root:
                lines.append("[]")
            else:
                lines.append(f"{prefix}: []")
            return

        # 1. Inline Form (All primitives)
        if all(_is_primitive(x) for x in arr):
            cells = [format_primitive(x, delimiter=self.delimiter) for x in arr]
            joined = self.delimiter.join(cells)
            header = f"[{len(arr)}]:" if is_root else f"{key_str}[{len(arr)}]:"
            lines.append(f"{indent}{header} {joined}")
            return

        # 2. Tabular Form (Uniform objects)
        if all(isinstance(x, dict) for x in arr):
            field_desc = _extract_uniform_fields(arr)
            if field_desc is not None:
                field_str = _render_field_header(field_desc, delimiter=self.delimiter)
                header = f"[{len(arr)}]{field_str}:" if is_root else f"{key_str}[{len(arr)}]{field_str}:"
                lines.append(f"{indent}{header}")
                row_indent = self._indent(level + 1)
                for item in arr:
                    cells = _flatten_row_values(item, field_desc, delimiter=self.delimiter)
                    lines.append(f"{row_indent}{self.delimiter.join(cells)}")
                return

        # 3. List Form (Fallback for non-uniform, nested arrays, mixed)
        header = f"[{len(arr)}]:" if is_root else f"{key_str}[{len(arr)}]:"
        lines.append(f"{indent}{header}")
        item_indent = self._indent(level + 1)
        for item in arr:
            if _is_primitive(item):
                lines.append(f"{item_indent}- {format_primitive(item, delimiter=self.delimiter)}")
            elif isinstance(item, list):
                if not item:
                    lines.append(f"{item_indent}- []")
                elif all(_is_primitive(x) for x in item):
                    cells = [format_primitive(x, delimiter=self.delimiter) for x in item]
                    lines.append(f"{item_indent}- [{len(item)}]: {self.delimiter.join(cells)}")
                else:
                    lines.append(f"{item_indent}- [{len(item)}]:")
                    for sub in item:
                        lines.append(f"{item_indent}  - {format_primitive(sub, delimiter=self.delimiter)}")
            elif isinstance(item, dict):
                if not item:
                    lines.append(f"{item_indent}-")
                else:
                    # First field on same line as hyphen (§10)
                    keys = list(item.keys())
                    first_k = keys[0]
                    first_v = item[first_k]
                    if _is_primitive(first_v):
                        lines.append(f"{item_indent}- {_format_key(first_k)}: {format_primitive(first_v, delimiter=self.delimiter)}")
                        for other_k in keys[1:]:
                            self._encode_object_entry(other_k, item[other_k], lines, level=level + 2)
                    else:
                        lines.append(f"{item_indent}-")
                        for k in keys:
                            self._encode_object_entry(k, item[k], lines, level=level + 2)


def encode(data: Any, indent_size: int = 2, delimiter: str = ",") -> str:
    """Serializes a Python object or JSON data model into a TOON v4.4 string."""
    return ToonEncoder(indent_size=indent_size, delimiter=delimiter).encode(data)


def dumps(data: Any, indent_size: int = 2, delimiter: str = ",") -> str:
    """Alias for encode() matching json.dumps convention."""
    return encode(data, indent_size=indent_size, delimiter=delimiter)
