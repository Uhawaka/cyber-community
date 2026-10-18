"""Factories that project authored characters into scene entities."""

from __future__ import annotations

from engine.contracts import (
    BuiltinComponent,
    ComponentValue,
    EntityKind,
    EntitySpec,
    SceneBlueprint,
)


def character_entity(
    character_id: str,
    name: str,
    blueprint: SceneBlueprint,
    location_id: str,
    profile: dict[str, object],
    soul: dict[str, object],
) -> EntitySpec:
    return EntitySpec(
        character_id,
        EntityKind.CHARACTER,
        (
            ComponentValue(
                BuiltinComponent.IDENTITY.value,
                {
                    "name": name,
                    "description": str(
                        profile.get("description", "")
                    ),
                },
            ),
            ComponentValue(
                BuiltinComponent.PRESENCE.value,
                {
                    "scene_id": blueprint.scene_id,
                    "anchor_id": blueprint.entry_anchor_id,
                    "location_id": location_id,
                },
            ),
            ComponentValue(
                BuiltinComponent.AGENT.value,
                {
                    "goals": tuple(
                        str(item)
                        for item in profile.get("goals", ())
                    ),
                    "motivation": (
                        dict(profile["motivation"])
                        if isinstance(
                            profile.get("motivation"), dict
                        )
                        else {}
                    ),
                    "commitment_status": "active",
                    "soul": soul,
                    "pending_interactions": (),
                },
            ),
            ComponentValue(
                BuiltinComponent.ATTRIBUTES.value,
                dict(profile.get("attributes", {}))
                if isinstance(profile.get("attributes"), dict)
                else {},
            ),
            ComponentValue(
                BuiltinComponent.INVENTORY.value,
                {"item_ids": ()},
            ),
        ),
    )
