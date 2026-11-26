"""Submodule: models."""

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class DiscoveredRoute:
    route_pattern: str
    concrete_url_path: str
    source_file: str
    framework: str
    is_dynamic: bool
    requires_auth: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiscoveredRoute":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class RouteSmokeResult:
    route_pattern: str
    url: str
    source_file: str
    http_status: int
    final_url: str
    auth_redirected: bool
    console_errors: List[str] = field(default_factory=list)
    page_errors: List[str] = field(default_factory=list)
    failed_requests: List[str] = field(default_factory=list)
    navigable: bool = False
    ttfb_ms: int = 0
    settle_ms: int = 0
    heap_used_mb: float = 0.0
    dom_nodes: int = 0
    spinner_state: str = "none"
    perf_status: str = "PASS"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouteSmokeResult":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class SmokeScanReport:
    base_url: str
    scanned_at: str
    total_routes: int
    passed_routes: int
    failed_routes: int
    all_navigable: bool
    total_console_errors: int = 0
    total_page_errors: int = 0
    results: List[RouteSmokeResult] = field(default_factory=list)
    triage_tickets_created: List[str] = field(default_factory=list)
    schema_version: str = "1.0.0"
    settle_budget_ms: int = 1500
    hard_settle_timeout_ms: int = 5000
    heap_budget_mb: float = 80.0
    slow_routes: int = 0
    stuck_routes: int = 0
    max_settle_ms: int = 0
    max_heap_mb: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["results"] = [r.to_dict() for r in self.results]
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SmokeScanReport":
        raw = dict(data)
        raw_results = raw.get("results") or []
        raw["results"] = [
            RouteSmokeResult.from_dict(r) if isinstance(r, dict) else r
            for r in raw_results
        ]
        valid = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**valid)
