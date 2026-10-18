"""Run creation, persistence, loading, export, and branching."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from engine.contracts import IntentPolicy, SceneGenerator, WorldAdjudicator
from engine.runtime.character import MemoryProjection
from engine.runtime.character.policy import ActorPolicy, DeterministicActorPolicy
from engine.runtime.kernel.events import EventLog, EventPersistenceError, EventType, WorldEvent, event_record
from engine.runtime.kernel.state import WorldState
from engine.runtime.simulation.run import AutonomousRun, event_history_hash
from engine.runtime.workflow import build_initial_state, workflow_step_scope
from engine.world.package_spec import CompiledWorld

def _initial_state(compiled: CompiledWorld, seed: int) -> WorldState:
    return build_initial_state(compiled, seed)


def create_run(
    compiled: CompiledWorld,
    seed: int,
    path: str | Path | None = None,
    *,
    actor_policy: ActorPolicy | None = None,
    scene_generator: SceneGenerator | None = None,
    intent_policy: IntentPolicy | None = None,
    world_adjudicator: WorldAdjudicator | None = None,
) -> AutonomousRun:
    destination = Path(path) if path is not None else None
    if destination is not None and destination.exists() and destination.stat().st_size:
        raise EventPersistenceError("refusing to append a new run to a non-empty log")
    initial = _initial_state(compiled, seed)
    log = EventLog(initial, destination)
    initial_hash = initial.state_hash()
    with workflow_step_scope("genesis", "load_passages"):
        log.append(WorldEvent(
            sequence=0,
            tick=0,
            event_type=EventType.RUN_CREATED,
            actor_id=None,
            observers=tuple(initial.characters),
            data={
                "world_hash": compiled.content_hash,
                "seed": int(seed),
                "pre_state_hash": initial_hash,
                "deterministic_cursor": 0,
                "target_entity_id": compiled.world.world_id,
                "rule_basis": ("compiled world initializes run",),
            },
            pre_state_hash=initial_hash,
            world_hash=compiled.content_hash,
            deterministic_cursor=0,
            target_entity_id=compiled.world.world_id,
            rule_basis=("compiled world initializes run",),
        ))
    run = AutonomousRun(
        compiled=compiled,
        initial_state=initial,
        log=log,
        memory=MemoryProjection(compiled.world.characters),
        actor_policy=actor_policy or DeterministicActorPolicy(),
        scene_generator=scene_generator,
        intent_policy=intent_policy,
        world_adjudicator=world_adjudicator,
    )
    return run


def load_run(
    compiled: CompiledWorld,
    path: str | Path,
    *,
    recover_tail: bool = False,
    actor_policy: ActorPolicy | None = None,
    scene_generator: SceneGenerator | None = None,
    intent_policy: IntentPolicy | None = None,
    world_adjudicator: WorldAdjudicator | None = None,
) -> AutonomousRun:
    events = EventLog.read_events(
        path, world_hash=compiled.content_hash, recover_tail=recover_tail
    )
    if not events or events[0].event_type is not EventType.RUN_CREATED:
        raise EventPersistenceError("event log must begin with run_created")
    seed = events[0].data.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise EventPersistenceError("run_created event has no valid seed")
    initial = _initial_state(compiled, seed)
    log = EventLog.replay(initial, events, path=path)
    metadata = _read_run_metadata(path)
    run = AutonomousRun(
        compiled=compiled,
        initial_state=initial,
        log=log,
        memory=MemoryProjection(compiled.world.characters),
        parent_history_hash=metadata.get("parent_history_hash"),
        fork_sequence=metadata.get("fork_sequence"),
        actor_policy=actor_policy or DeterministicActorPolicy(),
        scene_generator=scene_generator,
        intent_policy=intent_policy,
        world_adjudicator=world_adjudicator,
    )
    for event in events:
        if event.event_type is EventType.AVATAR_JOINED:
            run.memory.register_avatar(
                str(event.data["avatar_id"]), event.data.get("memory_seed", ())
            )
    return run


def export_run(run: AutonomousRun, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        metadata = {
            "parent_history_hash": run.parent_history_hash,
            "fork_sequence": run.fork_sequence,
        }
        for event in run.events:
            record = event_record(event)
            record["run_metadata"] = metadata
            payload = json.dumps(
                record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8") + b"\n"
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("run export write made no progress")
                view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, destination)
    os.chmod(destination, 0o600)
    directory = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return destination


def _read_run_metadata(path: str | Path) -> dict[str, Any]:
    try:
        first = Path(path).read_text(encoding="utf-8").splitlines()[0]
        value = json.loads(first).get("run_metadata", {})
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError, IndexError):
        return {}


def fork_run(
    run: AutonomousRun,
    event_count: int | None = None,
    *,
    through_sequence: int | None = None,
) -> AutonomousRun:
    """Rebuild an independent branch from an immutable event prefix."""
    if event_count is not None and through_sequence is not None:
        raise ValueError("choose event_count or through_sequence")
    prefix_length = (
        through_sequence + 1
        if through_sequence is not None
        else len(run.events) if event_count is None else event_count
    )
    if prefix_length < 0 or prefix_length > len(run.events):
        raise ValueError("event prefix is outside the run history")
    prefix = run.events[:prefix_length]
    log = EventLog.replay(run.initial_state, prefix)
    branch = AutonomousRun(
        compiled=run.compiled,
        initial_state=run.initial_state,
        log=log,
        memory=MemoryProjection(run.compiled.world.characters),
        parent_history_hash=event_history_hash(prefix),
        fork_sequence=prefix_length - 1,
        actor_policy=run.actor_policy,
        scene_generator=run.scene_generator,
        intent_policy=run.intent_policy,
        world_adjudicator=run.world_adjudicator,
    )
    for event in prefix:
        if event.event_type is EventType.AVATAR_JOINED:
            branch.memory.register_avatar(
                str(event.data["avatar_id"]), event.data.get("memory_seed", ())
            )
    return branch

