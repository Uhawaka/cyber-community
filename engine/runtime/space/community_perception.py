"""Current public observations, never hidden inspection or author answers."""

from __future__ import annotations

from engine.contracts.community import PerceptionEnvelope, VisibleEntity


def perceive(run, actor_id: str) -> PerceptionEnvelope:
    actor = run.state.characters[actor_id]
    world = run.compiled.world
    location = next(p for p in world.locations if p.id == actor.location_id)
    entities = []
    for resource in world.resources:
        held = run.state.inventories[actor_id].get(resource.id, 0)
        if resource.location_id != actor.location_id and not held:
            continue
        if run.state.resources[resource.id] <= 0 and not held:
            continue
        properties = dict(resource.properties)
        if properties.get("hidden") is True and not held:
            continue
        entities.append(VisibleEntity(
            resource.id, resource.name, "resource",
            (str(properties.get("visible_description", resource.name)), f"held: {held}"),
            f"perception:{actor_id}:{run.state.tick}:{resource.id}",
        ))
    for other_id in present_ids(run, actor.location_id):
        if other_id == actor_id:
            continue
        other = next((c for c in world.characters if c.id == other_id), None)
        name = other.name if other else run.state.characters[other_id].display_name
        entities.append(VisibleEntity(
            other_id, name, "character", ("present",),
            f"perception:{actor_id}:{run.state.tick}:{other_id}",
        ))
    routes = tuple(
        passage.id for passage in world.passages
        if passage.origin_id == actor.location_id
        and dict(passage.properties).get("hidden") is not True
    )
    received = tuple(
        f"event:{event.sequence}" for event in run.events[-64:]
        if actor_id in event.observers and event.event_type.value == "dialogue"
    )[-16:]
    return PerceptionEnvelope(
        actor_id, run.state.tick, actor.location_id,
        location.description, tuple(entities[:64]), routes, received,
    )


def present_ids(run, location_id):
    return tuple(sorted(
        actor_id for actor_id, actor in run.state.characters.items()
        if actor.active and actor.location_id == location_id
    ))
