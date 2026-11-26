"""
Isolated Navigation & Domain Context Resolver for Edge Brigade.
Slices repository navigation docs (specs/INDEX.md, CONTEXT.md, docs/domains/*.md)
and git co-change history into a bounded <=15-line context block with [STALE] link checking.
@intent Slice repository navigation docs, CONTEXT.md Domain Map globs, and co-changes into <=15 lines
@concepts bounded-navigation, domain-deed
@invariants [INV-BRIGADE-BOUNDED-NAV]
"""

import importlib
from typing import Any, Tuple

from tools.brigade.nav.builder import build_navigation_context
from tools.brigade.nav.constants import NAV_HEADER
from tools.brigade.nav.migrations import resolve_migration_paths

__all__ = ["NAV_HEADER", "build_navigation_context", "resolve_migration_paths"]
_NAV_SUBMODULES: Tuple[str, ...] = ("constants", "links", "stale", "docs", "deeds", "migrations", "cochanges", "builder")


def __getattr__(name: str) -> Any:
    for sub in _NAV_SUBMODULES:
        mod = importlib.import_module(f"tools.brigade.nav.{sub}")
        if name in mod.__dict__:
            return mod.__dict__[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    names = set(__all__)
    for sub in _NAV_SUBMODULES:
        mod = importlib.import_module(f"tools.brigade.nav.{sub}")
        names.update(k for k in mod.__dict__ if not k.startswith("__"))
    return sorted(names)
