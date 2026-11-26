"""Submodule: route_params."""

from typing import Any, Callable, Dict, List, Optional
import re

from tools.brigade.smoke.constants import _AUTH_ENTRY_SEGMENTS, _PARAM_BRACKET_RE, _PARAM_COLON_RE, _PROTECTED_SEGMENTS

def _route_pattern_to_regex(route_pattern: str) -> re.Pattern[str]:
    segs = [s for s in route_pattern.strip("/").split("/") if s]
    if not segs:
        return re.compile(r"^/$")
    parts: List[str] = []
    for seg in segs:
        if seg.startswith("[...") and seg.endswith("]"):
            parts.append(".+")
        elif (seg.startswith("[") and seg.endswith("]")) or seg.startswith(":"):
            parts.append("[^/]+")
        else:
            parts.append(re.escape(seg))
    return re.compile("^/" + "/".join(parts) + "$")


def _apply_explicit_params(route_pattern: str, params: Dict[str, str]) -> str:
    def _sub_bracket(m: re.Match[str]) -> str:
        key = m.group(1) or m.group(2)
        return str(params[key]) if key in params else m.group(0)

    out = _PARAM_BRACKET_RE.sub(_sub_bracket, route_pattern)
    return _PARAM_COLON_RE.sub(lambda m: str(params.get(m.group(1), m.group(0))), out)


def _resolve_concrete_url(
    route_pattern: str,
    params: Dict[str, str],
    visited_paths: List[str],
) -> str:
    resolved = _apply_explicit_params(route_pattern, params)
    if not _is_dynamic_route(resolved):
        return resolved
    matcher = _route_pattern_to_regex(route_pattern)
    for vp in visited_paths:
        if not _is_dynamic_route(vp) and matcher.match(vp):
            return vp
    return resolved


def _normalize_route_path(raw: str) -> str:
    clean = "/" + (raw or "").strip().strip("/")
    return re.sub(r"/+", "/", clean)


def _is_auth_entry_route(route_pattern: str) -> bool:
    segs = {s.lower() for s in route_pattern.strip("/").split("/") if s}
    return bool(segs & _AUTH_ENTRY_SEGMENTS)


def _requires_auth_route(route_pattern: str) -> bool:
    if _is_auth_entry_route(route_pattern):
        return False
    segs = {s.lower() for s in route_pattern.strip("/").split("/") if s}
    return bool(segs & _PROTECTED_SEGMENTS)


def _is_dynamic_route(route_pattern: str) -> bool:
    if "[" in route_pattern and "]" in route_pattern:
        return True
    return bool(_PARAM_COLON_RE.search(route_pattern))


def _has_skipped_segment(parts: tuple[str, ...]) -> bool:
    for seg in parts:
        if seg == "api" or seg.startswith("@") or seg.startswith("_"):
            return True
    return False


def _strip_route_groups(parts: tuple[str, ...]) -> List[str]:
    return [seg for seg in parts if not (seg.startswith("(") and seg.endswith(")"))]
