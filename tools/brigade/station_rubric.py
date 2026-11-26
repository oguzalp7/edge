"""3-layer station rubric loader and bounded navigation context injector."""

from pathlib import Path
from typing import List, Optional, Any

from tools.brigade.models import Ticket
from tools.brigade.navigation import build_navigation_context

def _read_file_candidates(dir_path: Path, filenames: List[str]) -> Optional[str]:
    for fn in filenames:
        p = dir_path / fn
        if p.is_file():
            text = p.read_text(encoding="utf-8").strip()
            if text:
                return text
    return None


def load_station_rubric(role_slug: Any, repo_path: Optional[Path] = None) -> str:
    """
    Loads 3-layer rubric:
    1. Core agents/<role-slug>.md
    2. Active Stack Profile overlays (base-to-derived) under '## STACK PROFILE OVERLAY (<id>)'
    3. Repo <repo_path>/.edge/stations/<role-slug>.md under '## REPOSITORY-LOCAL STATION OVERLAY'.
    """
    raw_slug = str(role_slug.value if hasattr(role_slug, "value") else role_slug).lower().strip()
    slug = raw_slug.removeprefix("stationrole.")
    files = [slug.replace("_", "-") + ".md", slug.replace("-", "_") + ".md"]

    plugin_agents = Path(__file__).resolve().parents[2] / "agents"
    content = _read_file_candidates(plugin_agents, files)
    if not content:
        role_upper = slug.upper()
        content = (
            f"# Persona: {role_upper}\n\n"
            f"You are the {role_upper} station worker in Edge Brigade.\n"
            f"Adhere to coding_standards.md and your designated operational boundaries."
        )

    if repo_path:
        from tools.common.profiles import load_profile_station_overlays, resolve_active_profiles

        resolved_profiles = resolve_active_profiles(Path(repo_path))
        for profile_id, profile_overlay in load_profile_station_overlays(slug, resolved_profiles):
            content = f"{content}\n\n## STACK PROFILE OVERLAY ({profile_id})\n{profile_overlay}"

        overlay = _read_file_candidates(Path(repo_path) / ".edge" / "stations", files)
        if overlay:
            content = f"{content}\n\n## REPOSITORY-LOCAL STATION OVERLAY\n{overlay}"

    return content


def _collect_nav_paths(ticket: Ticket, extra_paths: Optional[List[str]] = None) -> List[str]:
    raw_paths: List[str] = []
    candidates = [
        ticket.target_file,
        *(getattr(ticket, "expected_files", None) or []),
        *(extra_paths or []),
    ]
    for p in candidates:
        if p and p not in raw_paths:
            raw_paths.append(p)
    return raw_paths


def _inject_nav_block(prompt: str, nav: str) -> str:
    if "\n---\n\n# " in prompt:
        head, tail = prompt.rsplit("\n---\n\n# ", 1)
        return f"{head}\n\n{nav}\n\n---\n\n# {tail}"
    if "\n---\n\n" in prompt:
        head, tail = prompt.rsplit("\n---\n\n", 1)
        return f"{head}\n\n{nav}\n\n---\n\n{tail}"
    return f"{prompt.rstrip()}\n\n{nav}\n"


def _with_navigation_context(
    prompt: str,
    repo_path: Optional[Path],
    ticket: Ticket,
    extra_paths: Optional[List[str]] = None,
) -> str:
    """Injects deterministic navigation context before the trailing rubric separator."""
    raw_paths = _collect_nav_paths(ticket, extra_paths)
    nav = build_navigation_context(
        repo_path,
        target_paths=raw_paths,
        domain=ticket.domain or "",
        spec_path=getattr(ticket, "spec_path", None) or "",
    )
    if not nav:
        return prompt
    return _inject_nav_block(prompt, nav)
