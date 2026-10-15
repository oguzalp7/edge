"""
Edge Brigade: Michelin Station & Deterministic State Machine Engine
Inspired by Lauren Tan's (Poteto) Brigade de Cuisine (pstack)
and Dexter Horthy's 12-Factor Agents (Factor 8: Own Your Control Flow).
"""

from .models import StationRole, BrigadeState, CycleState, Ticket
from .fsm import BrigadeFSM
from .stations import StationRegistry

__all__ = ["StationRole", "BrigadeState", "CycleState", "Ticket", "BrigadeFSM", "StationRegistry"]
