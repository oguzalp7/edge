"""Persistent station roster state operations mixin."""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from tools.brigade.models import BrigadeState, Station, StationRole


class StationRosterMixin:
    """Provides stateful station registration and kitchen roster formatting."""

    def __init__(self, state: BrigadeState):
        self.state = state

    @property
    def stations(self) -> Dict[str, Station]:
        return self.state.stations

    @staticmethod
    def format_kitchen_roster(stations: Dict[str, Station]) -> str:
        """Renders a clean Markdown block listing registered stations and P2P handoff rules."""
        if not stations:
            return (
                "### 📋 ACTIVE KITCHEN ROSTER\n"
                "No persistent station workers currently registered.\n"
                "Register stations with: brigade register <repo> --role <role> --conversation-id <id>\n"
            )
        return StationRosterMixin._render_roster_table(stations)

    @staticmethod
    def _render_roster_table(stations: Dict[str, Station]) -> str:
        lines = [
            "### 📋 ACTIVE KITCHEN ROSTER",
            "| Role | Station Name | Conversation ID | Model | Status |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for role_slug, st in sorted(stations.items()):
            lines.append(StationRosterMixin._format_roster_row(st))
        lines.extend([
            "",
            "🤝 **PEER-TO-PEER HANDOFF RULES (Autonomous Kitchen Relay):**",
            "- **Subagent Mode (Pro):** Message station directly via `send_message(Recipient='<conversation_id>', Message='...')`.",
            "- **Swarm Mode (Ultra):** Wake sleeping worker on shared board via `@<role>` mention (e.g. `post_message(text='@coder Red tests passing. Begin surgery.')`).",
            "- `seam_architect` -> `coder`: Red tests passing -> advance to `SURGERY`, message `coder` / wake via `@coder`.",
            "- `coder`/`surgeon` -> `gate`: Verify passing -> advance to `GATE` (runs `tools/gate.py` & UI `diff_image.py`).",
            "- `gate` -> `qa_engineer` (if QA needed) or `examiner` (`REVIEW`).",
            "- `qa_engineer` -> `examiner`: Proof receipt verified -> advance to `REVIEW`, message `examiner` / wake via `@examiner`.",
            "- `examiner` -> `coder`/`surgeon` (`POLISH`) or `@orchestrator` (`STAGING` after `brigade seal-review`).",
            "- **Green-Zone Invariant:** Message `@orchestrator` ONLY upon reaching `STAGING` (`[READY_FOR_STAGING]`) or unresolvable `[ESCALATION]`!",
        ])
        return "\n".join(lines)

    @staticmethod
    def _format_roster_row(st: Station) -> str:
        name = st.name if st.name else f"{st.role.replace('_', ' ').title()} Station"
        cid = f"`{st.conversation_id}`" if st.conversation_id else "*none*"
        model = getattr(st, "model", None) or "flash"
        status = getattr(st, "status", None) or "IDLE"
        return f"| `{st.role}` | {name} | {cid} | `{model}` | {status} |"

    def register(
        self,
        role: StationRole,
        conversation_id: str,
        name: Optional[str] = None,
        model: str = "flash",
    ) -> Station:
        station_name = name or f"{role.value.replace('_', ' ').title()} Station"
        station = Station(
            role=role.value,
            conversation_id=conversation_id,
            name=station_name,
            status="IDLE",
            model=model or "flash",
            registered_at=datetime.now(timezone.utc).isoformat(),
            last_active_at=datetime.now(timezone.utc).isoformat(),
        )
        self.state.stations[role.value] = station
        self.state.updated_at = datetime.now(timezone.utc).isoformat()
        return station

    def unregister(self, role: StationRole) -> bool:
        if role.value in self.state.stations:
            del self.state.stations[role.value]
            self.state.updated_at = datetime.now(timezone.utc).isoformat()
            return True
        return False

    def get_station(self, role: StationRole) -> Optional[Station]:
        return self.state.stations.get(role.value)

    def mark_active(self, role: StationRole) -> None:
        station = self.get_station(role)
        if station:
            station.status = "BUSY"
            station.last_active_at = datetime.now(timezone.utc).isoformat()
            self.state.updated_at = datetime.now(timezone.utc).isoformat()

    def mark_idle(self, role: StationRole) -> None:
        station = self.get_station(role)
        if station:
            station.status = "IDLE"
            station.last_active_at = datetime.now(timezone.utc).isoformat()
            self.state.updated_at = datetime.now(timezone.utc).isoformat()
