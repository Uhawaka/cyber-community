"""Public autonomous simulation API."""

from engine.runtime.kernel.lifecycle import create_run, export_run, load_run
from engine.runtime.simulation.executor import MAX_CATCHUP_TICKS, run_catchup, run_ticks
from engine.runtime.simulation.observability import CausalTrace, TickReport, explain_event
from engine.runtime.simulation.planner import choose_attempt, opportunities_for
from engine.runtime.simulation.policy import SimulationPolicy
from engine.runtime.simulation.resolver import Resolver
from engine.runtime.simulation.run import AutonomousRun

__all__ = [
    "AutonomousRun", "CausalTrace", "MAX_CATCHUP_TICKS", "Resolver",
    "SimulationPolicy", "TickReport", "choose_attempt", "create_run",
    "explain_event", "export_run", "load_run", "opportunities_for",
    "run_catchup", "run_ticks",
]
