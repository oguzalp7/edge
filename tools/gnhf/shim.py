"""
Ephemeral agy wrapper shim and model quota protector.
"""

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, List


_KNOWN_AGY_LOCATIONS: List[str] = [
    "/usr/local/bin/agy",
    "~/.local/bin/agy",
]

_SHIM_BINARIES: List[str] = ["agy", "antigravity"]


def _find_real_agy() -> str:
    """Finds the underlying host agy binary before PATH manipulation."""
    found = shutil.which("agy")
    if found:
        return found
    home_agy = str(Path.home() / ".local" / "bin" / "agy")
    for loc in [home_agy, *_KNOWN_AGY_LOCATIONS]:
        expanded = os.path.expanduser(loc)
        if os.path.exists(expanded):
            return expanded
    return "/usr/local/bin/agy"


def _generate_shim_content(real_agy: str, model: str) -> str:
    return f"""#!/usr/bin/env bash
REAL_AGY="{real_agy}"
MODEL="{model}"

filtered_args=()
has_model=false

for arg in "$@"; do
  if [ "$arg" = "--verbose" ] || [ "$arg" = "-verbose" ]; then
    continue
  fi
  if [[ "$arg" == --model* ]] || [ "$arg" = "-m" ]; then
    has_model=true
  fi
  filtered_args+=("$arg")
done

if [ "$has_model" = true ]; then
  exec "$REAL_AGY" "${{filtered_args[@]}}"
else
  exec "$REAL_AGY" --model "$MODEL" "${{filtered_args[@]}}"
fi
"""


def _write_shim_scripts(shim_dir: Path, real_agy: str, model: str) -> None:
    """Writes the wrapper scripts for all binary candidates in the shim directory."""
    script_content = _generate_shim_content(real_agy, model)
    for bin_name in _SHIM_BINARIES:
        script_path = shim_dir / bin_name
        script_path.write_text(script_content, encoding="utf-8")
        script_path.chmod(0o755)


@contextmanager
def create_agy_shim(model: str = "gemini-3.8-flash-medium") -> Generator[Path, None, None]:
    """
    Creates an ephemeral directory containing executable 'agy' and 'antigravity' wrappers.
    Prepends this directory to PATH for child subprocesses.
    Guarantees clean teardown on exit.
    """
    real_agy = _find_real_agy()
    temp_dir_str = tempfile.mkdtemp(prefix="edge-gnhf-shim-")
    temp_dir = Path(temp_dir_str)
    orig_path = os.environ.get("PATH", "")

    try:
        _write_shim_scripts(temp_dir, real_agy, model)
        os.environ["PATH"] = f"{temp_dir}{os.pathsep}{orig_path}" if orig_path else str(temp_dir)
        yield temp_dir
    finally:
        os.environ["PATH"] = orig_path
        shutil.rmtree(temp_dir, ignore_errors=True)
