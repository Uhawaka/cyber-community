"""Places a character can actually reach from the current location."""

from __future__ import annotations

from engine.contracts import CharacterIntent
from engine.runtime.kernel.state import WorldState
from engine.world.package_spec import AutonomousWorldSpec


def adjacent_places(
    world: AutonomousWorldSpec,
    state: WorldState,
    intent: CharacterIntent,
) -> list[dict[str, str]]:
    """Next locations along authored passages. Leaving uses these, not a step inside the room."""

    location_id = state.characters[intent.actor_id].location_id
    places: dict[str, dict[str, str]] = {}
    for passage in world.passages:
        if passage.origin_id != location_id:
            continue
        destination = next(
            (
                item
                for item in world.locations
                if item.id == passage.destination_id
            ),
            None,
        )
        if destination is None:
            continue
        places[destination.id] = {
            "location_id": destination.id,
            "scene_key": "default",
            "name": destination.name,
        }
    return [places[key] for key in sorted(places)]


def inner_scenes(
    world: AutonomousWorldSpec,
    state: WorldState,
    intent: CharacterIntent,
) -> list[dict[str, str]]:
    """Other scene seeds in the same location. These are rooms, not the next place."""

    location_id = state.characters[intent.actor_id].location_id
    prefix = f"scene:{location_id}"
    current_key = (
        "default"
        if intent.scene_id == prefix
        else intent.scene_id[len(prefix) + 1 :]
        if intent.scene_id.startswith(prefix + ":")
        else "default"
    )
    location = next(
        (item for item in world.locations if item.id == location_id),
        None,
    )
    if location is None:
        return []
    return [
        {
            "location_id": location.id,
            "scene_key": seed.key,
            "name": seed.name,
        }
        for seed in location.scene_seeds
        if seed.key != current_key
    ]
