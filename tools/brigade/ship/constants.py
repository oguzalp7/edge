"""Ship-prep submodule: constants."""

from typing import List, Dict, Any, Optional, Tuple
import re

INDEX_TOKEN_RE = re.compile(r"(@route|@module|@spec|Page:|Action:|Schema:)\s+([^\s|]+)")


BOLD_TERM_RE = re.compile(r"\*\*([^*]+)\*\*")


_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


_TABLE_SEP_RE = re.compile(r"^\|[\s:\-|]+\|$")


_TICKET_RE = re.compile(r"\b(TICK-[A-Z0-9][A-Z0-9-]*)\b")


_URL_USERINFO_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^\s/@'\"]+@)")


_REPO_PREFIXES: Tuple[str, ...] = (
    "src/", "tools/", "skills/", "agents/", "rules/",
    "tests/", "scripts/", "specs/", "public/", "drizzle/", "prisma/",
)


_INLINE_PATH_RE = re.compile(
    r"((?:src|tools|skills|agents|rules|tests|scripts|specs|public|drizzle|prisma)/[^\s|`'\",;<>]+)"
)


_EVIDENCE_ARTIFACT_PREFIXES: Tuple[str, ...] = (
    ".edge/qa/screenshots/",
    ".edge/qa/proofs/",
    ".edge/qa/visual/",
)


_SLICE_BRANCH_PREFIXES: Tuple[str, ...] = (
    "feat/",
    "fix/",
    "refactor/",
    "hotfix/",
    "chore/",
    "ship/",
)


DEFAULT_STAGE_BRANCHES: Dict[str, str] = {
    "integration": "development",
    "staging": "staging",
    "production": "production",
}


_CALLSTACK_HEADING_RE = re.compile(
    r"^(#{1,4})\s+.*(?:call[-\s]?stack|responsive\s+layout\s+flow|architecture|flow|component\s+tree|file\s+tree)",
    re.IGNORECASE,
)


_HEADING_LEVEL_RE = re.compile(r"^(#{1,6})\s+(.*)$")


_CRIT_ID_RE = re.compile(r"\b((?:AC|IC)-\d+)\b")


_FENCE_BLOCK_RE = re.compile(r"```([a-zA-Z0-9_-]*)\s*\n(.*?)```", re.DOTALL)


_TREEHOUSE_SLOT_RE = re.compile(r"^.*/\.treehouse/pool/slot-\d+/[^/]+/")


_KNOWN_ROOT_RE = re.compile(
    r"^.*/(?=(?:\.edge|src|tools|skills|agents|rules|tests|scripts|specs|public|drizzle|prisma)/)"
)


_AUTH_SEGMENT_RE = re.compile(
    r"(?:^|/)(auth|middleware|permissions|rbac|session|security)(?:/|\.|$)",
    re.IGNORECASE,
)


_LAYER_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("tests", ("tests/", ".test.", ".spec.")),
    ("api", ("/actions/", "/api/", "src/actions/", "src/app/api/")),
    ("ui", ("/components/", ".tsx", ".jsx", ".css")),
    ("tooling", ("tools/", "skills/", "agents/", "rules/")),
    ("db", ("/db/", "db/")),
)
