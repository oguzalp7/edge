"""
Path normalization, project attribution, and intent definitions for edge-distill SessionMiner.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_BRAIN_ROOTS = [
    Path("~/.gemini/antigravity/brain"),
    Path("~/.gemini/antigravity-cli/brain"),
]

BRAIN_REGEX = re.compile(r"[/\\]\.gemini[/\\]antigravity(?:-cli)?[/\\]brain", re.IGNORECASE)
MCP_REGEX = re.compile(r"[/\\]\.gemini[/\\]antigravity(?:-cli)?[/\\]mcp", re.IGNORECASE)

INTENT_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "Context Hygiene": {
        "title": "Bağlam Hijyeni & Delegasyon (Context Hygiene)",
        "rule_hint": "rules/AGENTS.md & rules/playbooks/pause-safely.md",
        "patterns": [
            "bağlam", "baglam", "balon", "temiz tut", "alt ajan", "altajan",
            "delege", "koda boğulma", "koda bogulma", "yeşil alan", "yesil alan",
            "hafıza şiş", "hafiza sis", "soğuk başlangıç",
            "soguk baslangic", "kirletme",
        ],
    },
    "Vertical Slice": {
        "title": "Dikey Dilim & Bütünlük (Vertical Slice & Pocock/Dex Invariant)",
        "rule_hint": "rules/feature.md & rules/AGENTS.md",
        "patterns": [
            "dikey dilim", "vertical slice", "uçtan uca", "uctan uca",
            "yarım bırakma", "yarim birakma", "sadece db", "katman",
            "asılı kal", "asili kal",
        ],
    },
    "Seam & Contracts": {
        "title": "Seam & Sözleşme Disiplini (Feathers Seams & Contracts)",
        "rule_hint": "rules/refactor.md & rules/edge-core-refactor",
        "patterns": [
            "seam", "dikiş yeri", "dikis yeri", "sözleşme", "sozlesme",
            "contract", "interface", "repo", "controller şişkin", "controller siskin",
        ],
    },
    "Test Immutability": {
        "title": "TDD & Test İntizamı (Test Immutability & Anti-Cheating)",
        "rule_hint": "rules/refactor.md & rules/feature.md (Karakterizasyon Testi)",
        "patterns": [
            "önce test", "once test", "kırmızı test", "kirmizi test",
            "testi bozma", "sahte test", "hile yapma", "karakterizasyon",
            "kodu teste uydurma",
        ],
    },
    "Visual Gate": {
        "title": "Görsel Doğrulama & UI (Visual Gate)",
        "rule_hint": "skills/edge-orchestrator/SKILL.md (lavish-axi)",
        "patterns": [
            "lavish", "prototip", "görsel", "gorsel", "arayüz", "arayuz",
            "bana göster", "bana goster", "onay almadan yazma", "tarayıcı", "tarayici",
        ],
    },
}

_IGNORED_SUBDIRS = {"tests", "test", "unit", "src", "dist", "build", "resources", "node_modules"}


def normalize_path_string(p: str) -> str:
    """Cleans up raw path/URI strings, normalizing separators and removing URL prefixes."""
    if not p:
        return ""
    p = str(p).strip().strip("\"'")
    if p.startswith("file:///"):
        rest = p[8:]
        p = rest if (len(rest) >= 2 and rest[1] == ":" and rest[0].isalpha()) else "/" + rest
    elif p.startswith("file://"):
        p = p[7:]
    return p.replace("\\\\", "/").replace("\\", "/")


def _extract_worktree_project(stripped: str) -> Optional[str]:
    m_wt = re.search(r"(?:^|/)worktrees/([a-zA-Z0-9_\-]+)", stripped)
    if not m_wt:
        return None
    wt_target = m_wt.group(1)
    if not re.match(r"^[0-9a-f]{8,}$", wt_target):
        return wt_target
    m_repo = re.search(r"/([^/]+)/worktrees/" + wt_target, stripped)
    if not m_repo:
        return None
    repo_name = m_repo.group(1).lstrip(".")
    if repo_name and repo_name not in ("antigravity", "antigravity-cli", "var", "tmp"):
        return repo_name
    return None


def extract_project_from_path(p: str) -> Optional[str]:
    """Extracts high-confidence project name from path or URI string."""
    norm = normalize_path_string(p)
    if not norm or BRAIN_REGEX.search(norm) or MCP_REGEX.search(norm):
        return None
    stripped = re.sub(r"^(?:[a-zA-Z]:/|//wsl\.localhost/[^/]+/|/mnt/[a-z]/)", "/", norm)
    if "/" not in stripped.strip("/"):
        return None
    if re.search(r"/[^/]+\.[a-zA-Z0-9_\-]+$", stripped):
        stripped = re.sub(r"/[^/]+\.[a-zA-Z0-9_\-]+$", "", stripped)

    m_plugin = re.search(r"(?:^|/)plugins/([a-zA-Z0-9_\-]+)", stripped)
    if m_plugin:
        return m_plugin.group(1)
    wt_proj = _extract_worktree_project(stripped)
    if wt_proj:
        return wt_proj
    m_user = re.search(
        r"(?:/home/[^/]+|/Users/[^/]+/(?:Desktop|Documents|Projects|Developer|dev|code|repos|workspace|work)|/Users/[^/]+|/Desktop)/([a-zA-Z0-9_\-]+)",
        stripped,
    )
    if m_user:
        name = m_user.group(1).lstrip(".")
        if name not in ("tmp", "temp", "cache", "var", "Library", "Applications"):
            return name

    parts = [part for part in stripped.strip("/").split("/") if part]
    if len(parts) >= 2:
        if parts[0] in ("tmp", "temp", "var", "opt") and parts[1] not in _IGNORED_SUBDIRS:
            return parts[1]
        if parts[1] in ("src", "lib", "tests", "test", "app", "components") and parts[0] not in _IGNORED_SUBDIRS:
            return parts[0]
    return None


def extract_paths_from_command(cmd: str) -> List[str]:
    """Extracts path-like tokens from a command line string."""
    if not cmd or not isinstance(cmd, str):
        return []
    return re.findall(r"(?:[a-zA-Z]:[\\/]|/[a-zA-Z0-9_.-]+)[^\s\"'><;|]+", cmd)


def extract_conversation_id(transcript_path: Path) -> str:
    """Extracts conversation_id from standard brain path layout."""
    parts = transcript_path.parts
    if len(parts) >= 4 and parts[-3] == ".system_generated":
        return parts[-4]
    return transcript_path.parent.name


def parse_timestamp(ts: str) -> Optional[datetime]:
    """Parses ISO timestamp safely, handling Z suffix and timezone offsets."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def extract_clean_quote(text: str, keyword: str) -> str:
    """Extracts a crisp, meaningful sentence or snippet containing the target keyword."""
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    for s in re.split(r"[\n.!?]+", cleaned):
        s = s.strip()
        if keyword.lower() in s.lower() and len(s) >= 12:
            return s[:180].strip()
    return cleaned.strip()[:180]
