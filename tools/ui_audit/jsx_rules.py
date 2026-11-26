"""Tailwind class category classifiers for JSXFingerprinter."""

from typing import List, Optional, Set, Tuple


def _has_prefix(class_set: Set[str], prefixes: Tuple[str, ...]) -> bool:
    return any(c.startswith(prefixes) for c in class_set)


def _has_substr(class_set: Set[str], needles: Tuple[str, ...]) -> bool:
    return any(n in c for c in class_set for n in needles)


def _match_overlay_or_drawer(class_set: Set[str]) -> Optional[str]:
    if not (class_set & {"fixed", "absolute"}):
        return None
    if "inset-0" in class_set or "backdrop-blur" in class_set or _has_prefix(class_set, ("bg-black/",)):
        return "modal_overlay"
    if {"items-center", "justify-center"} <= class_set:
        return "modal_container"
    if (class_set & {"inset-y-0", "right-0", "left-0"}) and (_has_prefix(class_set, ("max-w-",)) or _has_substr(class_set, ("translate-x", "transition"))):
        return "drawer"
    return None


def _match_skeleton_or_button(tag: str, class_set: Set[str]) -> Optional[str]:
    is_muted = _has_substr(class_set, ("bg-gray-200", "bg-zinc-200", "bg-muted"))
    if "animate-pulse" in class_set or (is_muted and _has_prefix(class_set, ("h-",)) and _has_prefix(class_set, ("rounded",))):
        return "skeleton"
    if tag.lower() in ("button", "link") or "cursor-pointer" in class_set:
        has_act = _has_prefix(class_set, ("hover:", "bg-")) or _has_substr(class_set, ("font-medium", "font-semibold"))
        if _has_prefix(class_set, ("px-", "p-")) and _has_prefix(class_set, ("rounded",)) and has_act:
            return "button"
    return None


def _match_banner_card_or_table(tag: str, class_set: Set[str]) -> Optional[str]:
    alert_bg = _has_prefix(class_set, ("bg-red-", "bg-green-", "bg-yellow-", "bg-amber-", "bg-blue-"))
    if _has_prefix(class_set, ("border-l-",)) or _has_substr(class_set, ("alert",)) or (alert_bg and _has_prefix(class_set, ("p-",)) and _has_prefix(class_set, ("rounded",))):
        return "alert_banner"
    has_card_bg = _has_prefix(class_set, ("bg-white", "bg-zinc-", "bg-slate-"))
    if has_card_bg and _has_prefix(class_set, ("rounded-",)) and (class_set & {"p-4", "p-5", "p-6", "p-8"}) and (class_set & {"shadow", "shadow-sm", "shadow-md", "border"}):
        return "card"
    if tag.lower() == "table" or bool(class_set & {"overflow-x-auto", "min-w-full"}):
        return "table_container"
    return None


def categorize_jsx_pattern(tag: str, classes: List[str]) -> Optional[str]:
    """Classify JSX tag + class list into canonical primitive categories."""
    class_set = set(classes)
    return _match_overlay_or_drawer(class_set) or _match_skeleton_or_button(tag, class_set) or _match_banner_card_or_table(tag, class_set)
