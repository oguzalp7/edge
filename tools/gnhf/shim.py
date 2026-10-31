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
    "/home/oguz/.local/bin/agy",
]


def _find_real_agy() -> str:
    """Finds the underlying host agy binary before PATH manipulation."""
    found = shutil.which("agy")
    if found:
        return found
    for loc in _KNOWN_AGY_LOCATIONS:
        if os.path.exists(loc):
            return loc
    return "/usr/local/bin/agy"


def _write_shim_script(shim_dir: Path, real_agy: str, model: str) -> Path:
    """Writes the wrapper script that injects --model if missing."""
    script_path = shim_dir / "agy"
    script_content = f"""#!/usr/bin/env bash
REAL_AGY="{real_agy}"

has_model=false
for arg in "$@"; do
  if [[ "$arg" == --model* ]] || [[ "$arg" == "-m" ]]; then
    has_model=true
    break
  fi
done

if [ "$has_model" = true ]; then
  exec "$REAL_AGY" "$@"
else
  exec "$REAL_AGY" --model "{model}" "$@"
fi
"""
    script_path.write_text(script_content, encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


@contextmanager
def create_agy_shim(model: str = "gemini-3.8-flash-medium") -> Generator[Path, None, None]:
    """
    Creates an ephemeral directory containing an executable 'agy' wrapper.
    Prepends this directory to PATH for child subprocesses.
    Guarantees clean teardown on exit.
    """
    real_agy = _find_real_agy()
    temp_dir_str = tempfile.mkdtemp(prefix="edge-gnhf-shim-")
    temp_dir = Path(temp_dir_str)
    orig_path = os.environ.get("PATH", "")

    try:
        _write_shim_script(temp_dir, real_agy, model)
        os.environ["PATH"] = f"{temp_dir}{os.pathsep}{orig_path}" if orig_path else str(temp_dir)
        yield temp_dir
    finally:
        os.environ["PATH"] = orig_path
        shutil.rmtree(temp_dir, ignore_errors=True)
