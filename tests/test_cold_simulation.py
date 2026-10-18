from pathlib import Path

from engine.application import (
    SimulationPolicy,
    create_run,
    export_run,
    load_run,
    run_catchup,
    run_ticks,
)
from engine.runtime import EventType, MemoryTier
from engine.world.package_compiler import compile_package


ROOT = Path(__file__).parents[1]


def _compiled():
    result = compile_package(ROOT / "worlds" / "echo-quay")
    assert result.compiled is not None
    return result.compiled


def test_catchup_commits_replayable_coarse_time_and_provenance(tmp_path):
    compiled = _compiled()
    policy = SimulationPolicy(
        max_catchup_ticks=2,
        hot_character_ids=("lin",),
        action_budget=2,
        opportunity_budget=6,
        incident_budget=1,
        memory_budget=1,
    )
    run = create_run(compiled, seed=71)
    report = run_catchup(run, 10, policy=policy)
    summaries = tuple(
        event
        for event in run.events
        if event.event_type is EventType.COARSE_TICK_SUMMARY
    )
    summary = summaries[0]

    assert report.executed_ticks == 4
    assert report.coarse_ticks == report.truncated_ticks == 6
    assert run.state.tick == 10
    assert [item.delta.advance_tick for item in summaries] == [4, 2]
    assert summary.data["input_state_hash"] == summary.pre_state_hash
    assert summary.data["seed_cursor"] == {
        "seed": 71,
        "cursor": summary.sequence,
    }
    assert summary.data["time_range"]["to_tick"] == 6
    assert summary.data["detailed_character_ids"] == ("lin",)
    assert set(summary.data["cold_character_ids"]) == {"wei"}
    assert summary.data["structured_delta"]["advance_tick"] == 4
    assert summary.data["assumptions"]
    phase = next(
        event
        for event in run.events
        if event.event_type is EventType.PHASE_SNAPSHOT
    )
    gate = next(
        event
        for event in run.events
        if event.event_type is EventType.GATE_OPENED
    )
    assert phase.tick == 6
    assert gate.tick == 8
    assert all(
        not (
            event.event_type is EventType.COARSE_TICK_SUMMARY
            and event.tick >= gate.tick
        )
        for event in run.events
    )
    assert run.replay() == run.state

    path = export_run(run, tmp_path / "events.jsonl")
    loaded = load_run(compiled, path)
    assert loaded.state == run.state
    assert (
        loaded.memory.for_character("lin", loaded.events)[MemoryTier.EPISODIC]
        == run.memory.for_character("lin", run.events)[MemoryTier.EPISODIC]
    )


def test_cold_character_has_no_detail_and_reheating_does_not_backfill():
    run = create_run(_compiled(), seed=17)
    cold_policy = SimulationPolicy(
        max_catchup_ticks=1,
        hot_character_ids=("lin",),
        opportunity_budget=5,
        action_budget=2,
    )
    run_catchup(run, 6, policy=cold_policy)
    boundary = len(run.events)

    forbidden = {
        EventType.DIALOGUE,
        EventType.SOUL_EVOLUTION_PROPOSED,
        EventType.SOUL_EVOLUTION_APPROVED,
        EventType.SOUL_EVOLUTION_REJECTED,
    }
    assert not any(
        event.actor_id == "wei" and event.event_type in forbidden
        for event in run.events
    )
    assert not any(
        event.event_type is EventType.DIALOGUE and "wei" in event.observers
        for event in run.events
    )

    hot_again = SimulationPolicy(hot_character_ids=("wei",))
    run_ticks(run, 1, policy=hot_again)
    assert all(event.sequence >= boundary for event in run.events[boundary:])
    assert any(event.actor_id == "wei" for event in run.events[boundary:])


def test_same_seed_and_policy_produce_identical_coarse_history():
    compiled = _compiled()
    policy = SimulationPolicy(
        max_catchup_ticks=3,
        hot_location_ids=("tide-workshop",),
        action_budget=2,
        opportunity_budget=5,
        incident_budget=1,
        memory_budget=1,
    )
    first = create_run(compiled, seed=29)
    second = create_run(compiled, seed=29)

    assert run_catchup(first, 20, policy=policy) == run_catchup(
        second, 20, policy=policy
    )
    assert first.events == second.events
    assert first.state == second.state == first.replay()
