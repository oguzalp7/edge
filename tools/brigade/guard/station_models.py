"""Station persistence dataclasses and envelope models (stdlib-only)."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

GREEN_HEAT_THRESHOLD: int = 45_000
YELLOW_HEAT_THRESHOLD: int = 75_000
_ENVELOPE_META_KEYS = ("version", "initializedAt", "sessions", "stations")


@dataclass
class TokenHeatRecord:
    tokens: int
    heat_zone: str
    last_calculated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {"tokens": self.tokens, "heatZone": self.heat_zone, "heat_zone": self.heat_zone, "lastCalculatedAt": self.last_calculated_at}


TokenHeat = TokenHeatRecord


@dataclass
class StationRecord:
    conversation_id: str
    role: str
    canonical_role: str
    parent_conversation_id: str
    status: str = "IDLE"
    model: str = "flash"
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_active_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    token_heat: TokenHeatRecord = field(default_factory=lambda: TokenHeatRecord(tokens=0, heat_zone="GREEN"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversationId": self.conversation_id, "role": self.canonical_role or self.role,
            "canonicalRole": self.canonical_role, "parentConversationId": self.parent_conversation_id,
            "status": self.status, "model": self.model, "registeredAt": self.registered_at,
            "lastActiveAt": self.last_active_at, "tokenHeat": self.token_heat.to_dict(),
        }


class StationStoreEnvelope(dict):
    """Dict envelope supporting legacy flat cid indexing and structured v1 metadata."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        legacy_keys = [k for k in list(self.keys()) if k not in _ENVELOPE_META_KEYS]
        for k, default in (("stations", {}), ("sessions", {}), ("version", "1.0")):
            if k not in self:
                super().__setitem__(k, default)
        if "initializedAt" not in self:
            super().__setitem__("initializedAt", datetime.now(timezone.utc).isoformat())
        stations = super().__getitem__("stations")
        for k in legacy_keys:
            stations[k] = super().__getitem__(k)
            super().__delitem__(k)

    def __getitem__(self, key: str) -> Any:
        if key not in _ENVELOPE_META_KEYS and key in super().__getitem__("stations"):
            return super().__getitem__("stations")[key]
        return super().__getitem__(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key in _ENVELOPE_META_KEYS:
            super().__setitem__(key, value)
        else:
            super().setdefault("stations", {})[key] = value

    def __contains__(self, key: object) -> bool:
        return super().__contains__(key) or key in super().get("stations", {})

    def get(self, key: str, default: Any = None) -> Any:
        if key not in _ENVELOPE_META_KEYS and key in super().get("stations", {}):
            return super().get("stations", {})[key]
        return super().get(key, default)

    def __delitem__(self, key: str) -> None:
        stations = super().get("stations", {})
        if key in stations:
            del stations[key]
            return
        super().__delitem__(key)

    def get_stations(self) -> Dict[str, Dict[str, Any]]:
        return super().get("stations", {})
