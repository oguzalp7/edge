"""Stdlib-only Stack Profile loader and capability resolver."""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

DEFAULT_PROFILES_DIR = Path(__file__).resolve().parents[2] / "profiles"
_GATE_CAPABILITY_MAP: Dict[str, Tuple[str, ...]] = {
    "type_escapes": ("typescript",),
    "verification": ("typescript", "vitest"),
    "migration_gate": ("drizzle_orm",),
    "layer_leakage": ("server_actions", "drizzle_orm"),
    "dual_theme_and_a11y": ("tailwind_dual_theme", "lucide_a11y"),
    "zero_wrappers": ("nextjs_app_router", "tailwind_dual_theme"),
    "domain_purity": ("nextjs_app_router", "tailwind_dual_theme"),
    "coolify_two_tier": ("coolify_two_tier",),
}


class ProfileResolutionError(ValueError):
    """Raised on unknown profile IDs, malformed configs, or extends cycles."""


@dataclass(frozen=True)
class StackProfile:
    id: str
    root_dir: Path
    schema_version: int = 1
    name: str = ""
    description: str = ""
    extends: Tuple[str, ...] = ()
    detect: Dict[str, Any] = field(default_factory=dict)
    capabilities: FrozenSet[str] = frozenset()
    paths: Dict[str, List[str]] = field(default_factory=dict)
    commands: Dict[str, List[str]] = field(default_factory=dict)
    delivery: Dict[str, Any] = field(default_factory=dict)
    rules: Dict[str, List[str]] = field(default_factory=dict)
    skills: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedProfileSet:
    profile_ids: List[str] = field(default_factory=list)
    profiles: List[StackProfile] = field(default_factory=list)
    source: str = "core_default"
    capabilities: FrozenSet[str] = frozenset()
    paths: Dict[str, List[str]] = field(default_factory=lambda: {
        k: [] for k in ("source_roots", "action_globs", "schema_globs", "migration_globs", "ui_globs", "test_globs")
    })
    commands: Dict[str, List[str]] = field(default_factory=dict)
    delivery: Dict[str, Any] = field(
        default_factory=lambda: {"topology": "single_main", "default_stage_branches": {"integration": "main"}}
    )
    rules: Dict[str, List[str]] = field(default_factory=lambda: {"enabled_patterns": [], "disabled_patterns": []})
    skills: List[str] = field(default_factory=list)


def _dedup(items: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(items))


def _load_profile(pid: str, profiles_dir: Path, cache: Dict[str, StackProfile]) -> StackProfile:
    if pid in cache:
        return cache[pid]
    cfg_path = profiles_dir / pid / "profile.json"
    if not cfg_path.is_file():
        raise ProfileResolutionError(f"Unknown stack profile: '{pid}'")
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    prof = StackProfile(
        id=str(raw.get("id", pid)), root_dir=cfg_path.parent, schema_version=int(raw.get("schema_version", 1)),
        name=str(raw.get("name", "")), description=str(raw.get("description", "")),
        extends=tuple(raw.get("extends", ())), detect=dict(raw.get("detect", {})),
        capabilities=frozenset(raw.get("capabilities", ())), paths={k: list(v) for k, v in raw.get("paths", {}).items()},
        commands={k: list(v) for k, v in raw.get("commands", {}).items()}, delivery=dict(raw.get("delivery", {})),
        rules={k: list(v) for k, v in raw.get("rules", {}).items()}, skills=tuple(raw.get("skills", ())),
    )
    cache[pid] = prof
    return prof


def _expand_topological(requested: List[str], profiles_dir: Path) -> List[StackProfile]:
    cache, visiting, visited, ordered = {}, set(), set(), []

    def _visit(pid: str) -> None:
        if pid in visited:
            return
        if pid in visiting:
            raise ProfileResolutionError(f"Circular profile extends involving '{pid}'")
        visiting.add(pid)
        prof = _load_profile(pid, profiles_dir, cache)
        for parent_id in prof.extends:
            _visit(parent_id)
        visiting.remove(pid)
        visited.add(pid)
        ordered.append(prof)

    for pid in requested:
        _visit(pid)
    return ordered


def _merge_profiles(ordered: List[StackProfile], source: str) -> ResolvedProfileSet:
    caps: Set[str] = set()
    paths: Dict[str, List[str]] = {}
    commands: Dict[str, List[str]] = {}
    delivery: Dict[str, Any] = {"topology": "single_main", "default_stage_branches": {"integration": "main"}}
    enabled, disabled, skills = [], [], []
    for prof in ordered:
        caps.update(prof.capabilities)
        for k, vals in prof.paths.items():
            paths[k] = _dedup([*paths.get(k, ()), *vals])
        commands.update(prof.commands)
        delivery.update(prof.delivery)
        enabled = _dedup([*enabled, *prof.rules.get("enabled_patterns", ())])
        disabled = _dedup([*disabled, *prof.rules.get("disabled_patterns", ())])
        skills = _dedup([*skills, *prof.skills])
    dis_set = set(disabled)
    return ResolvedProfileSet(
        profile_ids=[p.id for p in ordered], profiles=ordered, source=source, capabilities=frozenset(caps),
        paths=paths, commands=commands, delivery=delivery,
        rules={"enabled_patterns": [p for p in enabled if p not in dis_set], "disabled_patterns": disabled}, skills=skills,
    )


def _apply_overrides(res: ResolvedProfileSet, overrides: Optional[Dict[str, Any]]) -> ResolvedProfileSet:
    if not overrides:
        return res
    commands = {**res.commands, **overrides.get("commands", {})}
    paths = {**res.paths, **overrides.get("paths", {})}
    delivery = {**res.delivery, **overrides.get("delivery", {})}
    caps = frozenset(overrides["capabilities"]) if "capabilities" in overrides else res.capabilities
    return ResolvedProfileSet(
        res.profile_ids, res.profiles, res.source, caps, paths, commands, delivery, res.rules, res.skills
    )


def _auto_detect_ids(repo: Path, profiles_dir: Path) -> List[str]:
    if not profiles_dir.is_dir():
        return []
    pkg_deps: Set[str] = set()
    pkg_file = repo / "package.json"
    if pkg_file.is_file():
        data = json.loads(pkg_file.read_text(encoding="utf-8") or "{}")
        for sec in ("dependencies", "devDependencies", "peerDependencies"):
            pkg_deps.update(data.get(sec, {}).keys())
    cache, matches = {}, []
    for sub in sorted(profiles_dir.iterdir()):
        if not (sub / "profile.json").is_file():
            continue
        prof = _load_profile(sub.name, profiles_dir, cache)
        det = prof.detect
        all_ok = all(next(repo.glob(p), None) for p in det.get("all_files", ()))
        any_hit = any(next(repo.glob(p), None) for p in det.get("any_files", ()))
        dep_hit = any(d in pkg_deps for d in det.get("package_json_deps", ()))
        if det and all_ok and (any_hit or dep_hit or (det.get("all_files") and not det.get("any_files"))):
            matches.append(prof)
    matches.sort(key=lambda p: (-len(p.extends), p.id))
    return [matches[0].id] if matches else []


def resolve_active_profiles(repo_root: Optional[Path], profiles_dir: Optional[Path] = None) -> ResolvedProfileSet:
    """Resolve active stack profiles deterministically with zero subprocesses."""
    if repo_root is None or not Path(repo_root).exists():
        return ResolvedProfileSet(source="missing_root")
    repo = Path(repo_root)
    p_dir = Path(profiles_dir) if profiles_dir is not None else DEFAULT_PROFILES_DIR
    explicit_cfg = repo / ".edge" / "profile.json"
    if explicit_cfg.is_file():
        data = json.loads(explicit_cfg.read_text(encoding="utf-8"))
        overrides = data.get("overrides")
        raw_req = data["profiles"] if "profiles" in data else [data.get("profile")]
        req = [str(x) for x in (raw_req or []) if x and x != "none"]
        if not req:
            return _apply_overrides(ResolvedProfileSet(source="explicit_none"), overrides)
        return _apply_overrides(_merge_profiles(_expand_topological(req, p_dir), "explicit"), overrides)
    detected = _auto_detect_ids(repo, p_dir)
    return _merge_profiles(_expand_topological(detected, p_dir), "auto_detect") if detected else ResolvedProfileSet(source="core_default")


def has_profile_capability(resolved: ResolvedProfileSet, capability: str) -> bool:
    """Return True when the active profile set grants the requested capability."""
    return capability in resolved.capabilities


def is_stack_gate_enabled(resolved: ResolvedProfileSet, gate_name: str) -> bool:
    """Return True when a named verification gate is enabled by active profiles."""
    req_caps = _GATE_CAPABILITY_MAP.get(gate_name)
    return any(cap in resolved.capabilities for cap in req_caps) if req_caps else gate_name in resolved.capabilities


def load_profile_station_overlays(role_slug: str, resolved: ResolvedProfileSet) -> List[Tuple[str, str]]:
    """Load station overlay markdown files in topological base-to-derived order."""
    slug = role_slug.strip().lower().replace("_", "-")
    overlays: List[Tuple[str, str]] = []
    for prof in resolved.profiles:
        overlay_path = prof.root_dir / "agents" / f"{slug}.md"
        if overlay_path.is_file():
            content = overlay_path.read_text(encoding="utf-8").strip()
            if content:
                overlays.append((prof.id, content))
    return overlays