"""
Token-Oriented Object Notation (TOON) Encoder.
Implements the TOON v4.4 specification (https://github.com/toon-format/spec).
"""

from typing import Any, Dict, List

from tools.common.toon_scalars import (
    NUMBER_PATTERN,
    _format_key,
    _format_number,
    _is_primitive,
    _needs_quotes,
    _normalize,
    _quote_string,
    format_primitive,
)
from tools.common.toon_tabular import (
    _extract_uniform_fields,
    _flatten_row_values,
    _render_field_header,
)


class ToonEncoder:
    def __init__(self, indent_size: int = 2, delimiter: str = ","):
        self.indent_size = indent_size
        self.delimiter = delimiter

    def encode(self, data: Any) -> str:
        lines: List[str] = []
        self._encode_root(_normalize(data), lines)
        return "\n".join(lines)

    def _indent(self, level: int) -> str:
        return " " * (level * self.indent_size)

    def _emit_keyed_tabular(self, mapping: Dict[str, Any], header: str, lines: List[str], row_level: int) -> bool:
        if len(mapping) < 2:
            return False
        field_desc = _extract_uniform_fields(list(mapping.values()))
        if field_desc is None:
            return False
        field_str = _render_field_header(field_desc, delimiter=self.delimiter)
        lines.append(f"{header}[{len(mapping)}:]{field_str}:")
        row_indent = self._indent(row_level)
        for k, v in mapping.items():
            cells = _flatten_row_values(v, field_desc, delimiter=self.delimiter)
            lines.append(f"{row_indent}{_format_key(k)}: {self.delimiter.join(cells)}")
        return True

    def _encode_root(self, data: Any, lines: List[str]) -> None:
        if isinstance(data, list):
            self._encode_array_val("", data, lines, level=0, is_root=True)
            return
        if isinstance(data, dict):
            if self._emit_keyed_tabular(data, "", lines, row_level=1):
                return
            for k, v in data.items():
                self._encode_object_entry(k, v, lines, level=0)
            return
        lines.append(format_primitive(data, delimiter=self.delimiter))

    def _encode_object_entry(self, key: str, val: Any, lines: List[str], level: int) -> None:
        indent = self._indent(level)
        k_fmt = _format_key(key)
        if _is_primitive(val):
            lines.append(f"{indent}{k_fmt}: {format_primitive(val, delimiter=self.delimiter)}")
            return
        if isinstance(val, list):
            self._encode_array_val(k_fmt, val, lines, level=level, is_root=False)
            return
        if isinstance(val, dict):
            if val and self._emit_keyed_tabular(val, f"{indent}{k_fmt}", lines, row_level=level + 1):
                return
            lines.append(f"{indent}{k_fmt}:")
            for sub_k, sub_v in val.items():
                self._encode_object_entry(sub_k, sub_v, lines, level=level + 1)

    def _encode_list_item(self, item: Any, item_indent: str, lines: List[str], level: int) -> None:
        if _is_primitive(item):
            lines.append(f"{item_indent}- {format_primitive(item, delimiter=self.delimiter)}")
            return
        if isinstance(item, list):
            if not item:
                lines.append(f"{item_indent}- []")
            elif all(_is_primitive(x) for x in item):
                lines.append(f"{item_indent}- [{len(item)}]: {self.delimiter.join(format_primitive(x, delimiter=self.delimiter) for x in item)}")
            else:
                lines.append(f"{item_indent}- [{len(item)}]:")
                lines.extend(f"{item_indent}  - {format_primitive(s, delimiter=self.delimiter)}" for s in item)
            return
        if isinstance(item, dict):
            if not item:
                lines.append(f"{item_indent}-")
                return
            keys = list(item.keys())
            first_k, first_v = keys[0], item[keys[0]]
            if _is_primitive(first_v):
                lines.append(f"{item_indent}- {_format_key(first_k)}: {format_primitive(first_v, delimiter=self.delimiter)}")
                rest = keys[1:]
            else:
                lines.append(f"{item_indent}-")
                rest = keys
            for k in rest:
                self._encode_object_entry(k, item[k], lines, level=level + 2)

    def _encode_array_val(
        self, key_str: str, arr: List[Any], lines: List[str], level: int, is_root: bool = False
    ) -> None:
        indent = self._indent(level)
        prefix = f"{indent}{key_str}" if key_str else indent
        if not arr:
            lines.append("[]" if is_root else f"{prefix}: []")
            return
        if all(_is_primitive(x) for x in arr):
            joined = self.delimiter.join(format_primitive(x, delimiter=self.delimiter) for x in arr)
            header = f"[{len(arr)}]:" if is_root else f"{key_str}[{len(arr)}]:"
            lines.append(f"{indent}{header} {joined}")
            return
        if all(isinstance(x, dict) for x in arr) and (field_desc := _extract_uniform_fields(arr)) is not None:
            field_str = _render_field_header(field_desc, delimiter=self.delimiter)
            header = f"[{len(arr)}]{field_str}:" if is_root else f"{key_str}[{len(arr)}]{field_str}:"
            lines.append(f"{indent}{header}")
            row_indent = self._indent(level + 1)
            lines.extend(f"{row_indent}{self.delimiter.join(_flatten_row_values(item, field_desc, delimiter=self.delimiter))}" for item in arr)
            return
        header = f"[{len(arr)}]:" if is_root else f"{key_str}[{len(arr)}]:"
        lines.append(f"{indent}{header}")
        item_indent = self._indent(level + 1)
        for item in arr:
            self._encode_list_item(item, item_indent, lines, level)


def encode(data: Any, indent_size: int = 2, delimiter: str = ",") -> str:
    """Serializes a Python object or JSON data model into a TOON v4.4 string."""
    return ToonEncoder(indent_size=indent_size, delimiter=delimiter).encode(data)


def dumps(data: Any, indent_size: int = 2, delimiter: str = ",") -> str:
    """Alias for encode() matching json.dumps convention."""
    return encode(data, indent_size=indent_size, delimiter=delimiter)
