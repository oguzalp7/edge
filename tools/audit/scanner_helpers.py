import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set


def clean_test_stem(raw_stem: str) -> str:
    """Strips test suffixes and leading test_ prefix from a file stem."""
    clean_stem = raw_stem.lower()
    for suffix in (".test", ".spec", "_test"):
        if clean_stem.endswith(suffix):
            clean_stem = clean_stem[: -len(suffix)]
    if clean_stem.startswith("test_"):
        clean_stem = clean_stem[5:]
    return clean_stem


def index_test_file(
    test_index: Dict[str, List[str]],
    filepath: Path,
    root: Path,
    generic_stems: Set[str],
) -> None:
    """Registers stem and parent-dir lookup keys for a single test file."""
    lower_stem = filepath.stem.lower()
    clean_stem = clean_test_stem(filepath.stem)
    try:
        rel_p = str(filepath.relative_to(root))
    except ValueError:
        rel_p = str(filepath)
    parent_dir = filepath.parent.name.lower()

    if clean_stem not in generic_stems:
        test_index[clean_stem].append(rel_p)
        test_index[f"domain:{clean_stem}"].append(rel_p)
    if lower_stem not in generic_stems:
        test_index[lower_stem].append(rel_p)
    test_index[f"{parent_dir}/{clean_stem}"].append(rel_p)
    test_index[f"{parent_dir}/{lower_stem}"].append(rel_p)


def index_test_dir(
    test_index: Dict[str, List[str]],
    scan_target: Path,
    root: Path,
    excludes: Set[str],
    ext_map: Dict[str, Any],
    generic_stems: Set[str],
) -> None:
    """Walks a single candidate test directory and populates test_index."""
    if not scan_target.exists():
        return
    for filepath in iter_unignored_files(scan_target, excludes):
        adapter = ext_map.get(filepath.suffix.lower())
        if adapter and adapter.is_test_file(filepath):
            index_test_file(test_index, filepath, root, generic_stems)


def iter_unignored_files(root_dir: Path, excludes: Set[str]) -> Iterator[Path]:
    """Walks root_dir yielding files while pruning excluded and hidden dirs."""
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [
            d for d in dirnames if d not in excludes and not d.startswith(".")
        ]
        for filename in filenames:
            yield Path(dirpath) / filename


def resolve_scoped_path(
    file_entry: str, root: Path, target_dir: Path
) -> Optional[Path]:
    """Resolves a scoped file entry against workspace root or target_dir."""
    p = Path(file_entry)
    if p.is_absolute():
        resolved_p = p.resolve()
    else:
        resolved_p = (root / p).resolve()
        if not resolved_p.exists():
            resolved_p = (target_dir / p).resolve()
    return resolved_p if resolved_p.is_file() else None


def read_text_safely(filepath: Path) -> Optional[str]:
    """Reads UTF-8 text from filepath, returning None on read failure."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None
