"""Submodule: constants."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import json
import os
import re
import tempfile


_AUTH_ENTRY_SEGMENTS = {"login", "signin", "signup", "register"}


_PROTECTED_SEGMENTS = {"portal", "admin", "dashboard", "settings", "account", "studio"}


_AUTH_REDIRECT_MARKERS = ("/login", "/signin", "redirect=")


_SKIP_DIRS = {".git", "node_modules", ".next", ".edge", ".svelte-kit", "dist", "build"}


_NEXT_EXTS = (".tsx", ".ts", ".jsx", ".js")


_ASTRO_EXTS = (".astro", ".html")


_INDEX_ROUTE_RE = re.compile(r"@route\s+([^\s|]+)")


_PARAM_BRACKET_RE = re.compile(r"\[\.\.\.([^\]]+)\]|\[([^\]]+)\]")


_PARAM_COLON_RE = re.compile(r":([a-zA-Z0-9_]+)")


def _write_json_atomic(target: Path, payload: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, target)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
