#!/usr/bin/env python3
"""
Cross-OS runtime environment, configuration, and split-brain path resolution.
@intent Provide stdlib-only OS detection, MachineConfig persistence, and host path resolution
@concepts cross-os-runtime-env, atomic-state-store
@invariants [INV-BRIGADE-CROSS-OS-ENV], [INV-BRIGADE-ATOMIC-STATE]
"""

from dataclasses import dataclass
import glob
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

OsMode = Literal["windows", "wsl", "macos", "linux"]

_WINDOWS_SYSTEM_USERS = frozenset({"public", "default", "all users", "default user"})
_MNT_DRIVE_RE = re.compile(r"^/mnt/([a-zA-Z])(?:/(.*))?$")
_WIN_DRIVE_RE = re.compile(r"^([a-zA-Z]):(?:/(.*))?$")
_WSL_UNC_RE = re.compile(r"^//wsl(?:\.localhost|\$)/[^/]+(/.*)?$", re.IGNORECASE)


@dataclass
class MachineConfig:
    """User-level machine portability configuration stored at ~/.edge/machine.json."""

    schema_version: str = "1.0"
    os_mode: str = ""
    hooks_mode: str = "session"
    install_profile: str = "core"
    wsl_distro: str = ""
    persona_tone: str = "technical"
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "os_mode": self.os_mode,
            "hooks_mode": self.hooks_mode,
            "install_profile": self.install_profile,
            "wsl_distro": self.wsl_distro,
            "persona_tone": self.persona_tone,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "MachineConfig":
        if not isinstance(data, dict):
            return cls()
        defaults = cls()
        return cls(
            schema_version=str(data.get("schema_version") or defaults.schema_version),
            os_mode=str(data.get("os_mode") if data.get("os_mode") is not None else defaults.os_mode),
            hooks_mode=str(data.get("hooks_mode") or defaults.hooks_mode),
            install_profile=str(data.get("install_profile") or defaults.install_profile),
            wsl_distro=str(data.get("wsl_distro") if data.get("wsl_distro") is not None else defaults.wsl_distro),
            persona_tone=str(data.get("persona_tone") or defaults.persona_tone),
            updated_at=str(data.get("updated_at") if data.get("updated_at") is not None else defaults.updated_at),
        )


def is_wsl() -> bool:
    """Return True when executing inside Windows Subsystem for Linux."""
    if os.name != "posix":
        return False
    if os.environ.get("WSL_DISTRO_NAME", "").strip():
        return True
    try:
        proc_ver = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return "microsoft" in proc_ver or "wsl" in proc_ver


def detect_os_mode() -> OsMode:
    """Detect runtime OS mode without spawning subprocesses."""
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if is_wsl():
        return "wsl"
    return "linux"


def get_plugin_root() -> Path:
    """Resolve plugin root from env overrides or package location."""
    for env_key in ("PLUGIN_ROOT", "EDGE_PLUGIN_ROOT"):
        val = os.environ.get(env_key, "").strip()
        if val:
            return Path(val)
    return Path(__file__).resolve().parents[2]


def get_edge_home() -> Path:
    """Resolve ~/.edge home directory honoring EDGE_HOME override."""
    val = os.environ.get("EDGE_HOME", "").strip()
    if val:
        return Path(val)
    return Path.home() / ".edge"


def get_machine_config_path() -> Path:
    """Return canonical path to machine.json."""
    return get_edge_home() / "machine.json"


def _atomic_write_text(target: Path, content: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def load_machine_config(path: Optional[Path] = None) -> MachineConfig:
    """Load MachineConfig safely, falling back to defaults on missing or invalid JSON."""
    cfg_path = path or get_machine_config_path()
    try:
        raw = cfg_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except Exception:
        return MachineConfig()
    return MachineConfig.from_dict(parsed)


def save_machine_config(config: MachineConfig, path: Optional[Path] = None) -> Path:
    """Persist MachineConfig atomically to disk."""
    cfg_path = path or get_machine_config_path()
    payload = json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n"
    return _atomic_write_text(cfg_path, payload)


def cache_python_executable(exe_path: Optional[str] = None) -> None:
    """Cache resolved Python executable path for fast Windows/Unix hook startup."""
    target_exe = (exe_path or sys.executable or "").strip()
    if not target_exe:
        return
    plugin_data = os.environ.get("PLUGIN_DATA", "").strip()
    if plugin_data:
        _atomic_write_text(Path(plugin_data) / "python_exe.txt", target_exe + "\n")
    _atomic_write_text(get_edge_home() / "python_exe.txt", target_exe + "\n")


def get_wsl_distro() -> str:
    """Resolve optional WSL distro name without hardcoded fallbacks."""
    env_distro = os.environ.get("EDGE_WSL_DISTRO", "").strip()
    if env_distro:
        return env_distro
    cfg_distro = load_machine_config().wsl_distro.strip()
    if cfg_distro:
        return cfg_distro
    return os.environ.get("WSL_DISTRO_NAME", "").strip()


def _windows_host_antigravity_from_userprofile() -> Optional[Path]:
    up = os.environ.get("USERPROFILE", "").strip()
    if not up:
        return None
    norm = up.replace("\\", "/")
    match = _WIN_DRIVE_RE.match(norm)
    if not match:
        return None
    drive = match.group(1).lower()
    rest = (match.group(2) or "").lstrip("/")
    cand = Path(f"/mnt/{drive}/{rest}") / ".gemini" / "antigravity"
    if cand.is_dir() or cand.parent.is_dir():
        return cand
    return None


def _scan_windows_host_antigravity_dirs() -> Optional[Path]:
    matches = glob.glob("/mnt/[a-z]/Users/*/.gemini/antigravity")
    ranked: List[Tuple[int, int, str, Path]] = []
    for raw in matches:
        cand = Path(raw)
        user_dir = cand.parents[1].name.lower()
        if user_dir in _WINDOWS_SYSTEM_USERS:
            continue
        has_stations = 1 if (cand / "edge_active_stations.json").is_file() else 0
        has_brain = 1 if (cand / "brain").is_dir() else 0
        ranked.append((-has_stations, -has_brain, str(cand), cand))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return ranked[0][3]


def get_antigravity_data_dir() -> Path:
    """Resolve shared Antigravity data dir, preventing Windows/WSL split-brain."""
    explicit = os.environ.get("EDGE_ANTIGRAVITY_DIR", "").strip()
    if explicit:
        return Path(explicit)
    if is_wsl():
        host_dir = _windows_host_antigravity_from_userprofile()
        if host_dir is not None:
            return host_dir
        scanned_dir = _scan_windows_host_antigravity_dirs()
        if scanned_dir is not None:
            return scanned_dir
    return Path.home() / ".gemini" / "antigravity"


def get_brain_dir() -> Path:
    """Resolve Antigravity brain directory."""
    explicit = os.environ.get("GEMINI_BRAIN_ROOT", "").strip()
    if explicit:
        return Path(explicit)
    return get_antigravity_data_dir() / "brain"


def get_active_stations_path() -> Path:
    """Resolve canonical active stations registry path."""
    explicit = os.environ.get("EDGE_ACTIVE_STATIONS_FILE", "").strip()
    if explicit:
        return Path(explicit)
    return get_antigravity_data_dir() / "edge_active_stations.json"


def get_active_sessions_dir() -> Path:
    """Resolve active sessions marker directory co-located with active stations file."""
    explicit = os.environ.get("EDGE_ACTIVE_SESSIONS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    return get_antigravity_data_dir() / "edge_active_sessions"


def _resolve_windows_path(norm: str) -> Path:
    mnt_match = _MNT_DRIVE_RE.match(norm)
    if mnt_match:
        drive = mnt_match.group(1).upper()
        rest = mnt_match.group(2) or ""
        return Path(f"{drive}:/{rest}")
    if _WSL_UNC_RE.match(norm):
        return Path(norm)
    if norm.startswith("/"):
        distro = get_wsl_distro()
        if distro:
            return Path(f"//wsl.localhost/{distro}/{norm.lstrip('/')}")
    return Path(norm)


def _resolve_wsl_path(norm: str) -> Path:
    unc_match = _WSL_UNC_RE.match(norm)
    if unc_match:
        return Path(unc_match.group(1) or "/")
    drive_match = _WIN_DRIVE_RE.match(norm)
    if drive_match:
        drive = drive_match.group(1).lower()
        rest = (drive_match.group(2) or "").lstrip("/")
        return Path(f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}")
    return Path(norm)


def resolve_host_path(raw_path: Union[str, Path]) -> Path:
    """Normalize a host/guest path into the current OS runtime representation."""
    if not raw_path:
        return Path("")
    text = str(raw_path).strip()
    if not text:
        return Path("")
    mode = detect_os_mode()
    if mode in ("macos", "linux"):
        return Path(raw_path)
    norm = text.replace("\\", "/")
    if mode == "windows":
        return _resolve_windows_path(norm)
    return _resolve_wsl_path(norm)
