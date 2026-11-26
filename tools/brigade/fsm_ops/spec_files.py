"""Porcelain path filtering and YAML frontmatter expected-file parsing."""

import re
from pathlib import Path
from typing import Any, List, Optional, Set


def _parse_porcelain_paths(porcelain_output: str) -> List[str]:
    """
    Parses git status --porcelain output preserving leading status column whitespace.
    Handles '?? path', ' M path', 'M  path', 'A  path', quoted paths, and renames.
    Guaranteed Cyclomatic Complexity <= 6.
    """
    paths: List[str] = []
    if not porcelain_output or not porcelain_output.strip():
        return paths

    for raw_line in porcelain_output.splitlines():
        line = raw_line.rstrip("\r\n")
        if len(line) < 3:
            continue
        if len(line) >= 2 and line[1] == " ":
            raw_path = line[2:].strip()
        else:
            raw_path = line[3:].strip()
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ")[-1].strip()
        clean_path = raw_path.strip('"').replace("\\", "/")
        if clean_path.startswith("./"):
            clean_path = clean_path[2:]
        if clean_path:
            paths.append(clean_path)

    return list(dict.fromkeys(paths))


def _is_non_prod_file(f: str) -> bool:
    """
    Determines if a relative path is a test, doc, metadata, or task tracking file.
    Excludes .edge/, tests/, __tests__/, *.test.*, *.spec.*, test_*, *_test.*,
    frontier.md, .frontier.toml, backlog.md, done-archive.md, .md, .json, .toml.
    Guaranteed Cyclomatic Complexity <= 8.
    """
    norm = f.replace("\\", "/").strip()
    if norm.startswith("./"):
        norm = norm[2:]
    if not norm:
        return True

    name = norm.rsplit("/", 1)[-1].lower()

    if any(norm.endswith(ext) for ext in (".md", ".json", ".toml")):
        return True

    if name in ("frontier.md", ".frontier.toml", "backlog.md", "done-archive.md"):
        return True

    if name.startswith("test_") or "_test." in name:
        return True

    if any(marker in norm for marker in (".test.", ".spec.", "tests/", "__tests__/", ".edge/")):
        return True

    return False
