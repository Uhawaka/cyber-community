"""Commit replayable coarse catch-up summaries."""

from __future__ import annotations

from engine.runtime.kernel.events import EventType, WorldEvent
from engine.runtime.simulation.coarse import coarse_delta
from engine.runtime.simulation.policy import SimulationPolicy
from engine.runtime.simulation.run import AutonomousRun
from engine.runtime.simulation.settlements import delta_summary


def append_coarse_summary(
    run: AutonomousRun,
    coarse_ticks: int,
    *,
    requested_ticks: int,
    detailed_ticks: int,
    start_tick: int,
    start_sequence: int,
    policy: SimulationPolicy,
) -> None:
    pre_hash = run.state.state_hash()
    cursor = len(run.events)
    coarse_from_tick = run.state.tick
    coarse_from_time = run.state.world_time
    hot_characters = policy.hot_characters(run.state)
    cold_characters = policy.cold_characters(run.state)
    summary_delta, settlements, assumptions = coarse_delta(
        run, coarse_ticks, policy.need_decay
    )
    run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=run.state.tick,
            event_type=EventType.COARSE_TICK_SUMMARY,
            actor_id=None,
            observers=hot_characters,
            delta=summary_delta,
            data={
                "requested_ticks": requested_ticks,
                "executed_ticks": detailed_ticks,
                "truncated_ticks": coarse_ticks,
                "coarse_ticks": coarse_ticks,
                "from_tick": start_tick,
                "to_tick": coarse_from_tick + coarse_ticks,
                "event_count": len(run.events) - start_sequence,
                "input_state_hash": pre_hash,
                "pre_state_hash": pre_hash,
                "world_hash": run.state.world_hash,
                "seed": run.state.seed,
                "deterministic_cursor": cursor,
                "seed_cursor": {
                    "seed": run.state.seed,
                    "cursor": cursor,
                },
                "time_range": {
                    "from_tick": coarse_from_tick,
                    "to_tick": coarse_from_tick + coarse_ticks,
                    "from_world_time": coarse_from_time,
                    "to_world_time": (
                        coarse_from_time + coarse_ticks
                    ),
                },
                "detailed_character_ids": hot_characters,
                "cold_character_ids": cold_characters,
                "structured_delta": delta_summary(summary_delta),
                "settlements": settlements,
                "assumptions": assumptions,
                "target_entity_id": run.state.world_id,
                "rule_basis": (
                    "bounded detailed catch-up followed by "
                    "replayable coarse settlement"
                ),
            },
            pre_state_hash=pre_hash,
            world_hash=run.state.world_hash,
            deterministic_cursor=cursor,
            target_entity_id=run.state.world_id,
            rule_basis=(
                "bounded detailed catch-up followed by "
                "replayable coarse settlement"
            ),
        )
    )
