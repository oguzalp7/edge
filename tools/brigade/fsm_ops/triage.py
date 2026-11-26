"""BrigadeFSM mixin: triage."""

from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Set
import json

from tools.brigade.flight_recorder import FlightRecorder
from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD, call_facade
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog


class FsmTriageMixin:
    """Mixin providing triage operations for BrigadeFSM."""

    def _select_triage_target(
        self, track: str, target_domain: Optional[str], whitelist: Optional[List[str]], blacklist: Optional[List[str]]
    ) -> Optional[Dict[str, Any]]:
        ledger_path = self.target_repo / ".edge" / "ledger" / f"{track}.json"
        if not ledger_path.exists():
            return None
        try:
            data = json.loads(ledger_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        open_items = [i for i in data.get("items", []) if i.get("status") == "OPEN"]
        if whitelist:
            wl = [w.lower().rstrip("s") for w in whitelist]
            open_items = [i for i in open_items if any(w in i.get("file_path", "").lower() or w in i.get("title", "").lower() for w in wl)]
        if blacklist:
            bl = [b.lower().rstrip("s") for b in blacklist]
            open_items = [i for i in open_items if not any(b in i.get("file_path", "").lower() or b in i.get("title", "").lower() for b in bl)]
        if not open_items:
            return None
        if target_domain:
            dn = target_domain.lower().rstrip("s")
            df = [i for i in open_items if dn in i.get("file_path", "").lower() or dn in i.get("title", "").lower()]
            open_items = df or open_items
        order = {"CRITICAL": 0, "WARNING": 1, "ADVISORY": 2}
        open_items.sort(key=lambda x: order.get(x.get("severity", "WARNING"), 99))
        return open_items[0]

    def _build_triage_constraints(self, prior_constraints: List[str]) -> List[str]:
        from tools.common.profiles import is_stack_gate_enabled, resolve_active_profiles

        profiles = resolve_active_profiles(self.target_repo)
        mig_enabled = profiles.source not in ("explicit", "explicit_none") or is_stack_gate_enabled(profiles, "migration_gate")
        mig_rule = (
            "MigrationGate Invariant: NEVER touch `src/db/schema/*` or `drizzle/` migrations."
            if mig_enabled
            else "MigrationGate Invariant: NEVER mutate database schema files or migration directories."
        )
        base_constraints = [
            mig_rule,
            "Layer Leakage Gate: Do not introduce direct DB calls (`db.select`, `db.insert`, `db.update`, `db.delete`, `db.transaction`, `db.query`) in action controllers (`after_leaks <= before_leaks`, 0 in new actions).",
            "Max CC Non-Regression: Modified production files must not regress max cyclomatic complexity (healthy ceiling CC <= 10 for clean/new files).",
            "Zero-Wrapper Left Behind: Do not create shallow 1-line pass-through services.",
        ]
        return base_constraints + [c for c in prior_constraints if c not in base_constraints]

    def triage_next_ticket(
        self, track: str = "core", target_domain: Optional[str] = None,
        whitelist: Optional[List[str]] = None, blacklist: Optional[List[str]] = None,
        transcript_path: Optional[Path] = None,
    ) -> Optional[Ticket]:
        """Inspects .edge/ledger/<track>.json and creates a discrete Ticket for the top OPEN finding."""
        if self.state.current_state == CycleState.PAUSED:
            print("⚠️ Cannot triage while state is PAUSED. Run 'brigade resume' first.")
            return None
        if transcript_path:
            zone, rec = self.get_heat_zone(self.calculate_token_estimate(transcript_path))
            if zone in (ContextHeatZone.YELLOW, ContextHeatZone.RED):
                print(f"⚠️ TRIAGE BLOCKED BY HEAT POLICY: {rec}")
                return None
        target = self._select_triage_target(track, target_domain, whitelist, blacklist)
        if not target:
            return None
        file_path = target.get("file_path", "")
        domain = Path(file_path).stem
        if domain.endswith((".test", ".spec")):
            domain = domain.split(".")[0]
        rule_id, line_num = target.get("rule_id", "RULE-GENERAL"), target.get("line_number", 1)
        ticket_id = Ticket.generate_id(track, domain, rule_id, line_num)
        branch_name = f"refactor/{track}-{domain}-{rule_id.lower().replace('rule-', '').replace('-', '')[:10]}"
        scaffolding = 25 if not (self.target_repo / "src" / "lib" / domain / "repository.ts").exists() else 0
        test_file = self.target_repo / "tests" / "unit" / domain / f"{domain}.test.ts"
        test_seam = f"npx vitest run tests/unit/{domain}/{domain}.test.ts" if test_file.exists() else "npm run test:unit"
        sloc_b, health_b = self.calculate_file_metrics(self.target_repo / file_path)
        recorder = call_facade("FlightRecorder", FlightRecorder)(self.target_repo, ticket_id)
        ticket = Ticket(
            ticket_id=ticket_id, track=track, domain=domain, rule_id=rule_id,
            severity=target.get("severity", "WARNING"), target_file=file_path,
            target_symbol=target.get("symbol"), line_number=line_num,
            fingerprint=target.get("fingerprint", ""), description=target.get("title", ""),
            suggested_fix=target.get("suggested_fix", ""), branch_name=branch_name,
            test_seam_command=test_seam, scaffolding_allowance=scaffolding,
            negative_constraints=self._build_triage_constraints(recorder.get_negative_constraints()),
            health_before=health_b, sloc_before=sloc_b,
            before_metrics=self._capture_before_metrics(target_file=file_path),
            surgeon_cid=self._resolve_station_cid("surgeon"),
        )
        self.state.active_ticket, self.state.active_branch, self.state.current_state = ticket, branch_name, CycleState.TRIAGE
        self.save()
        return ticket
