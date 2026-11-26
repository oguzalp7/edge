"""
Safe spec archival helper for edge-drift (INV-DRIFT-ARCHIVE-SAFE).
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from tools.common.paths import normalize_target_path


def archive_ephemeral_spec(
    repo_path: Union[Path, str],
    spec_path: Union[Path, str],
) -> Optional[Path]:
    """
    Safely moves a temporary/completed slice spec file into <repo>/.edge/archive/specs/<filename>.
    Never archives files inside .edge/cache/.
    """
    norm_repo = normalize_target_path(repo_path)
    spec_file = Path(spec_path)
    if not spec_file.is_absolute():
        spec_file = norm_repo / spec_file
    if not spec_file.exists() or not spec_file.is_file():
        return None

    from tools.common.fs import resolve_target_repo_root

    resolved_spec = spec_file.resolve()
    cache_roots = [
        (norm_repo / ".edge" / "cache").resolve(),
        (resolve_target_repo_root(norm_repo) / ".edge" / "cache").resolve(),
    ]
    if any(resolved_spec == c or c in resolved_spec.parents for c in cache_roots):
        return None

    archive_dir = norm_repo / ".edge" / "archive" / "specs"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / spec_file.name
    if dest.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = archive_dir / f"{spec_file.stem}_{ts}{spec_file.suffix}"

    try:
        shutil.move(str(spec_file), str(dest))
        return dest
    except Exception:
        try:
            shutil.copy2(str(spec_file), str(dest))
            spec_file.unlink()
            return dest
        except Exception:
            return None
