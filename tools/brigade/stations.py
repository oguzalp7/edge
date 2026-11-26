"""
Station Registry & Dispatcher for Edge Brigade.
Manages persistent station worker registrations (conversation_ids)
and prepares hermetic, deterministic prompt payloads for each station.
"""

import importlib
from pathlib import Path
from typing import Any, List, Optional, Tuple

from tools.brigade.models import ReviewFinding, Ticket
from tools.brigade.station_dispatch import _GENERIC_DOMAINS, build_swarm_dispatch_directive, resolve_default_station_model
from tools.brigade.station_prompts_coder import build_coder_polish_prompt, build_coder_prompt
from tools.brigade.station_prompts_plan import build_researcher_prompt, build_seam_architect_prompt, build_seam_prompt, build_spec_writer_prompt
from tools.brigade.station_prompts_qa import build_qa_prompt
from tools.brigade.station_prompts_review import build_examiner_prompt, build_polish_prompt
from tools.brigade.station_prompts_surgeon import build_surgeon_prompt
from tools.brigade.station_qa_params import _build_qa_assertions, _build_qa_lavish_section, _clean_path_stem, _clean_slug, _resolve_qa_lavish, _resolve_qa_prompt_params, _resolve_qa_scenario, _resolve_qa_slug, _resolve_ticket_slug, _strip_branch_prefix
from tools.brigade.station_roster import StationRosterMixin
from tools.brigade.station_rubric import _collect_nav_paths, _inject_nav_block, _read_file_candidates, _with_navigation_context, load_station_rubric

__all__ = ["StationRegistry", "build_swarm_dispatch_directive", "resolve_default_station_model"]


class StationRegistry(StationRosterMixin):
    """Facade registry combining stateful roster storage with rubric and prompt builders."""

    _read_file_candidates = staticmethod(_read_file_candidates)
    load_station_rubric = staticmethod(load_station_rubric)
    _collect_nav_paths = staticmethod(_collect_nav_paths)
    _inject_nav_block = staticmethod(_inject_nav_block)
    _with_navigation_context = staticmethod(_with_navigation_context)
    build_surgeon_prompt = staticmethod(build_surgeon_prompt)
    build_spec_writer_prompt = staticmethod(build_spec_writer_prompt)
    build_researcher_prompt = staticmethod(build_researcher_prompt)
    build_seam_architect_prompt = staticmethod(build_seam_architect_prompt)
    build_seam_prompt = staticmethod(build_seam_prompt)
    build_coder_prompt = staticmethod(build_coder_prompt)
    build_examiner_prompt = staticmethod(build_examiner_prompt)
    build_polish_prompt = staticmethod(build_polish_prompt)
    build_coder_polish_prompt = staticmethod(build_coder_polish_prompt)
    _resolve_qa_scenario = staticmethod(_resolve_qa_scenario)
    _resolve_qa_lavish = staticmethod(_resolve_qa_lavish)
    _clean_slug = staticmethod(_clean_slug)
    _strip_branch_prefix = staticmethod(_strip_branch_prefix)
    _clean_path_stem = staticmethod(_clean_path_stem)
    _resolve_ticket_slug = staticmethod(_resolve_ticket_slug)
    _resolve_qa_slug = staticmethod(_resolve_qa_slug)
    _resolve_qa_prompt_params = staticmethod(_resolve_qa_prompt_params)
    _build_qa_lavish_section = staticmethod(_build_qa_lavish_section)
    _build_qa_assertions = staticmethod(_build_qa_assertions)
    build_qa_prompt = staticmethod(build_qa_prompt)


_LAZY_SUBMODULES: Tuple[str, ...] = ("station_dispatch", "station_rubric", "station_roster", "station_qa_params")


def __getattr__(name: str) -> Any:
    for sub in _LAZY_SUBMODULES:
        mod = importlib.import_module(f"tools.brigade.{sub}")
        if name in mod.__dict__:
            return mod.__dict__[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
