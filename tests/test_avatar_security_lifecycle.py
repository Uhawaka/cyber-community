from pathlib import Path

import pytest

from engine.application import (
    avatar_memory,
    avatar_perception,
    create_run,
    join_avatar,
    leave_avatar,
    run_catchup,
    run_ticks,
)
from engine.participation import AvatarPackage
from engine.runtime.kernel import (
    AvatarPresenceDelta,
    Delta,
    EventType,
    EventValidationError,
    WorldEvent,
)
from engine.runtime.simulation.resolver import Resolver
from engine.runtime.space import ActionAttempt, ActionKind
from engine.world.package_compiler import compile_package


PACKAGE = Path(__file__).parents[1] / "worlds" / "echo-quay"


def _run():
    result = compile_package(PACKAGE)
    assert result.ok and result.compiled is not None
    return create_run(result.compiled, seed=61)


def _package(**profile):
    return AvatarPackage(
        "guest",
        "访客",
        profile={
            "identity": "远行者",
            "goals": ("观察潮声",),
            "needs": {"knowledge": 30},
            "skills": ("listen",),
            **profile,
        },
        soul={"values": ("克制",)},
        memory_seed=(
            {
                "kind": "belief",
                "summary": "我从北方来。",
                "confidence": 0.9,
                "visibility": "private",
            },
        ),
    )


def test_avatar_package_rejects_capabilities_deltas_and_bounds():
    for payload in (
        {"tools": ["shell"]},
        {"network": True},
        {"permissions": {"files": ["/"]}},
        {"delta": {"resources": 99}},
    ):
        with pytest.raises(ValueError, match="capabilities or deltas"):
            AvatarPackage("guest", "访客", profile=payload)
    with pytest.raises(ValueError, match="skills"):
        _package(skills=tuple(f"skill-{index}" for index in range(33)))
    with pytest.raises(ValueError, match="valid id"):
        AvatarPackage("../guest", "访客")


def test_entry_is_authorized_and_avatar_is_never_autonomously_scheduled():
    run = _run()
    with pytest.raises(ValueError, match="not authorized"):
        join_avatar(run, _package(), "glass-market")
    join_avatar(run, _package(), "bell-pier")
    location = run.state.characters["guest"].location_id

    run_ticks(run, 3)

    assert run.state.characters["guest"].location_id == location
    assert not any(
        action.character_id == "guest"
        for event in run.events
        for action in event.delta.actions
    )


def test_perception_memory_and_pause_leave_rejoin_lifecycle():
    run = _run()
    package = _package()
    join_avatar(run, package, "bell-pier")
    run_ticks(run, 1)
    before_leave = run.state.characters["guest"]
    leave = leave_avatar(run, "guest")
    assert leave.event_type is EventType.AVATAR_LEFT

    run_catchup(run, 4, max_ticks=1)
    offline = run.state.characters["guest"]
    assert offline.location_id == before_leave.location_id
    assert offline.needs["fatigue"] > before_leave.needs["fatigue"]
    assert not offline.active
    assert all(
        event.sequence < leave.sequence
        for event in avatar_perception(run, "guest")
        if event.event_type not in {EventType.AVATAR_LEFT}
    )

    rejoined = join_avatar(run, package, offline.location_id)
    assert rejoined.event_type is EventType.AVATAR_REJOINED
    assert run.state.characters["guest"].location_id == before_leave.location_id
    core = avatar_memory(run, "guest")
    assert [item.summary for item in core[next(iter(
        tier for tier in core if tier.value == "core"
    ))]] == ["我从北方来。"]
    assert all(
        memory.source_sequence is None
        or "secret" not in memory.summary.lower()
        for memories in core.values()
        for memory in memories
    )
    assert run.replay() == run.state


def test_event_log_enforces_avatar_lifecycle_presence_value():
    run = _run()
    join_avatar(run, _package(), "bell-pier")
    state = run.state

    with pytest.raises(EventValidationError, match="active=False"):
        run.log.append(
            WorldEvent(
                sequence=len(run.events),
                tick=state.tick,
                event_type=EventType.AVATAR_LEFT,
                actor_id="guest",
                observers=("guest",),
                delta=Delta(
                    avatar_presence=(AvatarPresenceDelta("guest", True),)
                ),
                pre_state_hash=state.state_hash(),
                world_hash=state.world_hash,
            )
        )

    leave_avatar(run, "guest")
    state = run.state
    with pytest.raises(EventValidationError, match="active=True"):
        run.log.append(
            WorldEvent(
                sequence=len(run.events),
                tick=state.tick,
                event_type=EventType.AVATAR_REJOINED,
                actor_id="guest",
                observers=("guest",),
                delta=Delta(
                    avatar_presence=(AvatarPresenceDelta("guest", False),)
                ),
                pre_state_hash=state.state_hash(),
                world_hash=state.world_hash,
            )
        )


def test_same_illegal_attempt_has_same_resolver_error_for_npc_and_avatar():
    run = _run()
    npc_id, npc = next(
        (actor_id, character)
        for actor_id, character in run.state.characters.items()
        if character.participant_kind == "npc"
    )
    join_avatar(run, _package(), npc.location_id)
    resolver = Resolver(run.compiled.world, run.log)

    messages = []
    for actor_id in (npc_id, "guest"):
        with pytest.raises(ValueError) as error:
            resolver.resolve(
                ActionAttempt(
                    actor_id=actor_id,
                    kind=ActionKind.MOVE,
                    target_id="missing-passage",
                    expected_location_id=npc.location_id,
                    cost=1,
                    reason="same illegal attempt",
                )
            )
        messages.append(str(error.value))
    assert messages == ["passage is not available"] * 2
