import json
from dataclasses import asdict
from pathlib import Path
import pytest

from engine.application import (
    apply_intervention,
    create_run,
    get_pending_user_gate,
    run_ticks,
)
from engine.runtime.character import MemoryTier
from engine.runtime.kernel.events import EventType
from engine.runtime.simulation.resolver import Resolver
from engine.runtime.space import ActionAttempt, ActionKind, DialogueAct
from engine.world.package_compiler import compile_package


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "worlds" / "black-pine-ridge"
FORBIDDEN = {
    "blocking",
    "character_arc",
    "character_arcs",
    "conflict",
    "dialogue",
    "dialogues",
    "obligation",
    "obligations",
    "outcome",
    "outcomes",
    "script",
    "stakes",
}


def compiled_world():
    result = compile_package(PACKAGE)
    assert result.ok, result.diagnostics
    assert result.compiled is not None
    return result.compiled


def nested_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from nested_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from nested_keys(child)


def test_black_pine_package_compiles_complete_autonomous_world():
    compiled = compiled_world()

    assert len(compiled.world.locations) >= 3
    assert all(
        len(location.scene_seeds) >= 2
        for location in compiled.world.locations
    )
    assert len(compiled.world.characters) == 3
    assert compiled.world.dramatic_horizon is not None
    assert compiled.world.dramatic_horizon.central_question
    back_door = next(
        item
        for item in compiled.world.locations
        if item.id == "back-door"
    )
    opening = next(
        item for item in back_door.scene_seeds
        if item.key == "default"
    )
    assert opening.dramatic_question
    assert opening.failure_pressure
    assert opening.closure_signals
    assert compiled.world.resources
    edges = {
        (passage.origin_id, passage.destination_id)
        for passage in compiled.world.passages
    }
    assert all((destination, origin) in edges for origin, destination in edges)
    for character in compiled.world.characters:
        directory = PACKAGE / "characters" / character.id
        assert {path.name for path in directory.iterdir()} == {
            "profile.yaml",
            "soul.yaml",
            "memory.seed.json",
        }
        profile = dict(character.profile)
        assert profile["goals"]
        assert profile["needs"]
        assert profile["motivation"]["active_commitment"]


def test_private_character_knowledge_becomes_seed_memory():
    compiled = compiled_world()
    run = create_run(compiled, seed=17)

    for character in compiled.world.characters:
        authored = character.memory_seed
        private = [
            item
            for item in authored
            if item.get("kind") in {"secret", "belief"}
        ]
        assert private
        assert all(item.get("visibility") == "private" for item in private)
        core = run.memory.for_character(character.id, run.events)[MemoryTier.CORE]
        assert len(core) == len(authored) >= 3
        assert all(item.seeded and item.source_sequence is None for item in core)


def test_scene_turn_workflow_persists_scene_and_first_person_turns_across_seeds():
    histories = set()
    for seed in (3, 17, 29):
        run = create_run(compiled_world(), seed=seed)
        run_ticks(run, 20)

        scenes = [
            event
            for event in run.events
            if event.event_type is EventType.SCENE_INSTANTIATED
        ]
        turns = [
            event
            for event in run.events
            if event.event_type is EventType.TURN_RESOLVED
        ]
        assert scenes
        assert turns
        assert all(
            event.actor_id in event.observers
            and event.data["intent_id"]
            and event.data["public_action"]
            and event.data["actor_feedback"]
            for event in turns
        )
        assert run.state.entities["scene:back-door"].version > 0
        assert run.replay() == run.state
        histories.add(run.history_hash())
    assert len(histories) == 3


def test_scene_turn_workflow_does_not_call_legacy_action_planner(monkeypatch):
    import engine.runtime.simulation.executor as executor

    def fail(*_args, **_kwargs):
        raise AssertionError("legacy opportunity planner was called")

    monkeypatch.setattr(executor, "opportunities_for", fail)
    run = create_run(compiled_world(), seed=17)

    run_ticks(run, 1)

    assert any(
        event.event_type is EventType.TURN_RESOLVED
        for event in run.events
    )


def test_ember_gate_commits_observable_branch_result():
    run = create_run(compiled_world(), seed=17)
    run_ticks(run, 12)
    pending = get_pending_user_gate(run)
    assert pending is not None

    event = apply_intervention(
        run, pending.gate_id, "bank-the-embers"
    )

    assert event.event_type is EventType.USER_INTERVENTION
    assert "火光重新攀上梁柱" in event.data["observation"]
    assert run.state.resources["dry-kindling"] == 2


def test_observation_omits_depleted_resource():
    run = create_run(compiled_world(), seed=17)
    gathered = Resolver(run.compiled.world, run.log).resolve(
        ActionAttempt(
            "wukong",
            ActionKind.GATHER,
            "bell-fragment",
            "back-door",
            1,
            "deplete the portable resource",
        )
    )

    observed = Resolver(run.compiled.world, run.log).resolve(
        ActionAttempt(
            gathered.actor_id,
            ActionKind.OBSERVE,
            "back-door",
            "back-door",
            1,
            "verify current location contents",
        )
    )

    assert "bell-fragment" not in observed.data["resources"]


def test_resolver_rejects_private_experience_disclosure():
    run = create_run(compiled_world(), seed=17)

    with pytest.raises(
        ValueError, match="discloses unauthorized information"
    ):
        Resolver(run.compiled.world, run.log).resolve(
            ActionAttempt(
                "bailing",
                ActionKind.TALK,
                "wukong",
                "back-door",
                1,
                "attempt private disclosure",
                utterance="我曾用苦叶草盖住身上的死气。",
                dialogue_act=DialogueAct.DISCLOSE,
                dialogue_topic="苦叶草",
                information_ids=("bailing:memory:0",),
            )
        )


def test_dialogue_propagates_public_fact_and_records_disclosure():
    run = create_run(compiled_world(), seed=17)
    resolver = Resolver(run.compiled.world, run.log)
    fact_id = "bailing:memory:1"

    resolver.resolve(
        ActionAttempt(
            "bailing",
            ActionKind.TALK,
            "wukong",
            "back-door",
            1,
            "share observed trace",
            utterance="林间小路的浅白粉末与铜铃内侧的粉痕相同。",
            dialogue_act=DialogueAct.DISCLOSE,
            dialogue_topic="铜铃",
            information_ids=(fact_id,),
        )
    )

    assert fact_id in run.state.knowledge["wukong"]
    assert fact_id in run.state.knowledge["traveler"]
    assert fact_id in run.state.disclosures["bailing"]["wukong"]
    assert fact_id in run.state.disclosures["bailing"]["traveler"]
    repeated = resolver.resolve(
        ActionAttempt(
            "wukong",
            ActionKind.TALK,
            "traveler",
            "back-door",
            1,
            "repeat known trace",
            utterance="白灵说林间粉末与铜铃内侧的粉痕相同。",
            dialogue_act=DialogueAct.DISCLOSE,
            dialogue_topic="铜铃",
            information_ids=(fact_id,),
        )
    )
    assert repeated.data["information_gain_ids"] == ()
    assert run.replay() == run.state


def test_package_contains_no_prearranged_story_or_blocking_fields():
    compiled = compiled_world()
    assert FORBIDDEN.isdisjoint(nested_keys(asdict(compiled.world)))

    for path in PACKAGE.rglob("*"):
        if path.is_file():
            authored = json.loads(path.read_text(encoding="utf-8"))
            assert FORBIDDEN.isdisjoint(nested_keys(authored)), path
