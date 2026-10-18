"""Structural gates for generated entities and adjudicated scene turns."""

from __future__ import annotations

from collections.abc import Mapping

from engine.contracts import (
    AdjudicatedTurn,
    BuiltinComponent,
    CharacterIntent,
    EntityKind,
    SceneBlueprint,
)
from engine.runtime.kernel.state import WorldState


class SceneValidationError(ValueError):
    pass


_REQUIRED_COMPONENTS = {
    EntityKind.SCENE: {
        BuiltinComponent.IDENTITY.value,
        BuiltinComponent.LAYOUT.value,
    },
    EntityKind.ANCHOR: {BuiltinComponent.IDENTITY.value},
    EntityKind.CHARACTER: {
        BuiltinComponent.IDENTITY.value,
        BuiltinComponent.PRESENCE.value,
        BuiltinComponent.AGENT.value,
    },
    EntityKind.NPC: {
        BuiltinComponent.IDENTITY.value,
        BuiltinComponent.PRESENCE.value,
        BuiltinComponent.AMBIENT_BEHAVIOR.value,
    },
    EntityKind.ITEM: {
        BuiltinComponent.IDENTITY.value,
        BuiltinComponent.INTERACTABLE.value,
    },
}


def validate_scene_blueprint(
    blueprint: SceneBlueprint,
    *,
    max_anchors: int,
    max_entities: int,
    max_ambient_npcs: int,
) -> None:
    if len(blueprint.entities) > max_entities:
        raise SceneValidationError("scene exceeds its entity budget")
    counts = {
        kind: sum(item.kind is kind for item in blueprint.entities)
        for kind in EntityKind
    }
    if counts[EntityKind.ANCHOR] > max_anchors:
        raise SceneValidationError("scene exceeds its anchor budget")
    if counts[EntityKind.NPC] > max_ambient_npcs:
        raise SceneValidationError("scene exceeds its ambient NPC budget")
    ids = {item.entity_id for item in blueprint.entities}
    for entity in blueprint.entities:
        components = {
            component.component_type: component
            for component in entity.components
        }
        missing = _REQUIRED_COMPONENTS.get(entity.kind, set()) - set(
            components
        )
        if missing:
            raise SceneValidationError(
                f"{entity.entity_id} lacks components: {sorted(missing)}"
            )
        _validate_component_shapes(entity.entity_id, components)
        presence = components.get(BuiltinComponent.PRESENCE.value)
        if presence is not None:
            data = presence.data
            if (
                data.get("scene_id") != blueprint.scene_id
                or data.get("anchor_id") not in ids
            ):
                raise SceneValidationError(
                    f"{entity.entity_id} has invalid scene presence"
                )
    scene = next(
        item for item in blueprint.entities if item.entity_id == blueprint.scene_id
    )
    layout = scene.component(BuiltinComponent.LAYOUT.value)
    assert layout is not None
    anchor_ids = layout.data.get("anchor_ids")
    if not isinstance(anchor_ids, tuple) or not anchor_ids:
        raise SceneValidationError("scene layout requires anchor ids")
    if not set(anchor_ids).issubset(ids):
        raise SceneValidationError("scene layout references unknown anchors")
    if any(
        next(item for item in blueprint.entities if item.entity_id == anchor_id).kind
        is not EntityKind.ANCHOR
        for anchor_id in anchor_ids
    ):
        raise SceneValidationError("scene layout may only reference anchors")
    if blueprint.entry_anchor_id not in anchor_ids:
        raise SceneValidationError(
            "scene entry anchor must be a declared layout anchor"
        )
    for entity in blueprint.entities:
        presence = entity.component(BuiltinComponent.PRESENCE.value)
        if (
            presence is not None
            and presence.data.get("anchor_id") not in anchor_ids
        ):
            raise SceneValidationError(
                f"{entity.entity_id} presence anchor is not in scene layout"
            )


def validate_intent(intent: CharacterIntent, state: WorldState) -> None:
    actor = state.entities.get(intent.actor_id)
    scene = state.entities.get(intent.scene_id)
    if actor is None or actor.kind not in {
        EntityKind.CHARACTER,
        EntityKind.NPC,
    }:
        raise SceneValidationError("intent actor cannot act")
    if scene is None or scene.kind is not EntityKind.SCENE:
        raise SceneValidationError("intent references an unknown scene")
    if scene.version != intent.expected_scene_version:
        raise SceneValidationError("intent scene version is stale")
    presence = actor.components.get(BuiltinComponent.PRESENCE.value, {})
    if presence.get("scene_id") != intent.scene_id:
        raise SceneValidationError("intent actor is not present in the scene")
    if not set(intent.referenced_entity_ids).issubset(state.entities):
        raise SceneValidationError("intent references unknown entities")


def validate_adjudicated_turn(
    turn: AdjudicatedTurn,
    intent: CharacterIntent,
    state: WorldState,
) -> None:
    if (
        turn.intent_id != intent.intent_id
        or turn.actor_id != intent.actor_id
        or turn.scene_id != intent.scene_id
        or turn.expected_scene_version != intent.expected_scene_version
    ):
        raise SceneValidationError("adjudication does not match its intent")
    if turn.status == "rejected" and turn.patches:
        raise SceneValidationError("rejected turns cannot mutate state")
    if turn.status == "rejected" and turn.scene_transition is not None:
        raise SceneValidationError("rejected turns cannot transition scenes")
    if turn.status == "rejected" and turn.dramatic_progress != "none":
        raise SceneValidationError(
            "rejected turns cannot advance dramatic state"
        )
    if turn.dramatic_progress == "resolved":
        dramatic = state.entities[intent.scene_id].components.get(
            BuiltinComponent.DRAMATIC.value, {}
        )
        if (
            dramatic.get("status") != "open"
            or not dramatic.get("closure_signals")
        ):
            raise SceneValidationError(
                "scene has no open authored closure contract"
            )
    touched = {patch.entity_id for patch in turn.patches}
    allowed = {
        intent.actor_id,
        intent.scene_id,
        *intent.referenced_entity_ids,
    }
    if not touched.issubset(allowed):
        raise SceneValidationError("turn patches an unreferenced entity")
    for request in turn.interaction_requests:
        if (
            request.initiator_id != intent.actor_id
            or request.scene_id != intent.scene_id
            or request.recipient_id not in intent.referenced_entity_ids
        ):
            raise SceneValidationError("interaction request exceeds intent scope")
        recipient = state.entities.get(request.recipient_id)
        if recipient is None or recipient.kind not in {
            EntityKind.CHARACTER,
            EntityKind.NPC,
        }:
            raise SceneValidationError("interaction recipient cannot respond")


def _validate_component_shapes(
    entity_id: str, components: Mapping[str, object]
) -> None:
    identity = components.get(BuiltinComponent.IDENTITY.value)
    if identity is not None:
        data = getattr(identity, "data", {})
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            raise SceneValidationError(f"{entity_id} identity requires a name")
    interactable = components.get(BuiltinComponent.INTERACTABLE.value)
    if interactable is not None:
        hints = getattr(interactable, "data", {}).get("interaction_hints")
        if not isinstance(hints, tuple) or not all(
            isinstance(item, str) and item.strip() for item in hints
        ):
            raise SceneValidationError(
                f"{entity_id} interactable requires natural-language hints"
            )
