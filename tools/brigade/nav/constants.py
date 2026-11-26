"""Navigation constants and drift parser fallbacks."""

import re
from typing import Dict, List, Tuple

try:
    from tools.common.paths import to_wsl_path
except ImportError:  # pragma: no cover - standalone fallback
    def to_wsl_path(path: object) -> str:
        return str(path).replace("\\", "/")

try:
    from tools.drift.models import (
        matches_tracked_paths,
        parse_canonical_domain_doc,
        parse_context_glossary,
        parse_domain_frontmatter,
    )
except ImportError:  # pragma: no cover - lightweight stdlib fallback
    def parse_domain_frontmatter(markdown_text: str, fallback_domain: str = "") -> Tuple[str, List[str], str]:
        if not markdown_text.startswith("---"):
            return fallback_domain, [], markdown_text
        parts = markdown_text.split("---", 2)
        return (fallback_domain, [], parts[2].lstrip("\r\n")) if len(parts) >= 3 else (fallback_domain, [], markdown_text)

    def parse_canonical_domain_doc(markdown_text: str, doc_path: str, fallback_domain: str = "") -> object:
        return None

    def parse_context_glossary(markdown_text: str) -> Tuple[Dict[str, List[str]], List[str]]:
        return {}, []

    def matches_tracked_paths(changed_files: List[str], tracked_paths: List[str]) -> List[str]:
        return []


NAV_HEADER = "### 🧭 NAVIGATION & DOMAIN CONTEXT"


_INDEX_CANDIDATES = ("specs/INDEX.md", ".edge/INDEX.md", "INDEX.md")


_GLOSSARY_CANDIDATES = ("CONTEXT.md", "GLOSSARY.md")


_ENV_DOC_CANDIDATES = (".edge/env.md", "AGENTS.md")


_DRIZZLE_OUT_RE = re.compile(r'out\s*:\s*["\']([^"\']+)["\']')


_DRIZZLE_SCHEMA_RE = re.compile(r'schema\s*:\s*["\']([^"\']+)["\']')


_ENV_MIGRATION_PATH_RE = re.compile(r"`((?:src/)?db/migrations(?:/\*)?)`")


_LOCKFILES = {
    "package-lock.json",
    "uv.lock",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
}


_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")


_MD_SEP_RE = re.compile(r"^\|[\s:\-|]+\|$")


_LINK_TITLE_RE = re.compile(r'\s+(?:"[^"]*"|\'[^\']*\')\s*$')
