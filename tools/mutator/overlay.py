"""Worker Overlay Materialization and Leak-Free Cleanup."""

import os
from pathlib import Path
import shutil
from typing import Dict, List, Optional, Set, Union
import uuid

CONFIG_FILES = [
    "vitest.config.ts", "vitest.config.mts", "vitest.config.js", "vite.config.ts",
    "tsconfig.json", "package.json", "pyproject.toml", "pytest.ini",
]
_IMPORTER_CACHE: Dict[str, List[Path]] = {}
_IGNORED_DIRS = {".git", "node_modules", ".edge", ".next", "dist", "build", ".venv"}
_SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".py")


def clear_importer_cache(repo_root: Optional[Union[Path, str]] = None) -> None:
    """Clear cached candidate source/test index for one repo or all repos."""
    if repo_root is None:
        _IMPORTER_CACHE.clear()
        return
    _IMPORTER_CACHE.pop(str(Path(repo_root).resolve()), None)


def _get_cached_repo_files(repo_root: Path) -> List[Path]:
    key = str(repo_root.resolve())
    if key in _IMPORTER_CACHE:
        return [p for p in _IMPORTER_CACHE[key] if p.exists()]
    files = [p for p in repo_root.rglob("*") if p.is_file() and p.suffix in _SOURCE_EXTS and not any(d in p.parts for d in _IGNORED_DIRS)]
    _IMPORTER_CACHE[key] = files
    return files


def _build_import_tokens(target_rel: str) -> Set[str]:
    tokens = {Path(target_rel).stem, target_rel}
    if target_rel.endswith(_SOURCE_EXTS):
        no_ext = target_rel.rsplit(".", 1)[0]
        tokens.add(no_ext)
        if no_ext.startswith("src/"):
            tokens.update(("@/" + no_ext[4:], no_ext[4:]))
    return tokens


def _find_all_importers(repo_root: Path, target_rel_path: str) -> Set[Path]:
    target_rel = Path(target_rel_path).as_posix()
    tokens, resolved_root = _build_import_tokens(target_rel), repo_root.resolve()
    importers: Set[Path] = set()
    for p in _get_cached_repo_files(repo_root):
        try:
            rel = p.resolve().relative_to(resolved_root).as_posix()
            if rel != target_rel and any(tok in p.read_text(encoding="utf-8", errors="ignore") for tok in tokens):
                importers.add(p)
        except Exception:
            continue
    return importers


def _copy_profile_configs(repo: Path, overlay: Path) -> None:
    from tools.common.profiles import has_profile_capability, resolve_active_profiles

    prof = resolve_active_profiles(repo)
    ts_active = prof.source not in ("explicit", "explicit_none") or has_profile_capability(prof, "typescript")
    cfg_list = CONFIG_FILES if ts_active else ["package.json", "pyproject.toml", "pytest.ini"]
    for cfg in cfg_list:
        cfg_path = repo / cfg
        if cfg_path.is_file():
            shutil.copy2(cfg_path, overlay / cfg)


def _safe_symlink(src: Path, dst: Path, is_dir: bool) -> None:
    if dst.exists():
        return
    try:
        os.symlink(src, dst, target_is_directory=is_dir)
    except Exception:
        pass


def _populate_dir(repo: Path, overlay: Path, current_rel: Path, required_dirs: Set[str]) -> None:
    (overlay / current_rel).mkdir(parents=True, exist_ok=True)
    for entry in (repo / current_rel).iterdir():
        if entry.name in (".git", ".edge") or entry.name in CONFIG_FILES:
            continue
        entry_rel = (current_rel / entry.name) if str(current_rel) != "." else Path(entry.name)
        entry_posix = entry_rel.as_posix()
        if entry.is_dir() and entry_posix in required_dirs:
            _populate_dir(repo, overlay, entry_rel, required_dirs)
        elif entry.is_dir() or entry.is_file():
            _safe_symlink(entry, overlay / entry_posix, entry.is_dir())


def _collect_required_dirs(copied_rel_files: Set[str]) -> Set[str]:
    required_dirs: Set[str] = set()
    for rel_f in copied_rel_files:
        p = Path(rel_f).parent
        while p != Path("."):
            required_dirs.add(p.as_posix())
            p = p.parent
    return required_dirs


def create_worker_overlay(
    repo_root: Union[Path, str], target_rel_path: str, mutated_bytes: bytes, work_root: Optional[Union[Path, str]] = None,
) -> Path:
    """Create isolated worker overlay with configs, mutated target, importers, and symlinks."""
    repo = Path(repo_root).resolve()
    target_norm = Path(target_rel_path).as_posix()
    base_work = Path(work_root).resolve() if work_root else (repo / ".edge" / "mutation-workers")
    overlay = base_work / f"worker-{uuid.uuid4().hex[:8]}"
    overlay.mkdir(parents=True, exist_ok=True)
    _copy_profile_configs(repo, overlay)
    mut_dest = overlay / target_norm
    mut_dest.parent.mkdir(parents=True, exist_ok=True)
    mut_dest.write_bytes(mutated_bytes)
    importers = _find_all_importers(repo, target_norm)
    for imp in importers:
        dest = overlay / imp.relative_to(repo).as_posix()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(imp, dest)
    copied = {target_norm} | {imp.relative_to(repo).as_posix() for imp in importers}
    _populate_dir(repo, overlay, Path("."), _collect_required_dirs(copied))
    return overlay


def _remove_entry(path: Path, is_dir: bool) -> None:
    try:
        path.rmdir() if (is_dir and not path.is_symlink()) else path.unlink()
    except Exception:
        pass


def cleanup_worker_overlay(overlay_path: Union[Path, str]) -> None:
    """Safely remove worker overlay without following symlinks into the real repo."""
    overlay = Path(overlay_path)
    if not overlay.exists() and not overlay.is_symlink():
        return
    for root_str, dirs, files in os.walk(overlay, topdown=False, followlinks=False):
        root_p = Path(root_str)
        for f in files:
            _remove_entry(root_p / f, False)
        for d in dirs:
            _remove_entry(root_p / d, True)
    _remove_entry(overlay, True)
