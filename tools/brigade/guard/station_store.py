"""Persistent active station store and atomic JSON storage (stdlib-only)."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, Optional, Tuple, Union

from tools.brigade.guard.role_detection import normalize_role
from tools.brigade.guard.station_models import StationRecord, StationStoreEnvelope, TokenHeatRecord


def _normalize_envelope_payload(envelope: Any) -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    if isinstance(envelope, StationStoreEnvelope):
        return {"version": envelope.get("version", "1.0"), "initializedAt": envelope.get("initializedAt", now_iso), "sessions": envelope.get("sessions", {}), "stations": envelope.get_stations()}
    if isinstance(envelope, dict) and ("version" in envelope or "stations" in envelope):
        return {"version": envelope.get("version", "1.0"), "initializedAt": envelope.get("initializedAt", now_iso), "sessions": envelope.get("sessions", {}), "stations": envelope.get("stations", {})}
    stations = dict(envelope) if isinstance(envelope, dict) else {}
    return {"version": "1.0", "initializedAt": now_iso, "sessions": {}, "stations": stations}


class StationStore:
    """Atomic JSON backing store for persistent Brigade stations."""

    def __init__(self, store_path: Path):
        self.store_path = Path(store_path)

    def load(self) -> StationStoreEnvelope:
        if not self.store_path.exists():
            env = StationStoreEnvelope()
            self.save(env)
            return env
        try:
            raw_data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except Exception:
            raw_data = {}
        raw_dict = raw_data if isinstance(raw_data, dict) else {}
        env = StationStoreEnvelope(raw_dict)
        if "version" not in raw_dict and "stations" not in raw_dict:
            self.save(env)
        return env

    def save(self, envelope: Union[StationStoreEnvelope, Dict[str, Any]]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = _normalize_envelope_payload(envelope)
        temp_file = self.store_path.with_suffix(".tmp")
        temp_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_file.replace(self.store_path)

    def register(self, conversation_id: str, role: str, parent_cid: str = "", model: str = "flash") -> StationRecord:
        if not conversation_id:
            raise ValueError("conversation_id is required")
        canonical = normalize_role(role) or role.strip().upper()
        now_iso = datetime.now(timezone.utc).isoformat()
        record = StationRecord(conversation_id, role, canonical, parent_cid, model=model or "flash", registered_at=now_iso, last_active_at=now_iso)
        env = self.load()
        env.get_stations()[conversation_id] = record.to_dict()
        if parent_cid:
            sess = env.setdefault("sessions", {}).setdefault(parent_cid, {"parentConversationId": parent_cid, "registeredStations": [], "lastScannedAt": now_iso})
            reg = sess.setdefault("registeredStations", [])
            if conversation_id not in reg:
                reg.append(conversation_id)
            sess["lastScannedAt"] = now_iso
        self.save(env)
        return record

    def _set_status(self, conversation_id: str, status: str) -> None:
        env = self.load()
        stations = env.get_stations()
        if conversation_id in stations:
            stations[conversation_id]["status"] = status
            stations[conversation_id]["lastActiveAt"] = datetime.now(timezone.utc).isoformat()
            self.save(env)

    def mark_exhausted(self, conversation_id: str) -> None:
        self._set_status(conversation_id, "EXHAUSTED")

    def mark_rotated(self, conversation_id: str) -> None:
        self._set_status(conversation_id, "ROTATED")


def get_active_stations_path() -> Path:
    """Resolve the active stations JSON path via cross-OS env helper."""
    from tools.common import env as _edge_env

    return _edge_env.get_active_stations_path()


def effective_stations_file() -> Path:
    facade = sys.modules.get("tools.brigade.orchestrator_guard")
    if facade is not None and "ACTIVE_STATIONS_FILE" in facade.__dict__:
        val = facade.__dict__["ACTIVE_STATIONS_FILE"]
        if val is not None:
            return Path(val)
    if "ACTIVE_STATIONS_FILE" in globals():
        val = globals()["ACTIVE_STATIONS_FILE"]
        if val is not None:
            return Path(val)
    return get_active_stations_path()


def __getattr__(name: str) -> Any:
    if name == "ACTIVE_STATIONS_FILE":
        return get_active_stations_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def load_active_stations() -> StationStoreEnvelope:
    return StationStore(effective_stations_file()).load()


def save_active_stations(data: Union[StationStoreEnvelope, Dict[str, Any]]) -> None:
    StationStore(effective_stations_file()).save(data)


def register_station(conversation_id: str, role: str, parent_cid: str = "", model: str = "flash") -> Optional[StationRecord]:
    return StationStore(effective_stations_file()).register(conversation_id, role, parent_cid, model=model) if conversation_id else None


def find_active_station(role: str, parent_cid: str = "") -> Optional[Tuple[str, Dict[str, Any]]]:
    canonical = normalize_role(role) or role.strip().upper()
    data = load_active_stations()
    stations = data.get_stations() if isinstance(data, StationStoreEnvelope) else (data.get("stations") if isinstance(data, dict) and "stations" in data else data)
    for cid, info in stations.items():
        if not isinstance(info, dict):
            continue
        st_role = normalize_role(info.get("role", "") or info.get("canonicalRole", "")) or info.get("role", "").upper()
        if st_role == canonical and info.get("status", "IDLE") not in ("EXHAUSTED", "ROTATED", "TERMINATED"):
            if not parent_cid or info.get("parentConversationId") == parent_cid:
                return cid, info
    return None
