from dataclasses import replace
from pathlib import Path

import pytest

from engine.runtime.simulation import create_run
from engine.runtime.simulation.reservations import ReservationBook
from engine.runtime.simulation.resolver import Resolver
from engine.runtime.space import ActionAttempt, ActionKind
from engine.world import compile_package


ROOT = Path(__file__).parents[1]


def _fixture():
    result = compile_package(ROOT / "worlds" / "echo-quay")
    assert result.ok and result.compiled is not None
    run = create_run(result.compiled, seed=19)
    state = replace(
        run.state,
        characters={
            actor_id: replace(character, location_id="glass-market")
            for actor_id, character in run.state.characters.items()
        },
        resources={**run.state.resources, "signal-oil": 1},
    )
    attempts = tuple(
        ActionAttempt(
            actor_id,
            ActionKind.GATHER,
            "signal-oil",
            "glass-market",
            1,
            "test contention",
            opportunity_id=f"gather-{actor_id}",
            pre_state_hash=state.state_hash(),
        )
        for actor_id in ("lin", "wei")
    )
    return result.compiled.world, state, attempts


def test_resource_reservation_is_order_independent_and_rejects_loser():
    world, state, attempts = _fixture()
    first = ReservationBook(world, state).allocate(attempts)
    second = ReservationBook(world, state).allocate(tuple(reversed(attempts)))

    assert tuple(item.actor_id for item in first[0]) == tuple(
        item.actor_id for item in second[0]
    )
    assert len(first[0]) == len(first[1]) == 1
    assert first[1][0].reason == "resource_capacity_exhausted"


def test_failed_reservation_can_replan_to_wait():
    world, state, attempts = _fixture()
    _, rejected = ReservationBook(world, state).allocate(attempts)
    loser = rejected[0]
    wait = replace(
        loser.attempt,
        kind=ActionKind.WAIT,
        target_id=loser.actor_id,
        cost=0,
        opportunity_id=f"wait-{loser.actor_id}",
    )
    accepted, retried = ReservationBook(world, state).allocate((wait,))
    assert not retried
    assert accepted[0].kind is ActionKind.WAIT


def test_location_capacity_is_reserved_once():
    world, state, _ = _fixture()
    world = replace(
        world,
        locations=tuple(
            replace(item, capacity=1) if item.id == "glass-market" else item
            for item in world.locations
        ),
    )
    state = replace(
        state,
        characters={
            actor_id: replace(character, location_id="bell-pier")
            for actor_id, character in state.characters.items()
        },
    )
    attempts = tuple(
        ActionAttempt(
            actor_id,
            ActionKind.MOVE,
            "pier-to-market",
            "bell-pier",
            2,
            "capacity test",
            opportunity_id=f"move-{actor_id}",
            pre_state_hash=state.state_hash(),
        )
        for actor_id in ("lin", "wei")
    )
    accepted, rejected = ReservationBook(world, state).allocate(attempts)
    assert len(accepted) == len(rejected) == 1
    assert rejected[0].reason == "location_capacity_exhausted"


def test_capacity_one_locations_allow_atomic_swap():
    world, state, _ = _fixture()
    world = replace(
        world,
        locations=tuple(
            replace(item, capacity=1)
            if item.id in {"bell-pier", "glass-market"}
            else item
            for item in world.locations
        ),
    )
    state = replace(
        state,
        characters={
            "lin": replace(state.characters["lin"], location_id="bell-pier"),
            "wei": replace(state.characters["wei"], location_id="glass-market"),
        },
    )
    attempts = (
        ActionAttempt(
            "lin",
            ActionKind.MOVE,
            "pier-to-market",
            "bell-pier",
            2,
            "swap",
            opportunity_id="lin-swap",
            pre_state_hash=state.state_hash(),
        ),
        ActionAttempt(
            "wei",
            ActionKind.MOVE,
            "market-to-pier",
            "glass-market",
            2,
            "swap",
            opportunity_id="wei-swap",
            pre_state_hash=state.state_hash(),
        ),
    )

    accepted, rejected = ReservationBook(world, state).allocate(attempts)

    assert {item.actor_id for item in accepted} == {"lin", "wei"}
    assert rejected == ()


def test_resolver_rejects_stale_reservation_atomically():
    result = compile_package(ROOT / "worlds" / "echo-quay")
    assert result.ok and result.compiled is not None
    run = create_run(result.compiled, seed=5)
    attempt = ActionAttempt(
        "lin",
        ActionKind.GATHER,
        "hemp-rope",
        "tide-workshop",
        1,
        "atomic test",
        opportunity_id="atomic-gather",
        pre_state_hash=run.state.state_hash(),
    )
    book = ReservationBook(result.compiled.world, run.state)
    accepted, rejected = book.allocate((attempt,))
    assert not rejected
    stale = replace(accepted[0], pre_state_hash="stale")
    before_state = run.state
    before_events = run.events

    with pytest.raises(ValueError, match="precondition hash"):
        Resolver(
            result.compiled.world, run.log, reservation_book=book
        ).resolve(stale)

    assert run.state == before_state
    assert run.events == before_events
