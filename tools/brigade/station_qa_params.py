"""QA scenario, slug, Lavish contract, and assertion parameter builders."""

from pathlib import Path
from typing import List, Optional, Tuple

from tools.brigade.models import Ticket
from tools.brigade.station_dispatch import _GENERIC_DOMAINS

def _resolve_qa_scenario(user_scenario_en: str, ticket: Optional[Ticket]) -> str:
    if user_scenario_en:
        return user_scenario_en
    if ticket and ticket.description:
        return ticket.description
    return "E2E UI & user flow verification"


def _resolve_qa_lavish(lavish_path: Optional[str], ticket: Optional[Ticket]) -> Optional[str]:
    if lavish_path:
        return lavish_path
    if ticket:
        return getattr(ticket, "lavish_path", None)
    return None


def _clean_slug(val: Optional[str]) -> str:
    return (val or "").strip().lower().replace("_", "-")


def _strip_branch_prefix(branch: str) -> str:
    s = branch.strip()
    for prefix in ("feat/", "fix/", "refactor/", "hotfix/", "chore/", "ship/"):
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def _clean_path_stem(raw_path: Optional[str]) -> str:
    text = (raw_path or "").strip()
    if not text:
        return ""
    stem = Path(text.replace("\\", "/")).stem
    return _clean_slug(stem)


def _resolve_ticket_slug(ticket: Ticket) -> Optional[str]:
    spec_slug = _clean_path_stem(getattr(ticket, "spec_path", None))
    if spec_slug:
        return spec_slug
    if (ticket.branch_name or "").strip():
        branch_slug = _clean_slug(
            _strip_branch_prefix(ticket.branch_name)
        )
        if branch_slug:
            return branch_slug
    domain_slug = _clean_slug(ticket.domain)
    if domain_slug and domain_slug not in _GENERIC_DOMAINS:
        return domain_slug
    target_slug = _clean_path_stem(ticket.target_file)
    if target_slug:
        return target_slug
    if (ticket.ticket_id or "").strip():
        return _clean_slug(ticket.ticket_id)
    return None


def _resolve_qa_slug(
    scenario_slug: str = "qa_scenario",
    ticket: Optional[Ticket] = None,
) -> str:
    """
    Deterministically resolves the scenario slug used for proof receipt lookup.
    Priority:
    1. Explicit scenario_slug if not default 'qa_scenario'
    2. ticket.spec_path stem
    3. ticket.branch_name (prefixes stripped)
    4. Non-generic ticket.domain (excludes general/core/ui/feature)
    5. ticket.target_file stem
    6. ticket.ticket_id
    7. Fallback: 'qa_scenario'
    """
    clean_scenario = _clean_slug(scenario_slug)
    if clean_scenario and clean_scenario != "qa-scenario":
        return clean_scenario
    if ticket:
        tslug = _resolve_ticket_slug(ticket)
        if tslug:
            return tslug
    return "qa_scenario" 


def _resolve_qa_prompt_params(
    user_scenario_en: str,
    ticket: Optional[Ticket],
    lavish_path: Optional[str],
    scenario_slug: str,
) -> Tuple[str, Optional[str], str]:
    """Resolves scenario text, lavish prototype path, and scenario slug for QA prompt."""
    scenario = _resolve_qa_scenario(user_scenario_en, ticket)
    lavish = _resolve_qa_lavish(lavish_path, ticket)
    slug = _resolve_qa_slug(scenario_slug, ticket)
    return scenario, lavish, slug


def _build_qa_lavish_section(eff_lavish: Optional[str]) -> str:
    if not eff_lavish:
        return ""
    return f"""
LAVISH-TO-REALITY PARITY & TIER-1 CONSOLE/SMOKE GATE:
- Approved Lavish Prototype: {eff_lavish}
- Inspect {eff_lavish} prior to launching browser verification.
- Verify that every interactive control, state, button, and layout from the Lavish prototype exists in the live DOM.
- TIER-1 CONSOLE/SMOKE GATE: Zero tolerance for unhandled exceptions, console.error messages, React hydration failures, or unexpected 4xx/5xx network responses. Any occurrence fails the QA gate (CRITICAL).
"""


def _build_qa_assertions(assertions: Optional[List[str]], eff_lavish: Optional[str]) -> str:
    if assertions:
        return "\n".join(f"- {a}" for a in assertions)

    items = [
        "Target flow completes with expected UI transitions.",
        "Zero unhandled exceptions or console errors in devtools (Tier-1 Zero Tolerance).",
        "Network requests return status 200/expected HTTP responses.",
        "Visual state matches design expectations (screenshot captured).",
    ]
    if eff_lavish:
        items.insert(0, f"Full structural and visual parity verified against {eff_lavish}.")
    return "\n".join(f"- {a}" for a in items)
