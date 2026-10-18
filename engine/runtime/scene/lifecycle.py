"""Entry, revisit, and local-time lifecycle for persisted scenes."""

from __future__ import annotations

from collections.abc import Mapping

from engine.contracts import (
    BuiltinComponent,
    ComponentPatch,
    ComponentValue,
    EntityKind,
    PatchOperation,
    SceneGenerator,
    scene_entity_id,
)
from engine.runtime.kernel.events import (
    Delta,
    EventType,
    MoveDelta,
    NeedDelta,
    WorldEvent,
)
from engine.runtime.scene.generation import ensure_scene
from engine.runtime.scene.labels import entity_label
from engine.runtime.simulation.run import AutonomousRun


def enter_scene(
    run: AutonomousRun,
    actor_id: str,
    location_id: str,
    generator: SceneGenerator,
    *,
    scene_key: str = "default",
    scene_seed: str | None = None,
    egress_reason: str = "",
) -> str:
    """Lazily materialize a scene or re-enter its persisted instance."""

    scene_id = scene_entity_id(location_id, scene_key)
    if scene_id not in run.state.entities:
        return ensure_scene(
            run,
            location_id,
            generator,
            scene_key=scene_key,
            scene_seed=scene_seed,
            entering_actor_ids=(actor_id,),
        )
    actor = run.state.entities.get(actor_id)
    scene = run.state.entities[scene_id]
    if actor is None or actor.kind is not EntityKind.CHARACTER:
        raise ValueError("scene entrant must be a character entity")
    presence = actor.components.get(
        BuiltinComponent.PRESENCE.value, {}
    )
    if presence.get("scene_id") == scene_id:
        return scene_id
    anchor_ids = tuple(
        scene.components.get(
            BuiltinComponent.LAYOUT.value, {}
        ).get("anchor_ids", ())
    )
    if not anchor_ids:
        raise ValueError("persisted scene has no entry anchor")
    attributes = dict(
        scene.components.get(BuiltinComponent.ATTRIBUTES.value, {})
    )
    attributes["visit_count"] = int(
        attributes.get("visit_count", 1)
    ) + 1
    attributes["last_active_at"] = run.state.world_time
    patches = (
        ComponentPatch(
            PatchOperation.UPSERT_COMPONENT,
            actor_id,
            expected_entity_version=actor.version,
            component=ComponentValue(
                BuiltinComponent.PRESENCE.value,
                {
                    "scene_id": scene_id,
                    "anchor_id": str(anchor_ids[0]),
                    "location_id": location_id,
                },
            ),
        ),
        ComponentPatch(
            PatchOperation.UPSERT_COMPONENT,
            scene_id,
            expected_entity_version=scene.version,
            component=ComponentValue(
                BuiltinComponent.ATTRIBUTES.value, attributes
            ),
        ),
    )
    pre_hash = run.state.state_hash()
    run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=run.state.tick,
            event_type=EventType.SCENE_ENTERED,
            actor_id=actor_id,
            observers=_scene_observers(run, scene_id, actor_id),
            delta=Delta(entity_patches=patches),
            data={
                "scene_id": scene_id,
                "scene_key": scene_key,
                "location_id": location_id,
                "summary": (
                    f"{entity_label(run, actor_id)}进入"
                    f"{entity_label(run, scene_id)}。"
                ),
                "egress_reason": egress_reason,
            },
            pre_state_hash=pre_hash,
            world_hash=run.state.world_hash,
            deterministic_cursor=len(run.events),
            target_entity_id=scene_id,
            rule_basis=(
                "scene instance already exists and is re-entered",
                *(
                    (f"character egress reason: {egress_reason}",)
                    if egress_reason
                    else ()
                ),
            ),
        )
    )
    return scene_id


def travel_to_scene(
    run: AutonomousRun,
    actor_id: str,
    location_id: str,
    generator: SceneGenerator,
    *,
    scene_key: str = "default",
    egress_reason: str = "",
) -> str:
    """Traverse one authored passage and sync map and entity position."""

    current = run.state.characters.get(actor_id)
    if current is None:
        raise ValueError("scene traveler must be a known character")
    passage = next(
        (
            item
            for item in run.compiled.world.passages
            if item.origin_id == current.location_id
            and item.destination_id == location_id
        ),
        None,
    )
    if passage is None:
        raise ValueError("scene travel requires an available passage")
    destination = next(
        item
        for item in run.compiled.world.locations
        if item.id == location_id
    )
    occupancy = sum(
        item.active
        and item.location_id == location_id
        and character_id != actor_id
        for character_id, item in run.state.characters.items()
    )
    if occupancy >= destination.capacity:
        raise ValueError("destination capacity is no longer available")
    scene_id = scene_entity_id(location_id, scene_key)
    if scene_id not in run.state.entities:
        ensure_scene(
            run,
            location_id,
            generator,
            scene_key=scene_key,
            entering_actor_ids=(),
        )
    actor = run.state.entities.get(actor_id)
    scene = run.state.entities[scene_id]
    if actor is None or actor.kind is not EntityKind.CHARACTER:
        raise ValueError("scene traveler must have a character entity")
    anchor_ids = tuple(
        scene.components.get(
            BuiltinComponent.LAYOUT.value, {}
        ).get("anchor_ids", ())
    )
    if not anchor_ids:
        raise ValueError("travel destination has no entry anchor")
    attributes = dict(
        scene.components.get(BuiltinComponent.ATTRIBUTES.value, {})
    )
    attributes["visit_count"] = int(
        attributes.get("visit_count", 1)
    ) + 1
    attributes["last_active_at"] = run.state.world_time
    pre_hash = run.state.state_hash()
    run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=run.state.tick,
            event_type=EventType.MOVED,
            actor_id=actor_id,
            observers=tuple(
                sorted(
                    {
                        actor_id,
                        *(
                            character_id
                            for character_id, state
                            in run.state.characters.items()
                            if state.active
                            and state.location_id
                            in {current.location_id, location_id}
                        ),
                    }
                )
            ),
            delta=Delta(
                moves=(
                    MoveDelta(
                        actor_id, current.location_id, location_id
                    ),
                ),
                needs=(NeedDelta(actor_id, "exploration", -12),),
                entity_patches=(
                    ComponentPatch(
                        PatchOperation.UPSERT_COMPONENT,
                        actor_id,
                        expected_entity_version=actor.version,
                        component=ComponentValue(
                            BuiltinComponent.PRESENCE.value,
                            {
                                "scene_id": scene_id,
                                "anchor_id": str(anchor_ids[0]),
                                "location_id": location_id,
                            },
                        ),
                    ),
                    ComponentPatch(
                        PatchOperation.UPSERT_COMPONENT,
                        scene_id,
                        expected_entity_version=scene.version,
                        component=ComponentValue(
                            BuiltinComponent.ATTRIBUTES.value,
                            attributes,
                        ),
                    ),
                ),
                advance_time=passage.travel_time,
            ),
            data={
                "passage_id": passage.id,
                "origin_id": current.location_id,
                "destination_id": location_id,
                "scene_id": scene_id,
                "scene_key": scene_key,
                "summary": (
                    f"{entity_label(run, actor_id)}从"
                    f"{entity_label(run, current.location_id)}前往"
                    f"{entity_label(run, location_id)}，进入"
                    f"{entity_label(run, scene_id)}。"
                ),
                "egress_reason": egress_reason,
                "public_trace": True,
            },
            pre_state_hash=pre_hash,
            world_hash=run.state.world_hash,
            deterministic_cursor=len(run.events),
            target_entity_id=scene_id,
            rule_basis=(
                "authored passage and destination capacity validated",
                "map location and entity presence committed together",
                *(
                    (f"character egress reason: {egress_reason}",)
                    if egress_reason
                    else ()
                ),
            ),
        )
    )
    return scene_id


def evolve_scene_time(
    run: AutonomousRun, scene_id: str
) -> WorldEvent | None:
    """Advance a persisted scene's local clock without regenerating it."""

    scene = run.state.entities.get(scene_id)
    if scene is None or scene.kind is not EntityKind.SCENE:
        raise ValueError("scene evolution requires a scene entity")
    if scene.components.get(
        BuiltinComponent.DRAMATIC.value, {}
    ).get("status") == "resolved":
        return None
    attributes = dict(
        scene.components.get(BuiltinComponent.ATTRIBUTES.value, {})
    )
    previous = float(
        attributes.get("last_active_at", run.state.world_time)
    )
    if run.state.world_time <= previous:
        return None
    attributes["elapsed_since_last_update"] = (
        run.state.world_time - previous
    )
    attributes["last_active_at"] = run.state.world_time
    attributes["temporal_revision"] = int(
        attributes.get("temporal_revision", 0)
    ) + 1
    event_cursor = int(attributes.get("world_event_cursor", 0))
    significant = [
        {
            "kind": event.event_type.value,
            "summary": str(
                event.data.get("summary")
                or event.data.get("observation")
                or event.event_type.value
            ),
        }
        for event in run.events[event_cursor:]
        if event.event_type
        in {
            EventType.INCIDENT_OCCURRED,
            EventType.USER_INTERVENTION,
            EventType.FATE_INTERVENTION,
        }
    ]
    prior = [
        dict(item)
        for item in attributes.get("recent_world_events", ())
        if isinstance(item, Mapping)
    ]
    attributes["recent_world_events"] = tuple(
        (*prior, *significant)[-4:]
    )
    attributes["world_event_cursor"] = len(run.events)
    pre_hash = run.state.state_hash()
    return run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=run.state.tick,
            event_type=EventType.SCENE_EVOLVED,
            actor_id=None,
            observers=_scene_observers(run, scene_id),
            delta=Delta(
                entity_patches=(
                    ComponentPatch(
                        PatchOperation.UPSERT_COMPONENT,
                        scene_id,
                        expected_entity_version=scene.version,
                        component=ComponentValue(
                            BuiltinComponent.ATTRIBUTES.value,
                            attributes,
                        ),
                    ),
                )
            ),
            data={
                "scene_id": scene_id,
                "location_id": attributes.get("location_id"),
                "elapsed": run.state.world_time - previous,
                "summary": f"{scene_id}随时间发生了更新。",
            },
            pre_state_hash=pre_hash,
            world_hash=run.state.world_hash,
            deterministic_cursor=len(run.events),
            target_entity_id=scene_id,
            rule_basis=("persisted scene local clock advanced",),
        )
    )


def _scene_observers(
    run: AutonomousRun, scene_id: str, *extra_ids: str
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *extra_ids,
                *(
                    entity_id
                    for entity_id, entity in run.state.entities.items()
                    if entity_id in run.state.characters
                    and entity.components.get(
                        BuiltinComponent.PRESENCE.value, {}
                    ).get("scene_id")
                    == scene_id
                ),
            }
        )
    )
