import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.mutator.sites_py import _discover_python_sdl_sites, _discover_python_sites_fallback


def test_python_sdl_and_fallback_operators() -> None:
    src = b"def check(x):\n    if x == 1:\n        return True\n    return False\n"
    sdl = _discover_python_sdl_sites(src, "mod.py")
    ops = _discover_python_sites_fallback(src, "mod.py")
    assert any(s.original == "==" for s in ops)
    assert isinstance(sdl, list)
