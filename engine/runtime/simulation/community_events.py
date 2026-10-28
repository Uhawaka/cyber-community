"""Community facts share the existing durable mutation gateway."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from engine.contracts.community import COMMUNITY_RUNTIME_VERSION
from engine.runtime.kernel.events import Delta, WorldEvent

_selected_intent_step = ContextVar("selected_intent_step", default=None)


@contextmanager
def selected_intent_step(selection):
    token = _selected_intent_step.set(selection)
    try:
        yield
    finally:
        _selected_intent_step.reset(token)


def commit(run, event_type, *, actor_id=None, observers=(), delta=None,
           data=None, commit_id, target_id=None, sources=(), basis=()):
    selection = _selected_intent_step.get()
    metadata = {"intent_step": selection} if selection and delta and delta.actions else {}
    return run.log.append(WorldEvent(
        sequence=len(run.events),
        tick=run.state.tick,
        event_type=event_type,
        actor_id=actor_id,
        observers=observers,
        delta=delta or Delta(),
        data={
            **(data or {}), **metadata, "runtime_version": COMMUNITY_RUNTIME_VERSION,
            "commit_id": commit_id, "source_refs": tuple(sources),
            "workflow_kind": "evolution", "workflow_step": "community_runtime",
        },
        pre_state_hash=run.state.state_hash(),
        world_hash=run.state.world_hash,
        deterministic_cursor=len(run.events),
        target_entity_id=target_id,
        rule_basis=tuple(basis) or ("registered community operation",),
    ))


def present(run, location_id):
    return tuple(sorted(
        actor_id for actor_id, actor in run.state.characters.items()
        if actor.active and actor.location_id == location_id
    ))


def open_tick(run):
    for event in reversed(run.events):
        if event.event_type.value == "community_tick":
            return event.data.get("phase") == "open"
    return False
