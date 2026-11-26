"""
Path glob matching and YAML frontmatter parsing for edge-drift domain deeds.
"""

import re
from typing import List, Tuple


def _glob_to_regex(pattern: str) -> re.Pattern:
    """
    Translates a glob pattern with support for ** recursive directory globs
    and * single-segment wildcards into a compiled regex.
    """
    p = pattern.replace("\\", "/").strip()
    if p.startswith("./"):
        p = p[2:]
    if p.endswith("/"):
        p = p + "**"

    tokens: List[str] = ["^"]
    i = 0
    n = len(p)
    while i < n:
        if p[i:i + 4] == "/**/":
            tokens.append("(?:/.*/|/)")
            i += 4
        elif p[i:i + 3] == "/**":
            tokens.append("(?:/.*)?")
            i += 3
        elif p[i:i + 2] == "**":
            tokens.append(".*")
            i += 2
        elif p[i] == "*":
            tokens.append("[^/]*")
            i += 1
        elif p[i] == "?":
            tokens.append("[^/]")
            i += 1
        else:
            tokens.append(re.escape(p[i]))
            i += 1

    tokens.append("$")
    return re.compile("".join(tokens))


def matches_tracked_paths(changed_files: List[str], tracked_paths: List[str]) -> List[str]:
    """
    Normalizes backslashes to /, strips leading ./, and matches exact paths,
    * wildcards, and recursive ** directory globs.
    """
    if not changed_files or not tracked_paths:
        return []
    regexes = [_glob_to_regex(p) for p in tracked_paths if p.strip()]
    if not regexes:
        return []

    matched: List[str] = []
    for file_path in changed_files:
        norm_file = file_path.replace("\\", "/").strip()
        if norm_file.startswith("./"):
            norm_file = norm_file[2:]
        if not norm_file:
            continue
        if any(r.match(norm_file) for r in regexes):
            matched.append(file_path)
    return matched


def _parse_tracked_paths_val(val: str) -> Tuple[List[str], bool]:
    if not val:
        return [], True
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return [], False
        items = [item.strip().strip("\"'") for item in inner.split(",")]
        return [i for i in items if i], False
    item_val = val.strip("\"'")
    return ([item_val] if item_val else []), False


def parse_domain_frontmatter(
    markdown_text: str,
    fallback_domain: str = "",
) -> Tuple[str, List[str], str]:
    """
    Parses leading YAML frontmatter (--- ... ---) from docs/domains/<domain>.md,
    returning (domain, tracked_paths, body_text).
    """
    if not markdown_text.startswith("---"):
        return fallback_domain, [], markdown_text
    parts = markdown_text.split("---", 2)
    if len(parts) < 3:
        return fallback_domain, [], markdown_text

    body_text = parts[2].lstrip("\r\n")
    domain = fallback_domain
    tracked_paths: List[str] = []
    in_block = False

    for line in parts[1].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if in_block and stripped.startswith("-"):
            item_val = stripped[1:].strip().strip("\"'")
            if item_val:
                tracked_paths.append(item_val)
            continue
        in_block = False
        if ":" not in line:
            continue
        key, val = (p.strip() for p in line.split(":", 1))
        if key == "domain" and val.strip("\"'"):
            domain = val.strip("\"'")
        elif key == "tracked_paths":
            items, in_block = _parse_tracked_paths_val(val)
            tracked_paths.extend(items)

    return (domain or fallback_domain), tracked_paths, body_text
