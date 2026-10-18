from pathlib import Path

import pytest

from engine.application import (
    avatar_opportunities,
    create_run,
    fork_run,
    join_avatar,
    observe_run,
    submit_avatar_attempt,
)
from engine.participation import AvatarProfile, InterventionAttempt
from engine.runtime.kernel import Delta, EventType, EventValidationError, WorldEvent
from engine.runtime.kernel.events import MoveDelta
from engine.runtime.simulation import opportunities_for
from engine.runtime.space import ActionKind, Opportunity
from engine.world.package_compiler import compile_package


PACKAGE = Path(__file__).parents[1] / "worlds" / "echo-quay"


def _run():
    result = compile_package(PACKAGE)
    assert result.ok and result.compiled is not None
    return create_run(result.compiled, seed=23)


def _join(run):
    location = run.compiled.world.characters[0].location_id
    event = join_avatar(
        run,
        AvatarProfile("traveler", "旅人"),
        location,
        goals=("understand",),
        needs={"knowledge": 45},
    )
    return event, location


def test_avatar_uses_npc_opportunity_enumeration_and_shared_resolver():
    run = _run()
    joined, _ = _join(run)

    options = avatar_opportunities(run, "traveler")
    npc_options = opportunities_for(
        run.compiled.world, run.state, run.compiled.world.characters[0].id
    )
    assert options and npc_options
    assert all(isinstance(item, Opportunity) for item in options + npc_options)
    assert {type(item.affordance.kind) for item in options + npc_options} == {ActionKind}

    selected = next(item for item in options if item.affordance.kind is ActionKind.WAIT)
    event = submit_avatar_attempt(
        run,
        InterventionAttempt(
            "attempt-1", selected.opportunity_id, "traveler", "wait"
        ),
    )
    assert event.event_type is EventType.WAITED
    assert event.opportunity_id == selected.opportunity_id
    assert event.pre_state_hash == selected.pre_state_hash
    assert event.world_hash == run.state.world_hash
    assert event.rule_basis
    assert joined.event_type is EventType.AVATAR_JOINED
    assert run.replay().characters["traveler"].participant_kind == "avatar"


def test_observation_is_read_only_and_intervention_forks_without_mutating_source():
    run = _run()
    _join(run)
    before_observe = (run.state, run.events, run.history_hash())
    view = observe_run(run)
    assert (view.state, view.events) == before_observe[:2]
    assert (run.state, run.events, run.history_hash()) == before_observe

    branch = fork_run(run)
    source_before = (run.state, run.events, run.history_hash())
    selected = next(
        item
        for item in avatar_opportunities(branch, "traveler")
        if item.affordance.kind is ActionKind.WAIT
    )
    submit_avatar_attempt(
        branch,
        InterventionAttempt(
            "attempt-branch", selected.opportunity_id, "traveler", "wait"
        ),
    )
    assert len(branch.events) == len(run.events) + 1
    assert (run.state, run.events, run.history_hash()) == source_before
    assert branch.replay() == branch.state


def test_stale_opportunity_and_unknown_destination_are_rejected_atomically():
    run = _run()
    _join(run)
    selected = next(
        item
        for item in avatar_opportunities(run, "traveler")
        if item.affordance.kind is ActionKind.WAIT
    )
    submit_avatar_attempt(
        run,
        InterventionAttempt("attempt-ok", selected.opportunity_id, "traveler", "wait"),
    )
    with pytest.raises(ValueError, match="current legal opportunity"):
        submit_avatar_attempt(
            run,
            InterventionAttempt(
                "attempt-stale", selected.opportunity_id, "traveler", "wait"
            ),
        )

    before = run.state
    character = before.characters["traveler"]
    with pytest.raises(EventValidationError, match="unknown move destination"):
        run.log.append(
            WorldEvent(
                sequence=len(run.events),
                tick=before.tick,
                event_type=EventType.MOVED,
                actor_id="traveler",
                observers=("traveler",),
                delta=Delta(
                    moves=(
                        MoveDelta(
                            "traveler", character.location_id, "malicious-nowhere"
                        ),
                    )
                ),
            )
        )
    assert run.state == before
