"""
Path normalization and translation utilities for Edge Tools.
Seamlessly bridges Windows, WSL, macOS, and Linux environments.
"""

import os
from pathlib import Path
import re
from typing import Tuple, Union

from . import env as _env

WSL_DISTRO: str = _env.get_wsl_distro()
_MNT_DRIVE_RE = re.compile(r"^/mnt/([a-zA-Z])(?:/(.*))?$")
_WSL_UNC_RE = re.compile(r"^//wsl(?:\.localhost|\$)/[^/]+(/.*)?$", re.IGNORECASE)


def _resolve_existing_or_first(candidates: Tuple[Path, ...], fallback: Path) -> Path:
    for cand in candidates:
        if cand.exists():
            return cand.resolve()
    return fallback


def _normalize_windows_target(raw_str: str, fallback: Path) -> Path:
    if raw_str.startswith("/home/"):
        distro = WSL_DISTRO or _env.get_wsl_distro()
        if not distro:
            return fallback
        wsl_unc = Path(rf"\\wsl.localhost\{distro}") / raw_str.lstrip("/")
        legacy_unc = Path(rf"\\wsl$\{distro}") / raw_str.lstrip("/")
        return _resolve_existing_or_first((wsl_unc, legacy_unc), wsl_unc)

    mnt_match = _MNT_DRIVE_RE.match(raw_str)
    if mnt_match:
        drive = mnt_match.group(1).upper()
        rest = mnt_match.group(2) or ""
        win_path = Path(f"{drive}:/{rest}")
        return win_path.resolve() if win_path.exists() else win_path

    return fallback.resolve()


def normalize_target_path(raw_path: Union[str, Path]) -> Path:
    """
    Normalizes an input path to a valid Path object.
    Translates WSL-style Linux paths (/home/...) into Windows UNC paths when running on Windows
    and a WSL distro is configured, and maps /mnt/<drive>/... across any drive letter.
    """
    p = raw_path if isinstance(raw_path, Path) else Path(raw_path)
    if p.exists():
        return p.resolve()
    if os.name == "nt":
        raw_str = str(raw_path).replace("\\", "/")
        return _normalize_windows_target(raw_str, p)
    return p.resolve()


def to_wsl_path(path: Union[str, Path]) -> str:
    """
    Converts a Windows path or UNC path into a clean WSL Linux path (/home/... or /mnt/<drive>/...).
    """
    p_str = str(path).replace("\\", "/")

    unc_match = _WSL_UNC_RE.match(p_str)
    if unc_match:
        return unc_match.group(1) or "/"

    if len(p_str) >= 2 and p_str[1] == ":" and p_str[0].isalpha():
        drive = p_str[0].lower()
        rest = p_str[2:].lstrip("/")
        return f"/mnt/{drive}/{rest}"

    if p_str.startswith("/"):
        return p_str

    return p_str


def is_wsl_path(path: Union[str, Path]) -> bool:
    """
    Determines if the path points to a WSL environment.
    """
    p_str = str(path).replace("\\", "/")
    if p_str.startswith("//wsl.localhost") or p_str.startswith("//wsl$"):
        return True
    if p_str.startswith("/home/"):
        return os.name == "nt" or _env.is_wsl()
    return False
