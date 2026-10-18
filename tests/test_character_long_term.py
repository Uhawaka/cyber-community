from pathlib import Path
from dataclasses import replace

from engine.application import (
    apply_intervention,
    create_run,
    get_pending_user_gate,
    run_ticks,
)
from engine.runtime.character.memory import MemoryProjection, MemoryTier
from engine.runtime.character.policy import DeterministicActorPolicy, SoulDecisionContext
from engine.runtime.character.contracts import SchemeStatus
from engine.runtime.kernel.events import Delta, EventType, WorldEvent
from engine.runtime.kernel.state import SoulOverlay
from engine.runtime.simulation.evolution import evolve_souls
from engine.runtime.space import Affordance, ActionKind, Opportunity
from engine.world.package_compiler import compile_package


PACKAGE = Path(__file__).parents[1] / "worlds" / "echo-quay"


def _compiled():
    result = compile_package(PACKAGE)
    assert result.ok and result.compiled is not None
    return result.compiled


def test_soul_is_read_only_input_and_schemes_are_replayable_state():
    compiled = _compiled()
    character = compiled.world.characters[0]
    context = SoulDecisionContext.from_character(character)
    assert context.values == tuple(dict(character.soul).get("values", ()))

    run = create_run(compiled, seed=17)
    run_ticks(run, 12)

    assert run.state.schemes
    assert any(
        scheme.status in {
            SchemeStatus.ACTIVE,
            SchemeStatus.COMPLETED,
            SchemeStatus.INVALIDATED,
        }
        for scheme in run.state.schemes.values()
    )
    assert run.replay() == run.state
    scheme_events = {
        EventType.SCHEME_CREATED,
        EventType.SCHEME_ADVANCED,
        EventType.SCHEME_COMPLETED,
        EventType.SCHEME_INVALIDATED,
    }
    assert any(event.event_type in scheme_events for event in run.events)


def test_memory_rebuild_and_guarded_soul_evolution_are_event_sourced():
    compiled = _compiled()
    run = create_run(compiled, seed=3)
    run_ticks(run, 20)
    pending = get_pending_user_gate(run)
    if pending is not None:
        apply_intervention(run, pending.gate_id)
        run_ticks(run, 20)

    markers = [
        event
        for event in run.events
        if event.event_type is EventType.MEMORY_CONSOLIDATED
    ]
    assert markers
    assert all(
        event.data["source_sequences"]
        and event.data["target_tier"] in {"semantic", "core"}
        and event.data["belief_type"] in {"fact", "inference", "misbelief"}
        and event.data["summary"]
        and not event.delta.actions
        for event in markers
    )

    actor_id = compiled.world.characters[0].id
    before = run.memory.for_character(actor_id, run.events)
    del run.memory
    rebuilt = MemoryProjection(compiled.world.characters)
    after = rebuilt.for_character(actor_id, run.events)
    assert before == after
    assert all(
        memory.belief_type and memory.source and 0 <= memory.confidence <= 1
        for tier in MemoryTier
        for memory in after[tier]
    )

    proposals = [
        event
        for event in run.events
        if event.event_type is EventType.SOUL_EVOLUTION_PROPOSED
    ]
    assert proposals
    assert all(
        len(event.data["evidence_sequences"]) >= 3
        and all(
            run.events[sequence].event_type is not EventType.DIALOGUE
            for sequence in event.data["evidence_sequences"]
        )
        for event in proposals
    )
    decisions = {
        EventType.SOUL_EVOLUTION_APPROVED,
        EventType.SOUL_EVOLUTION_REJECTED,
    }
    assert all(
        any(
            later.event_type in decisions
            and later.data["proposal_id"] == proposal.data["proposal_id"]
            for later in run.events[proposal.sequence + 1 :]
        )
        for proposal in proposals
    )
    approved = [
        event
        for event in run.events
        if event.event_type is EventType.SOUL_EVOLUTION_APPROVED
    ][-1]
    assert approved.delta.souls
    actor = run.state.characters[approved.actor_id]
    assert actor.soul_overlay.version >= 1
    assert actor.soul_overlay.evidence["drives"] == approved.data["evidence_sequences"]
    assert run.replay() == run.state


def test_rejected_soul_event_does_not_change_overlay():
    run = create_run(_compiled(), seed=31)
    actor_id = next(iter(run.state.characters))
    before = run.state.characters[actor_id].soul_overlay
    state = run.state
    run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=state.tick,
            event_type=EventType.SOUL_EVOLUTION_REJECTED,
            actor_id=actor_id,
            observers=(actor_id,),
            delta=Delta(),
            data={"proposal_id": "rejected-test", "reason": "insufficient evidence"},
            pre_state_hash=state.state_hash(),
            world_hash=state.world_hash,
        )
    )
    assert run.state.characters[actor_id].soul_overlay == before
    assert run.replay() == run.state


def test_dialogue_alone_never_proposes_soul_evolution():
    run = create_run(_compiled(), seed=41)
    actor_ids = tuple(run.state.characters)
    for index in range(3):
        state = run.state
        run.log.append(
            WorldEvent(
                sequence=len(run.events),
                tick=state.tick,
                event_type=EventType.DIALOGUE,
                actor_id=actor_ids[0],
                observers=actor_ids,
                data={"utterance": f"ordinary dialogue {index}"},
                pre_state_hash=state.state_hash(),
                world_hash=state.world_hash,
            )
        )
    assert evolve_souls(run, actor_ids=(actor_ids[0],), budget=1) == 0


def test_fresh_world_does_not_evolve_soul_during_opening_ticks():
    run = create_run(_compiled(), seed=43)
    run_ticks(run, 8)

    assert not any(
        event.event_type
        in {
            EventType.SOUL_EVOLUTION_PROPOSED,
            EventType.SOUL_EVOLUTION_APPROVED,
            EventType.SOUL_EVOLUTION_REJECTED,
        }
        for event in run.events
    )


def test_soul_overlay_changes_deterministic_decision_weight():
    compiled = _compiled()
    run = create_run(compiled, seed=43)
    actor_id = "lin"
    state = run.state
    location_id = state.characters[actor_id].location_id
    pre_hash = state.state_hash()
    observe = Opportunity(
        actor_id,
        Affordance(ActionKind.OBSERVE, location_id, location_id),
        10,
        "test",
        "observe",
        pre_hash,
    )
    wait = Opportunity(
        actor_id,
        Affordance(ActionKind.WAIT, actor_id, location_id),
        10,
        "test",
        "wait",
        pre_hash,
    )
    policy = DeterministicActorPolicy()
    assert policy.choose(compiled.world, state, actor_id, (observe, wait)).kind is ActionKind.OBSERVE

    character = state.characters[actor_id]
    changed = replace(
        state,
        characters={
            **state.characters,
            actor_id: replace(
                character,
                soul_overlay=SoulOverlay(
                    version=1,
                    traits={"drives": ("wait",)},
                    evidence={"drives": (1, 2, 3)},
                    last_evolution_tick=0,
                ),
            ),
        },
    )
    changed_hash = changed.state_hash()
    choices = tuple(
        replace(option, pre_state_hash=changed_hash) for option in (observe, wait)
    )
    assert policy.choose(compiled.world, changed, actor_id, choices).kind is ActionKind.WAIT


def test_misbelief_consolidation_stays_observer_scoped_and_rebuilds():
    compiled = _compiled()
    run = create_run(compiled, seed=47)
    lin = "lin"
    state = run.state
    source = run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=state.tick,
            event_type=EventType.OBSERVED,
            actor_id=lin,
            observers=(lin,),
            data={
                "summary": "北灯塔已经熄灭",
                "belief_type": "misbelief",
                "confidence": 0.4,
            },
            pre_state_hash=state.state_hash(),
            world_hash=state.world_hash,
        )
    )
    state = run.state
    run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=state.tick,
            event_type=EventType.MEMORY_CONSOLIDATED,
            actor_id=lin,
            observers=(lin,),
            data={
                "source_sequences": (source.sequence,),
                "target_tier": "semantic",
                "belief_type": "misbelief",
                "confidence": 0.4,
                "summary": source.data["summary"],
            },
            pre_state_hash=state.state_hash(),
            world_hash=state.world_hash,
        )
    )
    lin_memory = run.memory.for_character(lin, run.events)[MemoryTier.SEMANTIC]
    wei_memory = run.memory.for_character("wei", run.events)[MemoryTier.SEMANTIC]
    assert lin_memory[-1].belief_type == "misbelief"
    assert lin_memory[-1].source_sequences == (source.sequence,)
    assert not any(item.summary == source.data["summary"] for item in wei_memory)
    rebuilt = MemoryProjection(compiled.world.characters)
    assert rebuilt.for_character(lin, run.events) == run.memory.for_character(
        lin, run.events
    )


def test_evolution_tick_order_is_environment_then_action_then_projections():
    run = create_run(_compiled(), seed=11)
    run_ticks(run, 8)

    for tick in range(1, 9):
        events = [event for event in run.events if event.tick == tick]
        action_indexes = [
            index for index, event in enumerate(events) if event.delta.actions
        ]
        if action_indexes:
            first_action = events[action_indexes[0]]
            elapsed = next(
                event
                for event in reversed(run.events[: first_action.sequence])
                if event.event_type is EventType.ENVIRONMENT_DECAYED
            )
            assert elapsed.tick == tick - 1
        projection_indexes = [
            index
            for index, event in enumerate(events)
            if event.event_type
            in {
                EventType.MEMORY_CONSOLIDATED,
                EventType.SOUL_EVOLUTION_PROPOSED,
                EventType.SOUL_EVOLUTION_APPROVED,
                EventType.SOUL_EVOLUTION_REJECTED,
            }
        ]
        if projection_indexes:
            assert action_indexes and max(action_indexes) < min(projection_indexes)
