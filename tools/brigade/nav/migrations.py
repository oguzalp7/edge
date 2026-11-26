"""Navigation submodule: migrations."""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tools.brigade.nav.constants import _DRIZZLE_OUT_RE, _DRIZZLE_SCHEMA_RE, _ENV_DOC_CANDIDATES, _ENV_MIGRATION_PATH_RE

def _to_glob_path(raw: str, default: str) -> str:
    cleaned = raw.strip().replace("\\", "/").lstrip("./").rstrip("/")
    if not cleaned:
        return default
    if cleaned.endswith("/*"):
        return cleaned
    return f"{cleaned}/*"


def _resolve_drizzle_config_paths(root: Path) -> Optional[Tuple[str, str]]:
    for fname in ("drizzle.config.ts", "drizzle.config.js", "drizzle.config.mjs"):
        cfg = root / fname
        if cfg.is_file():
            text = cfg.read_text(encoding="utf-8", errors="replace")
            out_m = _DRIZZLE_OUT_RE.search(text)
            if out_m:
                sch_m = _DRIZZLE_SCHEMA_RE.search(text)
                schema_glob = _to_glob_path(sch_m.group(1), "src/db/schema/*") if sch_m else "src/db/schema/*"
                return (schema_glob, _to_glob_path(out_m.group(1), "drizzle/*"))
    return None


def resolve_migration_paths(repo_path: Optional[Path] = None) -> Tuple[str, str]:
    """Resolves (schema_glob, migration_glob) from drizzle.config.*, .edge/env.md, or AGENTS.md."""
    default_paths = ("src/db/schema/*", "drizzle/*")
    if repo_path is None:
        return default_paths
    root = Path(repo_path)
    if not root.is_dir():
        return default_paths
    drizzle_paths = _resolve_drizzle_config_paths(root)
    if drizzle_paths:
        return drizzle_paths
    for rel in _ENV_DOC_CANDIDATES:
        doc = root / rel
        if doc.is_file():
            m = _ENV_MIGRATION_PATH_RE.search(doc.read_text(encoding="utf-8", errors="replace"))
            if m:
                return ("src/db/schema/*", _to_glob_path(m.group(1), "drizzle/*"))
    from tools.common.profiles import resolve_active_profiles

    profiles = resolve_active_profiles(root)
    schema_globs = profiles.paths.get("schema_globs") or []
    mig_globs = profiles.paths.get("migration_globs") or []
    if schema_globs or mig_globs:
        return (
            schema_globs[0] if schema_globs else default_paths[0],
            mig_globs[0] if mig_globs else default_paths[1],
        )
    return default_paths


def _extract_bullets_from_lines(lines: List[str], limit: int) -> List[str]:
    rows: List[str] = []
    for raw in lines:
        s = raw.strip()
        if s.startswith(("- ", "* ")):
            rows.append(s)
            if len(rows) >= limit:
                break
    return rows


def _extract_agents_env_section_lines(text: str) -> List[str]:
    section: List[str] = []
    in_section = False
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("#"):
            if in_section:
                break
            in_section = "repo environment" in s.lower()
            continue
        if in_section:
            section.append(s)
    return section


def _extract_repo_env_rows(repo_root: Path, limit: int = 4) -> List[str]:
    env_file = repo_root / ".edge" / "env.md"
    if env_file.is_file():
        text = env_file.read_text(encoding="utf-8", errors="replace")
        return _extract_bullets_from_lines(text.splitlines(), limit)
    agents_file = repo_root / "AGENTS.md"
    if agents_file.is_file():
        text = agents_file.read_text(encoding="utf-8", errors="replace")
        return _extract_bullets_from_lines(_extract_agents_env_section_lines(text), limit)
    return []
