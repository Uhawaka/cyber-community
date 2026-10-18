"""Model-backed one-time scene generation with a narrow structural schema."""

from __future__ import annotations

import json
from collections.abc import Mapping

from engine.adapters.model_json import decode_json_object
from engine.contracts import (
    BuiltinComponent,
    ComponentValue,
    EntityKind,
    EntitySpec,
    SceneBlueprint,
    SceneGenerationContext,
    TextModel,
    scene_entity_id,
)
from engine.runtime.scene.generation import (
    DeterministicSceneGenerator,
    authored_item_entities,
)
from engine.runtime.scene.validation import validate_scene_blueprint


class ModelSceneGenerator:
    def __init__(
        self,
        model: TextModel,
        *,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.fallback = DeterministicSceneGenerator()
        self.diagnostics: list[str] = []

    def generate(self, context: SceneGenerationContext) -> SceneBlueprint:
        scene_id = scene_entity_id(
            context.location_id, context.scene_key
        )
        prompt = (
            "你是文字世界的场景生成器。场景只生成一次并会永久保存。"
            "根据世界种子自然生成合理布局、显著物件、可交互提示和少量环境NPC；"
            "不要编排角色剧情，不生成玩家角色，不预设重大秘密。交互提示是自然语言"
            "能力边界，不是动作枚举。根据阶段问题生成一至三个环境压力来源；"
            "压力只能描述会迫使角色选择的环境条件，不能指定角色行动或结局。"
            "输入中的authored_items是作者定义的规范物件：不得改名、改写描述、"
            "弱化或另造同义副本；只在authored_item_anchors中为它们选择锚点，"
            "系统会原样注入。items只能生成除此以外的环境物件。"
            "只返回JSON对象，schema为："
            '{"entry_anchor_id":"完整ID","local_rules":["..."],'
            '"pressure_sources":["..."],'
            '"authored_item_anchors":{"资源ID":"锚点完整ID"},'
            '"anchors":'
            '[{"id":"完整ID","name":"...","description":"..."}],"items":'
            '[{"id":"完整ID","name":"...","description":"...","anchor_id":"...",'
            '"interaction_hints":["..."]}],"npcs":[{"id":"完整ID","name":"...",'
            '"description":"...","anchor_id":"...","routines":["..."],'
            '"response_style":"...","known_facts":["..."],'
            '"interaction_hints":["..."]}]}。'
            "known_facts最多三条，只写该NPC在这个场景 premise 里肉眼能看见、"
            "可直接回答的那一层。premise 写明这里看不见的事，不要写进事实、"
            "物件描述或 NPC 能说的话。不得写重大秘密、推断或未提交的角色历史。"
            f"所有ID必须以{scene_id}:开头；anchors最多{context.max_anchors}个，"
            f"所有实体总数最多{context.max_entities}个，环境NPC最多"
            f"{context.max_ambient_npcs}个。输入："
            + json.dumps(
                {
                    "scene_id": scene_id,
                    "world_id": context.world_id,
                    "world_title": context.world_title,
                    "premise": context.premise,
                    "seed": context.seed,
                    "location_id": context.location_id,
                    "location_name": context.location_name,
                    "location_seed": context.location_seed,
                    "scene_key": context.scene_key,
                    "scene_seed": context.scene_seed,
                    "dramatic_question": context.dramatic_question,
                    "failure_pressure": context.failure_pressure,
                    "closure_signals": context.closure_signals,
                    "world_time": context.world_time,
                    "prior_scene_ids": context.prior_scene_ids,
                    "world_rules": _plain(context.world_rules),
                    "authored_items": _plain(context.authored_items),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        try:
            value = decode_json_object(
                self.model.complete(
                    prompt, timeout_seconds=self.timeout_seconds
                )
            )
            blueprint = _decode_blueprint(value, context)
            validate_scene_blueprint(
                blueprint,
                max_anchors=context.max_anchors,
                max_entities=context.max_entities,
                max_ambient_npcs=context.max_ambient_npcs,
            )
            return blueprint
        except Exception as exc:
            self.diagnostics.append(
                f"scene generation fallback: {type(exc).__name__}: {exc}"
            )
            return self.fallback.generate(context)


def _decode_blueprint(
    value: object, context: SceneGenerationContext
) -> SceneBlueprint:
    if not isinstance(value, dict):
        raise ValueError("scene response must be an object")
    scene_id = scene_entity_id(
        context.location_id, context.scene_key
    )
    anchors = _object_list(value.get("anchors"), "anchors")
    items = _object_list(value.get("items", []), "items")
    npcs = _object_list(value.get("npcs", []), "npcs")
    anchor_ids = tuple(_entity_id(item, scene_id) for item in anchors)
    entities: list[EntitySpec] = [
        EntitySpec(
            scene_id,
            EntityKind.SCENE,
            (
                ComponentValue(
                    BuiltinComponent.IDENTITY.value,
                    {
                        "name": (
                            context.location_name
                            if context.scene_key == "default"
                            else f"{context.location_name}·{context.scene_key}"
                        ),
                        "description": (
                            context.scene_seed
                            or context.location_seed
                        ),
                    },
                ),
                ComponentValue(
                    BuiltinComponent.LAYOUT.value,
                    {"anchor_ids": anchor_ids},
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
                        "pressure_sources": tuple(
                            str(item)
                            for item in value.get(
                                "pressure_sources", ()
                            )
                            if isinstance(item, str) and item.strip()
                        )[:3],
                        "pressure_level": 0,
                        "stagnant_turns": 0,
                        "pressure_escalation_turns": (
                            context.pressure_escalation_turns
                        ),
                        "max_pressure_level": context.max_pressure_level,
                        "decision_pressure_level": (
                            context.decision_pressure_level
                        ),
                        "resolution_modes": context.resolution_modes,
                        "status": "open",
                        "outcome": "",
                    },
                ),
            ),
        )
    ]
    entities.extend(
        EntitySpec(
            _entity_id(item, scene_id),
            EntityKind.ANCHOR,
            (
                ComponentValue(
                    BuiltinComponent.IDENTITY.value,
                    {
                        "name": _text(item, "name"),
                        "description": _text(item, "description"),
                    },
                ),
            ),
        )
        for item in anchors
    )
    entities.extend(
        _situated_entity(item, scene_id, context.location_id, EntityKind.ITEM)
        for item in items
    )
    entities.extend(
        _situated_entity(item, scene_id, context.location_id, EntityKind.NPC)
        for item in npcs
    )
    entry_anchor_id = _text(value, "entry_anchor_id")
    authored_item_anchors = value.get("authored_item_anchors", {})
    if not isinstance(authored_item_anchors, dict):
        raise ValueError("scene authored_item_anchors must be an object")
    authored_ids = {
        str(item["id"]) for item in context.authored_items
    }
    if set(authored_item_anchors) - authored_ids:
        raise ValueError("scene positioned an unknown authored item")
    selected_anchors = {
        str(resource_id): str(anchor_id)
        for resource_id, anchor_id in authored_item_anchors.items()
    }
    if not set(selected_anchors.values()).issubset(anchor_ids):
        raise ValueError("authored item references an unknown anchor")
    entities.extend(
        authored_item_entities(
            context,
            entry_anchor_id,
            selected_anchors,
        )
    )
    local_rules = tuple(
        str(item) for item in value.get("local_rules", ())
    )
    return SceneBlueprint(
        scene_id,
        context.location_id,
        entry_anchor_id,
        tuple(entities),
        local_rules,
        (
            f"world:{context.world_id}",
            f"seed:{context.seed}",
            f"location:{context.location_id}",
            f"scene-key:{context.scene_key}",
            f"model:{type(value).__name__}",
        ),
    )


def _situated_entity(
    value: dict[str, object],
    scene_id: str,
    location_id: str,
    kind: EntityKind,
) -> EntitySpec:
    entity_id = _entity_id(value, scene_id)
    components = [
        ComponentValue(
            BuiltinComponent.IDENTITY.value,
            {
                "name": _text(value, "name"),
                "description": _text(value, "description"),
            },
        ),
        ComponentValue(
            BuiltinComponent.PRESENCE.value,
            {
                "scene_id": scene_id,
                "anchor_id": _text(value, "anchor_id"),
                "location_id": location_id,
            },
        ),
        ComponentValue(
            BuiltinComponent.INTERACTABLE.value,
            {
                "interaction_hints": tuple(
                    str(item)
                    for item in value.get("interaction_hints", ())
                )
            },
        ),
    ]
    if kind is EntityKind.NPC:
        components.append(
            ComponentValue(
                BuiltinComponent.AMBIENT_BEHAVIOR.value,
                {
                    "routines": tuple(
                        str(item) for item in value.get("routines", ())
                    ),
                    "response_style": _text(value, "response_style"),
                    "known_facts": tuple(
                        str(item).strip()
                        for item in value.get("known_facts", ())
                        if isinstance(item, str) and item.strip()
                    )[:3],
                },
            )
        )
    return EntitySpec(entity_id, kind, tuple(components))


def _object_list(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise ValueError(f"scene {name} must be an object list")
    return value


def _entity_id(value: dict[str, object], scene_id: str) -> str:
    entity_id = _text(value, "id")
    if not entity_id.startswith(f"{scene_id}:"):
        raise ValueError("generated entity id is outside the scene namespace")
    return entity_id


def _text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"scene field {key} must be non-empty text")
    return item.strip()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value
