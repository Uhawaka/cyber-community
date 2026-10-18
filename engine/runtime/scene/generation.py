"""One-time scene materialisation into the authoritative event log."""

from __future__ import annotations

from engine.contracts import (
    BuiltinComponent,
    ComponentPatch,
    ComponentValue,
    EntityKind,
    EntitySpec,
    PatchOperation,
    SceneBlueprint,
    SceneGenerationContext,
    SceneGenerator,
    scene_entity_id,
)
from engine.runtime.kernel.events import Delta, EventType, WorldEvent
from engine.runtime.scene.authored_entities import character_entity
from engine.runtime.scene.validation import validate_scene_blueprint
from engine.runtime.simulation.run import AutonomousRun


class DeterministicSceneGenerator:
    """Safe fallback used when no model-backed generator is configured."""

    def generate(self, context: SceneGenerationContext) -> SceneBlueprint:
        scene_id = scene_entity_id(
            context.location_id, context.scene_key
        )
        entry_id = f"{scene_id}:entry"
        focus_id = f"{scene_id}:focus"
        return SceneBlueprint(
            scene_id,
            context.location_id,
            entry_id,
            (
                EntitySpec(
                    scene_id,
                    EntityKind.SCENE,
                    (
                        ComponentValue(
                            BuiltinComponent.IDENTITY.value,
                            {
                                "name": context.location_name,
                                "description": context.scene_seed,
                            },
                        ),
                        ComponentValue(
                            BuiltinComponent.LAYOUT.value,
                            {"anchor_ids": [entry_id, focus_id]},
                        ),
                        ComponentValue(
                            BuiltinComponent.ATTRIBUTES.value,
                            {
                                "turn_count": 0,
                                "location_id": context.location_id,
                                "scene_key": context.scene_key,
                                "created_at": context.world_time,
                                "last_active_at": context.world_time,
                                "visit_count": 1,
                            },
                        ),
                        ComponentValue(
                            BuiltinComponent.DRAMATIC.value,
                            {
                                "question": context.dramatic_question,
                                "failure_pressure": context.failure_pressure,
                                "closure_signals": context.closure_signals,
                                "pressure_sources": (
                                    context.failure_pressure,
                                )
                                if context.failure_pressure
                                else (),
                                "pressure_level": 0,
                                "stagnant_turns": 0,
                                "pressure_escalation_turns": (
                                    context.pressure_escalation_turns
                                ),
                                "max_pressure_level": (
                                    context.max_pressure_level
                                ),
                                "decision_pressure_level": (
                                    context.decision_pressure_level
                                ),
                                "resolution_modes": (
                                    context.resolution_modes
                                ),
                                "status": "open",
                                "outcome": "",
                            },
                        ),
                    ),
                ),
                EntitySpec(
                    entry_id,
                    EntityKind.ANCHOR,
                    (
                        ComponentValue(
                            BuiltinComponent.IDENTITY.value,
                            {
                                "name": "入口",
                                "description": f"{context.location_name}的入口。",
                            },
                        ),
                    ),
                ),
                EntitySpec(
                    focus_id,
                    EntityKind.ANCHOR,
                    (
                        ComponentValue(
                            BuiltinComponent.IDENTITY.value,
                            {
                                "name": "主要活动处",
                                "description": context.scene_seed,
                            },
                        ),
                    ),
                ),
                *authored_item_entities(context, entry_id),
            ),
            generation_basis=(
                f"world:{context.world_id}",
                f"seed:{context.seed}",
                f"location:{context.location_id}",
                f"scene-key:{context.scene_key}",
            ),
        )


def authored_item_entities(
    context: SceneGenerationContext,
    default_anchor_id: str,
    anchor_by_resource_id: dict[str, str] | None = None,
) -> tuple[EntitySpec, ...]:
    anchors = anchor_by_resource_id or {}
    return tuple(
        EntitySpec(
            f"{scene_entity_id(context.location_id, context.scene_key)}:"
            f"resource-{item['id']}",
            EntityKind.ITEM,
            (
                ComponentValue(
                    BuiltinComponent.IDENTITY.value,
                    {
                        "name": item["name"],
                        "description": item["description"],
                    },
                ),
                ComponentValue(
                    BuiltinComponent.PRESENCE.value,
                    {
                        "scene_id": scene_entity_id(
                            context.location_id, context.scene_key
                        ),
                        "anchor_id": anchors.get(
                            str(item["id"]), default_anchor_id
                        ),
                        "location_id": context.location_id,
                    },
                ),
                ComponentValue(
                    BuiltinComponent.INTERACTABLE.value,
                    {
                        "interaction_hints": (
                            f"可以观察或使用{item['name']}，"
                            "但不能改变其作者定义的事实",
                        )
                    },
                ),
                ComponentValue(
                    BuiltinComponent.ATTRIBUTES.value,
                    {
                        "resource_id": item["id"],
                        "authored": True,
                        "properties": item.get("properties", {}),
                    },
                ),
            ),
        )
        for item in context.authored_items
    )


def scene_generation_context(
    run: AutonomousRun,
    location_id: str,
    *,
    scene_key: str = "default",
    scene_seed: str | None = None,
) -> SceneGenerationContext:
    location = next(
        (
            item
            for item in run.compiled.world.locations
            if item.id == location_id
        ),
        None,
    )
    if location is None:
        raise ValueError(f"unknown scene location: {location_id}")
    authored_scene = next(
        (
            item
            for item in location.scene_seeds
            if item.key == scene_key
        ),
        None,
    )
    selected_scene_seed = (
        scene_seed
        or (
            authored_scene.premise
            if authored_scene is not None
            else ""
        )
        or (
            location.description
            if scene_key == "default"
            else (
                f"{location.description}；这是随剧情推进首次显现的"
                f"{scene_key}场景。"
            )
        )
        or location.name
    )
    runtime_contract = run.compiled.experience.runtime
    return SceneGenerationContext(
        world_id=run.compiled.world.world_id,
        world_title=run.compiled.world.title,
        premise=run.compiled.world.premise,
        seed=run.state.seed,
        location_id=location.id,
        location_name=location.name,
        location_seed=location.description or location.name,
        scene_key=scene_key,
        scene_seed=selected_scene_seed,
        dramatic_question=(
            authored_scene.dramatic_question
            if authored_scene is not None
            else ""
        ),
        failure_pressure=(
            authored_scene.failure_pressure
            if authored_scene is not None
            else ""
        ),
        closure_signals=(
            authored_scene.closure_signals
            if authored_scene is not None
            else ()
        ),
        world_time=run.state.world_time,
        prior_scene_ids=tuple(
            entity_id
            for entity_id, entity in run.state.entities.items()
            if entity.kind is EntityKind.SCENE
            and entity.components.get(
                BuiltinComponent.ATTRIBUTES.value, {}
            ).get("location_id")
            == location_id
        ),
        world_rules=tuple(run.compiled.world.rules),
        authored_items=tuple(
            {
                "id": resource.id,
                "name": resource.name,
                "description": str(
                    dict(resource.properties).get("inspection")
                    or resource.name
                ),
                "properties": dict(resource.properties),
            }
            for resource in run.compiled.world.resources
            if resource.location_id == location_id and resource.quantity > 0
        ),
        pressure_escalation_turns=(
            runtime_contract.pressure_escalation_turns
        ),
        max_pressure_level=runtime_contract.max_pressure_level,
        decision_pressure_level=runtime_contract.decision_pressure_level,
        resolution_modes=runtime_contract.resolution_modes,
    )


def ensure_scene(
    run: AutonomousRun,
    location_id: str,
    generator: SceneGenerator,
    *,
    scene_key: str = "default",
    scene_seed: str | None = None,
    entering_actor_ids: tuple[str, ...] | None = None,
) -> str:
    scene_id = scene_entity_id(location_id, scene_key)
    if scene_id in run.state.entities:
        return scene_id
    context = scene_generation_context(
        run,
        location_id,
        scene_key=scene_key,
        scene_seed=scene_seed,
    )
    blueprint = generator.generate(context)
    if blueprint.scene_id != scene_id or blueprint.location_id != location_id:
        raise ValueError("scene generator changed the requested identity")
    validate_scene_blueprint(
        blueprint,
        max_anchors=context.max_anchors,
        max_entities=context.max_entities,
        max_ambient_npcs=context.max_ambient_npcs,
    )
    patches = [
        ComponentPatch(
            PatchOperation.CREATE_ENTITY,
            entity.entity_id,
            entity=entity,
        )
        for entity in blueprint.entities
    ]
    location_entity_id = f"location:{location_id}"
    location_entity = run.state.entities.get(location_entity_id)
    if location_entity is None:
        patches.insert(
            0,
            ComponentPatch(
                PatchOperation.CREATE_ENTITY,
                location_entity_id,
                entity=EntitySpec(
                    location_entity_id,
                    EntityKind.LOCATION,
                    (
                        ComponentValue(
                            BuiltinComponent.IDENTITY.value,
                            {
                                "name": context.location_name,
                                "description": context.location_seed,
                            },
                        ),
                        ComponentValue(
                            BuiltinComponent.LAYOUT.value,
                            {"scene_ids": (scene_id,)},
                        ),
                    ),
                ),
            ),
        )
    else:
        layout = dict(
            location_entity.components.get(
                BuiltinComponent.LAYOUT.value, {}
            )
        )
        layout["scene_ids"] = tuple(
            dict.fromkeys(
                (*tuple(layout.get("scene_ids", ())), scene_id)
            )
        )
        patches.insert(
            0,
            ComponentPatch(
                PatchOperation.UPSERT_COMPONENT,
                location_entity_id,
                expected_entity_version=location_entity.version,
                component=ComponentValue(
                    BuiltinComponent.LAYOUT.value, layout
                ),
            ),
        )
    observers: list[str] = []
    selected_actor_ids = (
        {
            character.id
            for character in run.compiled.world.characters
            if run.state.characters.get(character.id) is not None
            and run.state.characters[character.id].location_id == location_id
        }
        if entering_actor_ids is None and scene_key == "default"
        else set(entering_actor_ids or ())
    )
    for character in run.compiled.world.characters:
        current = run.state.characters.get(character.id)
        if (
            character.id not in selected_actor_ids
            or current is None
            or current.location_id != location_id
        ):
            continue
        observers.append(character.id)
        if character.id not in run.state.entities:
            patches.append(
                ComponentPatch(
                    PatchOperation.CREATE_ENTITY,
                    character.id,
                    entity=character_entity(
                        character.id,
                        character.name,
                        blueprint,
                        location_id,
                        dict(character.profile),
                        dict(character.soul),
                    ),
                )
            )
        else:
            patches.append(
                ComponentPatch(
                    PatchOperation.UPSERT_COMPONENT,
                    character.id,
                    expected_entity_version=run.state.entities[
                        character.id
                    ].version,
                    component=ComponentValue(
                        BuiltinComponent.PRESENCE.value,
                        {
                            "scene_id": blueprint.scene_id,
                            "anchor_id": blueprint.entry_anchor_id,
                            "location_id": location_id,
                        },
                    ),
                ),
            )
    pre_hash = run.state.state_hash()
    run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=run.state.tick,
            event_type=EventType.SCENE_INSTANTIATED,
            actor_id=None,
            observers=tuple(observers),
            delta=Delta(entity_patches=tuple(patches)),
            data={
                "scene_id": scene_id,
                "scene_key": scene_key,
                "location_id": location_id,
                "entry_anchor_id": blueprint.entry_anchor_id,
                "generation_basis": blueprint.generation_basis,
            },
            pre_state_hash=pre_hash,
            world_hash=run.state.world_hash,
            deterministic_cursor=len(run.events),
            target_entity_id=scene_id,
            rule_basis=blueprint.generation_basis,
        )
    )
    return scene_id
