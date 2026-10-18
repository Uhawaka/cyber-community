import json
import shutil
from dataclasses import replace
from itertools import groupby
from pathlib import Path

import pytest

from engine.application import create_run, run_catchup, run_ticks
from engine.runtime.character import MemoryTier
from engine.runtime.kernel.events import (
    Delta,
    EventType,
    EventValidationError,
    MoveDelta,
    WorldEvent,
)
from engine.runtime.simulation.resolver import Resolver
from engine.runtime.simulation.planner import choose_attempt
from engine.runtime.space import ActionAttempt, ActionKind
from engine.world.package_compiler import compile_package


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "worlds" / "echo-quay"


def compiled_world(path=PACKAGE):
    result = compile_package(path)
    assert result.ok
    assert result.compiled is not None
    return result.compiled


def test_twenty_ticks_produce_emergent_movement_meeting_and_change():
    run = create_run(compiled_world(), seed=17)
    run_ticks(run, 20)

    kinds = [event.event_type for event in run.events]
    assert EventType.MOVED in kinds
    dialogue = next(event for event in run.events if event.event_type is EventType.DIALOGUE)
    assert dialogue.data["utterance"]
    assert dialogue.data["speaker_id"] in dialogue.observers
    assert dialogue.data["listener_id"] in dialogue.observers
    assert (
        any(run.state.inventories[actor] for actor in run.state.inventories)
        or any(
            score
            for relationships in run.state.relationships.values()
            for score in relationships.values()
        )
    )


def test_twenty_tick_behavior_is_varied_but_still_productive():
    for seed in (3, 17, 29):
        run = create_run(compiled_world(), seed=seed)
        run_ticks(run, 20)
        actions_by_actor = {
            actor_id: [
                event
                for event in run.events
                if event.actor_id == actor_id
            ]
            for actor_id in run.state.characters
        }
        action_events = [
            event for events in actions_by_actor.values() for event in events
        ]

        assert any(
            event.event_type is EventType.DIALOGUE for event in action_events
        )
        assert any(event.event_type is EventType.MOVED for event in action_events)
        assert any(event.event_type is EventType.GATHERED for event in action_events)
        for events in actions_by_actor.values():
            kind_streaks = [
                len(tuple(group))
                for _, group in groupby(event.event_type for event in events)
            ]
            target_streaks = [
                len(tuple(group))
                for _, group in groupby(
                    (event.event_type, event.target_entity_id)
                    for event in events
                )
            ]
            assert max(kind_streaks, default=0) <= 2
            assert max(target_streaks, default=0) <= 1


def test_active_plan_persists_and_move_uses_a_shortest_path():
    run = create_run(compiled_world(), seed=17)
    actor_id = "lin"
    actor = replace(
        run.state.characters[actor_id],
        location_id="bell-pier",
        short_plan=("gather", "hemp-rope", "tide-workshop"),
    )
    state = replace(
        run.state,
        characters={**run.state.characters, actor_id: actor},
    )

    attempt = choose_attempt(run.compiled.world, state, actor_id)

    assert attempt.kind is ActionKind.MOVE
    assert attempt.target_id == "pier-to-market"
    assert attempt.replacement_plan is None
    assert state.characters[actor_id].short_plan == (
        "gather",
        "hemp-rope",
        "tide-workshop",
    )


def test_same_seed_replays_identically_and_other_seed_branches():
    compiled = compiled_world()
    first = create_run(compiled, seed=11)
    second = create_run(compiled, seed=11)
    branch = create_run(compiled, seed=29)
    run_ticks(first, 12)
    run_ticks(second, 12)
    run_ticks(branch, 12)

    assert first.events == second.events
    assert first.state == first.replay()
    assert first.history_hash() == second.history_hash()
    assert first.history_hash() != branch.history_hash()
    assert all("world_hash" in event.data for event in first.events[:1])


def test_authored_resources_and_passages_change_history(tmp_path):
    package = tmp_path / "world"
    shutil.copytree(PACKAGE, package)
    resources_path = package / "resources.yaml"
    resources = json.loads(resources_path.read_text(encoding="utf-8"))
    resources["resources"][0]["quantity"] = 0
    resources_path.write_text(json.dumps(resources, ensure_ascii=False), encoding="utf-8")
    passages_path = package / "passages.yaml"
    passages = json.loads(passages_path.read_text(encoding="utf-8"))
    passages["passages"][0]["travel_time"] = 5
    passages_path.write_text(json.dumps(passages, ensure_ascii=False), encoding="utf-8")

    changed = create_run(compiled_world(package), seed=11)
    baseline = create_run(compiled_world(), seed=11)
    run_ticks(changed, 10)
    run_ticks(baseline, 10)

    assert changed.state.world_hash != baseline.state.world_hash
    assert changed.history_hash() != baseline.history_hash()


def test_colocation_and_observer_boundaries():
    run = create_run(compiled_world(), seed=3)
    resolver = Resolver(run.compiled.world, run.log)
    with pytest.raises(ValueError, match="co-location"):
        resolver.resolve(
            ActionAttempt(
                "lin", ActionKind.TALK, "wei", "tide-workshop", 1, "test"
            )
        )

    run_ticks(run, 6)
    dialogue = next(event for event in run.events if event.event_type is EventType.DIALOGUE)
    outsider = dialogue.data["listener_id"]
    memories = run.memory.for_character(outsider, run.events)
    assert any(
        item.source_sequence == dialogue.sequence
        for item in memories[MemoryTier.EPISODIC]
    )
    seed_core = memories[MemoryTier.CORE]
    assert seed_core
    assert any(item.seeded and item.source_sequence is None for item in seed_core)
    assert all(
        item.seeded or item.source_sequences
        for item in seed_core
    )
    assert not any(
        event.data.get("summary") == seed_core[0].summary for event in run.events
    )


def test_delta_is_atomic_and_catchup_is_typed_and_bounded():
    run = create_run(compiled_world(), seed=1)
    before = run.state
    bad = WorldEvent(
        sequence=len(run.events),
        tick=run.state.tick,
        event_type=EventType.MOVED,
        actor_id="lin",
        observers=("lin",),
        delta=Delta(
            moves=(MoveDelta("lin", "wrong-origin", "glass-market"),),
        ),
    )
    with pytest.raises(EventValidationError):
        run.log.append(bad)
    assert run.state == before
    assert len(run.events) == 1

    run_catchup(run, 100, max_ticks=4)
    summary = run.events[-1]
    assert summary.event_type is EventType.COARSE_TICK_SUMMARY
    assert summary.data["executed_ticks"] == 7
    assert summary.data["truncated_ticks"] == 89
