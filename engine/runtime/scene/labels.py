"""Reader-facing names for committed scene text."""

from __future__ import annotations

from engine.contracts import BuiltinComponent
from engine.runtime.simulation.run import AutonomousRun


def entity_label(run: AutonomousRun, entity_id: str) -> str:
    world = run.compiled.world
    for character in world.characters:
        if character.id == entity_id and character.name.strip():
            return character.name.strip()
    for location in world.locations:
        if location.id == entity_id and location.name.strip():
            return location.name.strip()
    scene_label = _scene_seed_name(world, entity_id)
    if scene_label is not None:
        return scene_label
    entity = run.state.entities.get(entity_id)
    if entity is not None:
        identity = entity.components.get(BuiltinComponent.IDENTITY.value, {})
        name = identity.get("name") if isinstance(identity, dict) else None
        if isinstance(name, str) and name.strip() and name.strip() != entity_id:
            return name.strip()
    return entity_id


def _scene_seed_name(world: object, entity_id: str) -> str | None:
    if not entity_id.startswith("scene:"):
        return None
    rest = entity_id[len("scene:") :]
    location_id, separator, scene_key = rest.partition(":")
    if not separator:
        scene_key = "default"
    for location in getattr(world, "locations", ()):
        if location.id != location_id:
            continue
        for seed in location.scene_seeds:
            if seed.key == scene_key and seed.name.strip():
                return seed.name.strip()
        if location.name.strip():
            return location.name.strip()
    return None
