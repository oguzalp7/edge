"""YAML frontmatter expected-file parsing helpers for BrigadeFSM."""

from pathlib import Path
from typing import Any, List, Optional


def _parse_expected_files_frontmatter_fallback(frontmatter: str) -> List[str]:
    """Fallback line scanner for expected_files list in YAML frontmatter when PyYAML is unavailable."""
    items: List[str] = []
    lines = iter(frontmatter.splitlines())
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("expected_files:"):
            continue
        val = stripped[len("expected_files:"):].strip()
        if val.startswith("[") and val.endswith("]"):
            return [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
        for subline in lines:
            sub = subline.strip()
            if not sub or sub.startswith("#"):
                continue
            if not sub.startswith("- "):
                return items
            items.append(sub[2:].strip().strip("'\""))
        break
    return items


def _clean_expected_list(raw_list: Any) -> List[str]:
    if not isinstance(raw_list, list):
        return []
    cleaned: List[str] = []
    for item in raw_list:
        s = str(item).strip().replace("\\", "/")
        s = s[2:] if s.startswith("./") else s
        if s:
            cleaned.append(s)
    return list(dict.fromkeys(cleaned))


def _extract_spec_expected_files(
    repo_path: Path, spec_path: Optional[str] = None, clean_name: str = ""
) -> List[str]:
    """Safely discovers and extracts expected_files from spec YAML frontmatter. Never mines prose."""
    if spec_path:
        cand = repo_path / spec_path
    elif clean_name:
        cand = repo_path / ".edge" / "specs" / f"{clean_name}.md"
    else:
        return []
    if not cand.exists() or not cand.is_file():
        return []
    try:
        content = cand.read_text(encoding="utf-8", errors="ignore")
        if not content.startswith("---"):
            return []
        parts = content.split("---", 2)
        if len(parts) < 3:
            return []
        frontmatter = parts[1]
        raw_list: Optional[List[Any]] = None
        try:
            import yaml
            parsed = yaml.safe_load(frontmatter)
            if isinstance(parsed, dict) and "expected_files" in parsed:
                raw_list = parsed.get("expected_files")
        except Exception:
            raw_list = None
        if raw_list is None:
            raw_list = _parse_expected_files_frontmatter_fallback(frontmatter)
        return _clean_expected_list(raw_list)
    except Exception:
        return []
