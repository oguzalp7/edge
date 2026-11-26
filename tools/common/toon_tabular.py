"""
Uniform record schema extraction and tabular rendering helpers for TOON v4.4.
"""

from typing import Any, Dict, List, Optional, Tuple

from tools.common.toon_scalars import _format_key, _is_primitive, format_primitive


def _sub_dict_matches(val: Any, sub_desc: List[Tuple[str, Optional[List]]]) -> bool:
    if not isinstance(val, dict) or list(val.keys()) != [sub[0] for sub in sub_desc]:
        return False
    for sub_k, sub_sub in sub_desc:
        if sub_sub is not None or not _is_primitive(val[sub_k]):
            return False
    return True


def _record_matches_schema(
    rec: Any, keys: List[str], field_descriptors: List[Tuple[str, Optional[List]]]
) -> bool:
    if not isinstance(rec, dict) or list(rec.keys()) != keys:
        return False
    for k, sub_desc in field_descriptors:
        val = rec[k]
        if sub_desc is None:
            if not _is_primitive(val):
                return False
        elif not _sub_dict_matches(val, sub_desc):
            return False
    return True


def _extract_uniform_fields(
    records: List[Dict[str, Any]],
) -> Optional[List[Tuple[str, Optional[List]]]]:
    """Checks if a list of dicts is uniform and returns field descriptors (max 1 nested level)."""
    if not records or not isinstance(records[0], dict) or not records[0]:
        return None
    first = records[0]
    keys = list(first.keys())
    field_descriptors: List[Tuple[str, Optional[List]]] = []

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

    if not all(_record_matches_schema(r, keys, field_descriptors) for r in records[1:]):
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
    cells: List[str] = []
    for k, sub in field_descriptors:
        val = record.get(k)
        if sub is None:
            cells.append(format_primitive(val, delimiter=delimiter))
        else:
            sub_dict = val if isinstance(val, dict) else {}
            cells.extend(format_primitive(sub_dict.get(sk), delimiter=delimiter) for sk, _ in sub)
    return cells
