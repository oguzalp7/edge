"""
Worker Overlay Materialization and Leak-Free Cleanup.
Materializes isolated worker environments with Next.js @/ alias awareness,
physical build config copies, dependent test materialization, and safe symlinking.
"""

import os
import uuid
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set, Union


CONFIG_FILES = [
    "vitest.config.ts",
    "vitest.config.mts",
    "vitest.config.js",
    "vite.config.ts",
    "tsconfig.json",
    "package.json",
    "pyproject.toml",
    "pytest.ini",
]

_IMPORTER_CACHE: Dict[str, List[Path]] = {}
_IGNORED_DIRS = {".git", "node_modules", ".edge", ".next", "dist", "build", ".venv"}
_SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".py")


def clear_importer_cache(repo_root: Optional[Union[Path, str]] = None) -> None:
    """Clears the cached candidate source/test index for one repo or all repos."""
    if repo_root is None:
        _IMPORTER_CACHE.clear()
        return
    _IMPORTER_CACHE.pop(str(Path(repo_root).resolve()), None)


def _get_cached_repo_files(repo_root: Path) -> List[Path]:
    key = str(repo_root.resolve())
    cached = _IMPORTER_CACHE.get(key)
    if cached is not None:
        return [p for p in cached if p.exists()]
    files: List[Path] = []
    for p in repo_root.rglob("*"):
        if not p.is_file() or p.suffix not in _SOURCE_EXTS:
            continue
        if any(ign in p.parts for ign in _IGNORED_DIRS):
            continue
        files.append(p)
    _IMPORTER_CACHE[key] = files
    return files


def _build_import_tokens(target_rel: str) -> Set[str]:
    tokens = {Path(target_rel).stem, target_rel}
    if target_rel.endswith(_SOURCE_EXTS):
        no_ext = target_rel.rsplit(".", 1)[0]
        tokens.add(no_ext)
        if no_ext.startswith("src/"):
            tokens.add("@/" + no_ext[4:])
            tokens.add(no_ext[4:])
    return tokens


def _find_all_importers(repo_root: Path, target_rel_path: str) -> Set[Path]:
    target_rel = Path(target_rel_path).as_posix()
    tokens = _build_import_tokens(target_rel)
    resolved_root = repo_root.resolve()
    importers: Set[Path] = set()

    for p in _get_cached_repo_files(repo_root):
        try:
            rel = p.resolve().relative_to(resolved_root).as_posix()
        except ValueError:
            continue
        if rel == target_rel:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            if any(tok in content for tok in tokens):
                importers.add(p)
        except Exception:
            continue
    return importers


def create_worker_overlay(
    repo_root: Union[Path, str],
    target_rel_path: str,
    mutated_bytes: bytes,
    work_root: Optional[Union[Path, str]] = None
) -> Path:
    """
    Creates an isolated worker overlay directory containing:
    1. Physical copies of test and build configs.
    2. The mutated target file at target_rel_path.
    3. Materialized copies of all tests and modules that import target_rel_path.
    4. Safe symlinks for untouched directories and assets.
    """
    repo = Path(repo_root).resolve()
    target_norm = Path(target_rel_path).as_posix()

    if work_root:
        base_work = Path(work_root).resolve()
    else:
        base_work = repo / ".edge" / "mutation-workers"

    base_work.mkdir(parents=True, exist_ok=True)
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    overlay = base_work / worker_id
    overlay.mkdir(parents=True, exist_ok=True)

    # 1. Physical copy of build and test configs
    for cfg in CONFIG_FILES:
        cfg_path = repo / cfg
        if cfg_path.is_file():
            shutil.copy2(cfg_path, overlay / cfg)

    # 2. Write mutated target file
    mut_dest = overlay / target_norm
    mut_dest.parent.mkdir(parents=True, exist_ok=True)
    mut_dest.write_bytes(mutated_bytes)

    # 3. Recursively find and materialize dependent importers
    importers = _find_all_importers(repo, target_norm)
    for imp in importers:
        imp_rel = imp.relative_to(repo).as_posix()
        dest = overlay / imp_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(imp, dest)

    # 4. Populate remaining file structure using symlinks
    copied_rel_files = {target_norm} | {imp.relative_to(repo).as_posix() for imp in importers}
    required_dirs = set()
    for rel_f in copied_rel_files:
        p = Path(rel_f).parent
        while p != Path("."):
            required_dirs.add(p.as_posix())
            p = p.parent

    def _populate_dir(current_rel: Path):
        source_dir = repo / current_rel
        target_dir = overlay / current_rel
        target_dir.mkdir(parents=True, exist_ok=True)

        for entry in source_dir.iterdir():
            if entry.name in (".git", ".edge") or entry.name in CONFIG_FILES:
                continue

            entry_rel = (current_rel / entry.name) if str(current_rel) != "." else Path(entry.name)
            entry_rel_posix = entry_rel.as_posix()

            if entry.is_dir():
                if entry_rel_posix in required_dirs:
                    _populate_dir(entry_rel)
                else:
                    dest_link = overlay / entry_rel_posix
                    if not dest_link.exists():
                        try:
                            os.symlink(entry, dest_link, target_is_directory=True)
                        except Exception:
                            pass
            elif entry.is_file():
                dest_file = overlay / entry_rel_posix
                if not dest_file.exists():
                    try:
                        os.symlink(entry, dest_file)
                    except Exception:
                        pass

    _populate_dir(Path("."))
    return overlay


def cleanup_worker_overlay(overlay_path: Union[Path, str]) -> None:
    """
    Safely tears down the worker overlay without traversing symlinks into the real repository.
    Unlinks directory and file symlinks directly, then deletes copied files and empty directories.
    """
    overlay = Path(overlay_path)
    if not overlay.exists() and not overlay.is_symlink():
        return

    for root, dirs, files in os.walk(overlay, topdown=False, followlinks=False):
        for f in files:
            f_path = Path(root) / f
            try:
                f_path.unlink()
            except Exception:
                pass
        for d in dirs:
            d_path = Path(root) / d
            try:
                if d_path.is_symlink():
                    d_path.unlink()
                else:
                    d_path.rmdir()
            except Exception:
                pass

    try:
        overlay.rmdir()
    except Exception:
        pass
