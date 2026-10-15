"""
Path normalization and translation utilities for Edge Tools.
Seamlessly bridges Windows and WSL (Ubuntu-24.04) environments.
"""

import os
from pathlib import Path
from typing import Union

WSL_DISTRO = "Ubuntu-24.04"
WSL_UNC_PREFIX = rf"\\wsl.localhost\{WSL_DISTRO}"
WSL_LEGACY_UNC_PREFIX = rf"\\wsl$\{WSL_DISTRO}"


def normalize_target_path(raw_path: Union[str, Path]) -> Path:
    """
    Normalizes an input path to a valid Path object.
    Translates WSL-style Linux paths (/home/...) into Windows UNC paths when running on Windows.
    """
    if isinstance(raw_path, Path):
        p = raw_path
    else:
        p = Path(raw_path)

    if p.exists():
        return p.resolve()

    raw_str = str(raw_path).replace("\\", "/")

    if os.name == "nt":
        # Handle WSL /home/... path on Windows
        if raw_str.startswith("/home/"):
            wsl_unc = Path(WSL_UNC_PREFIX) / raw_str.lstrip("/")
            if wsl_unc.exists():
                return wsl_unc.resolve()
            # Fallback legacy UNC
            legacy_unc = Path(WSL_LEGACY_UNC_PREFIX) / raw_str.lstrip("/")
            if legacy_unc.exists():
                return legacy_unc.resolve()
            return wsl_unc

        # Handle WSL /mnt/c/... path on Windows
        if raw_str.startswith("/mnt/c/"):
            win_path = Path("C:/" + raw_str[len("/mnt/c/"):])
            if win_path.exists():
                return win_path.resolve()
            return win_path

    return p.resolve()


def to_wsl_path(path: Union[str, Path]) -> str:
    """
    Converts a Windows path or UNC path into a clean WSL Linux path (/home/... or /mnt/c/...).
    """
    p_str = str(path).replace("\\", "/")

    # Check for \\wsl.localhost\Ubuntu-24.04\ or \\wsl$\Ubuntu-24.04\
    for prefix in [f"//wsl.localhost/{WSL_DISTRO}/", f"//wsl$/{WSL_DISTRO}/"]:
        if p_str.lower().startswith(prefix.lower()):
            rel = p_str[len(prefix):]
            return "/" + rel.lstrip("/")

    # Check for C:/ or c:/
    if len(p_str) >= 2 and p_str[1] == ":":
        drive = p_str[0].lower()
        rest = p_str[2:].lstrip("/")
        return f"/mnt/{drive}/{rest}"

    # Already a linux path
    if p_str.startswith("/"):
        return p_str

    return p_str


def is_wsl_path(path: Union[str, Path]) -> bool:
    """
    Determines if the path points to a WSL environment.
    """
    p_str = str(path).replace("\\", "/")
    return (
        p_str.startswith("//wsl.localhost")
        or p_str.startswith("//wsl$")
        or p_str.startswith("/home/")
    )
