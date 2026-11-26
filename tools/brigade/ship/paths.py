"""Ship-prep submodule: paths."""

from fnmatch import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import re

from tools.brigade.ship.constants import _EVIDENCE_ARTIFACT_PREFIXES, _KNOWN_ROOT_RE, _TREEHOUSE_SLOT_RE
from tools.brigade.ship.models import IndexChange

def _clean_slug(raw: str) -> str:
    return (raw or "").strip().lower().replace("_", "-")


def _is_evidence_artifact_path(norm_path: str) -> bool:
    rel = _normalize_display_path(norm_path).lstrip("/")
    low = rel.lower()
    return any(
        low.startswith(pref) or f"/{pref}" in low
        for pref in _EVIDENCE_ARTIFACT_PREFIXES
    )


def _strip_repo_prefix(s: str, repo: Optional[Path]) -> str:
    if repo is None:
        return s
    for cand in (str(repo).replace("\\", "/").rstrip("/"),):
        if cand and s.startswith(cand + "/"):
            return s[len(cand) + 1:]
    try:
        from tools.common.paths import to_wsl_path
        wsl_repo = to_wsl_path(repo).rstrip("/")
        if wsl_repo and s.startswith(wsl_repo + "/"):
            return s[len(wsl_repo) + 1:]
    except Exception:
        pass
    return s


def _normalize_display_path(raw_path: str, repo: Optional[Path] = None) -> str:
    s = str(raw_path or "").strip().replace("\\", "/")
    if not s:
        return ""
    s = re.sub(r"^//wsl(?:\.localhost|\$)/[^/]+", "", s)
    s = re.sub(r"^[A-Za-z]:/", lambda m: f"/mnt/{m.group(0)[0].lower()}/", s)
    s = _strip_repo_prefix(s, repo)
    s = _TREEHOUSE_SLOT_RE.sub("", s)
    s = _KNOWN_ROOT_RE.sub("", s)
    s = re.sub(r"^/private(?=/(?:tmp|var)/)", "", s)
    s = re.sub(r"^/(?:home|Users)/[^/]+/[^/]+/", "", s)
    return s.lstrip("./") if s.startswith("./") else s


def _format_screenshot_title(raw_path_or_url: str) -> str:
    clean = str(raw_path_or_url or "").split("?")[0].strip()
    stem = Path(clean).stem if clean else ""
    stem = re.sub(r"^\d+[-_]+", "", stem)
    words = [w.capitalize() for w in re.split(r"[-_\s]+", stem) if w]
    return " ".join(words) or "Screenshot"


def _norm_rel_path(raw: str) -> str:
    norm = raw.replace("\\", "/").strip()
    return norm[2:] if norm.startswith("./") else norm


def _match_expected_files(expected_files: List[str], changed_files: List[str]) -> List[str]:
    matched: List[str] = []
    for cf in changed_files:
        norm_cf = _norm_rel_path(cf)
        if any(fnmatch(norm_cf, pat) or norm_cf == pat for pat in expected_files):
            matched.append(norm_cf)
    return matched


def _filter_plan_index_changes(
    index_changes: List[IndexChange],
    spec_slug: str,
    spec_path: str,
    matched_files: List[str],
) -> List[IndexChange]:
    tokens = {spec_slug, spec_path.lower()}
    tokens.update(Path(mf).stem.lower() for mf in matched_files)
    return [ch for ch in index_changes if any(tok in ch.raw_line.lower() for tok in tokens)]
