"""Ground free-form intentions into bounded entity component patches."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json

from engine.adapters.model_json import decode_json_object
from engine.contracts import (
    AdjudicatedTurn,
    BuiltinComponent,
    CharacterIntent,
    ComponentPatch,
    ComponentValue,
    EntityKind,
    InteractionRequest,
    PatchOperation,
    SceneTransition,
    TextModel,
)
from engine.runtime.kernel.state import EntityState, WorldState
from engine.runtime.scene.capabilities import (
    CapabilityPack,
    capabilities_for_intent,
)
from engine.adapters.place_choices import adjacent_places, inner_scenes
from engine.world.package_spec import AutonomousWorldSpec


class ModelWorldAdjudicator:
    def __init__(
        self,
        model: TextModel,
        *,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.diagnostics: list[str] = []

    def adjudicate(
        self,
        world: AutonomousWorldSpec,
        state: WorldState,
        intent: CharacterIntent,
    ) -> AdjudicatedTurn:
        scope_ids = {
            intent.actor_id,
            intent.scene_id,
            *intent.referenced_entity_ids,
        }
        scope = {
            entity_id: _entity_record(entity)
            for entity_id in sorted(scope_ids)
            if (entity := state.entities.get(entity_id)) is not None
        }
        capabilities = capabilities_for_intent(state, intent)
        prompt = (
            "你是文字世界的世界裁决器，不是小说作者。角色已提交自由意图；"
            "只判断在当前实体与局部规则下会发生什么。角色可以用任意自然动作，"
            "但你只能修改意图明确引用的实体；不能替其他完整角色决定回应。"
            "若需要对方回应，创建interaction_request。不要补写隐藏剧情。"
            "只返回JSON对象："
            '{"status":"accepted|partial|rejected","public_action":"客观发生的行动",'
            '"actor_feedback":"给行动者的第一人称反馈","observer_feedback":'
            '{"角色ID":"该角色能感知的反馈"},"patches":[{"entity_id":"...",'
            '"component_type":"presence|attributes|inventory|knowledge|relationship|'
            'interactable","data":{}}],"interaction_requests":[{"recipient_id":"...",'
            '"public_prompt":"对方实际听到或收到的请求","private_context":"可空"}],'
            '"scene_boundary":"stay|transition",'
            '"scene_transition":null或{"location_id":"...","scene_key":"..."},'
            '"item_custody_updates":[{"item_id":"...","holder_id":"角色ID或null"}],'
            '"dramatic_progress":"none|advance|decision|resolved",'
            '"scene_outcome":null或"已经发生且可观察的阶段结果"}。'
            "patch只是结果，不是动作列表；不得修改identity、layout、agent或NPC"
            "行为定义。实体当前组件状态优先于identity中的初始场景描述；行动不能"
            "重复取得已被别人持有或已经移位的物品。取得物品时必须同时更新行动者"
            "inventory.item_ids和物品presence，使后续角色看到一致状态；只观察"
            "且没有新发现时不要伪造持久补丁。public_action只能写本角色本回合"
            "单方面已经完成的事实，不能把“等待对方同意后”的条件动作写成已经"
            "发生。若物品由另一完整角色持有，只能创建interaction_request请求"
            "交付，不得叙述物品已经到手；交付必须由持有人后续回合主动完成。"
            "只要public_action已经越过当前小场景边界，就必须选择transition并"
            "填写目标场景；不能用仍指向原入口的presence补丁假装深入。凡叙述"
            "拾取、抽走、递交、放下物品，必须在item_custody_updates声明结果，"
            "并用inventory补丁实现唯一持有人；仅改变物品presence不算取得。"
            "离开当前地点时，scene_boundary 必须是 transition，"
            "scene_transition 只能从 where_i_can_go 里选，scene_key 用 default；"
            "不能把离开写成仍在原地向前迈步。进入同一地点的里间时，才从"
            "inner_scenes 里选。首次进入会由运行器完成懒渲染。角色原话由系统"
            "原样保存，不要改写。输入："
            "dramatic_progress 评价本回合是否改变了场景问题：重复查验为none，"
            "获得会改变判断的新事实为advance，作出改变承诺、关系、持有或去向"
            "的选择为decision；只有行动已经满足场景closure_signals之一，且"
            "产生可观察结果时才可标记resolved并填写scene_outcome。不能因为"
            "回合数增加或角色声称完成就收束场景。若 intent.decision 是本角色"
            "公开承担的约束，且行动已实际表达或执行该决定，至少标记decision；"
            "若行动没有兑现该决定，应partial或rejected。"
            + json.dumps(
                {
                    "world": {
                        "id": world.world_id,
                        "premise": world.premise,
                        "rules": _plain(world.rules),
                    },
                    "scene_version": intent.expected_scene_version,
                    "intent": {
                        "intent_id": intent.intent_id,
                        "actor_id": intent.actor_id,
                        "goal": intent.goal,
                        "description": intent.description,
                        "references": intent.referenced_entity_ids,
                        "speech": intent.speech,
                        "reply_to": intent.reply_to_interaction_id,
                        "decision": intent.decision,
                    },
                    "entities": scope,
                    "workflow_capabilities": [
                        {
                            "id": item.capability_id,
                            "description": item.description,
                            "mutable_components": sorted(
                                item.mutable_components
                            ),
                        }
                        for item in capabilities
                    ],
                    "where_i_can_go": adjacent_places(world, state, intent),
                    "inner_scenes": inner_scenes(world, state, intent),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        try:
            raw = self.model.complete(
                prompt, timeout_seconds=self.timeout_seconds
            )
            value = decode_json_object(raw)
            try:
                return _decode_turn(
                    value, intent, state, capabilities, world
                )
            except (TypeError, ValueError) as exc:
                repaired = decode_json_object(
                    self.model.complete(
                        prompt
                        + "\n上一次输出未通过结构与权限校验："
                        + str(exc)
                        + "。请只修正JSON结构、补丁范围和组件数据，不改变裁决事实。"
                        + "上一次输出："
                        + raw,
                        timeout_seconds=self.timeout_seconds,
                    )
                )
                return _decode_turn(
                    repaired, intent, state, capabilities, world
                )
        except Exception as exc:
            self.diagnostics.append(
                f"adjudication fallback for {intent.intent_id}: "
                f"{type(exc).__name__}: {exc}"
            )
            return fallback_adjudication(intent)


def fallback_adjudication(intent: CharacterIntent) -> AdjudicatedTurn:
    return AdjudicatedTurn(
        intent.intent_id,
        intent.actor_id,
        intent.scene_id,
        intent.expected_scene_version,
        "rejected",
        f"{intent.actor_id}的意图未能完成世界裁决，因此没有发生。",
        "这次意图没有通过世界裁决，世界状态未改变。",
        spoken_text=intent.speech,
        rule_basis=("free intent has no requested persistent effect",),
    )


def _decode_turn(
    value: object,
    intent: CharacterIntent,
    state: WorldState,
    capabilities: tuple[CapabilityPack, ...],
    world: AutonomousWorldSpec,
) -> AdjudicatedTurn:
    if not isinstance(value, dict):
        raise ValueError("adjudication response must be an object")
    status = _text(value, "status")
    public_action = _text(value, "public_action")
    actor_feedback = _text(value, "actor_feedback")
    raw_patches = value.get("patches", [])
    if not isinstance(raw_patches, list):
        raise ValueError("adjudication patches must be a list")
    patches: list[ComponentPatch] = []
    mutable_components = {
        component_type
        for capability in capabilities
        for component_type in capability.mutable_components
    }
    for raw in raw_patches:
        if not isinstance(raw, dict):
            raise ValueError("adjudication patch must be an object")
        entity_id = _text(raw, "entity_id")
        component_type = _text(raw, "component_type")
        data = raw.get("data")
        if (
            component_type not in mutable_components
            or not isinstance(data, dict)
        ):
            raise ValueError("adjudication patch is outside mutable components")
        _validate_patch_shape(
            entity_id, component_type, data, intent, state
        )
        patches.append(
            ComponentPatch(
                PatchOperation.UPSERT_COMPONENT,
                entity_id,
                component=ComponentValue(component_type, data),
            )
        )
    observer_feedback = value.get("observer_feedback", {})
    if not isinstance(observer_feedback, dict) or not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in observer_feedback.items()
    ):
        raise ValueError("observer feedback must map ids to text")
    requests = _decode_requests(
        value.get("interaction_requests", []), intent, state
    )
    boundary = _text(value, "scene_boundary")
    if boundary not in {"stay", "transition"}:
        raise ValueError("scene_boundary must be stay or transition")
    transition = _decode_transition(
        value.get("scene_transition"), intent, state, world
    )
    if (boundary == "transition") != (transition is not None):
        raise ValueError("scene boundary and transition disagree")
    _validate_custody_updates(
        value.get("item_custody_updates"), patches, intent, state
    )
    dramatic_progress = str(
        value.get("dramatic_progress") or "none"
    ).strip()
    if dramatic_progress not in {
        "none",
        "advance",
        "decision",
        "resolved",
    }:
        raise ValueError("invalid dramatic progress")
    if (
        intent.decision is not None
        and status in {"accepted", "partial"}
        and dramatic_progress in {"none", "advance"}
    ):
        dramatic_progress = "decision"
    raw_outcome = value.get("scene_outcome")
    scene_outcome = (
        None
        if raw_outcome is None
        else _text(value, "scene_outcome")
    )
    return AdjudicatedTurn(
        intent.intent_id,
        intent.actor_id,
        intent.scene_id,
        intent.expected_scene_version,
        status,
        public_action,
        actor_feedback,
        tuple(patches),
        intent.speech,
        observer_feedback,
        requests,
        ("model adjudicated against referenced entity components",),
        transition,
        dramatic_progress,
        scene_outcome,
    )


def _decode_transition(
    value: object,
    intent: CharacterIntent,
    state: WorldState,
    world: AutonomousWorldSpec,
) -> SceneTransition | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("scene transition must be an object or null")
    location_id = _text(value, "location_id")
    scene_key = _text(value, "scene_key")
    current = state.characters[intent.actor_id].location_id
    if location_id != current:
        reachable = {
            item["location_id"]
            for item in adjacent_places(world, state, intent)
        }
        if location_id not in reachable:
            raise ValueError("scene transition cannot skip map travel")
        return SceneTransition(location_id, "default")
    location = next(
        (item for item in world.locations if item.id == location_id),
        None,
    )
    if location is None or scene_key not in {
        seed.key for seed in location.scene_seeds
    }:
        raise ValueError("scene transition is not in the location outline")
    return SceneTransition(location_id, scene_key)


def _validate_custody_updates(
    value: object,
    patches: list[ComponentPatch],
    intent: CharacterIntent,
    state: WorldState,
) -> None:
    if not isinstance(value, list):
        raise ValueError("item_custody_updates must be a list")
    predicted = {
        entity_id: _item_holder(state, entity_id)
        for entity_id in intent.referenced_entity_ids
        if (
            entity := state.entities.get(entity_id)
        ) is not None
        and entity.kind is EntityKind.ITEM
    }
    for patch in patches:
        if (
            patch.component is None
            or patch.component.component_type
            != BuiltinComponent.INVENTORY.value
        ):
            continue
        item_ids = {
            str(item)
            for item in patch.component.data.get("item_ids", ())
        }
        for item_id in predicted:
            if predicted[item_id] == patch.entity_id:
                predicted[item_id] = None
        for item_id in item_ids:
            if item_id in predicted:
                predicted[item_id] = patch.entity_id
    declared: dict[str, str | None] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("custody update must be an object")
        item_id = _text(item, "item_id")
        if item_id not in predicted:
            raise ValueError("custody update item is outside intent scope")
        holder = item.get("holder_id")
        if holder is not None and (
            not isinstance(holder, str) or not holder.strip()
        ):
            raise ValueError("custody holder must be text or null")
        declared[item_id] = None if holder is None else holder.strip()
    for item_id, holder_id in declared.items():
        if predicted[item_id] != holder_id:
            raise ValueError(
                "declared item custody lacks matching inventory patches"
            )


def _decode_requests(
    value: object,
    intent: CharacterIntent,
    state: WorldState,
) -> tuple[InteractionRequest, ...]:
    if not isinstance(value, list):
        raise ValueError("interaction requests must be a list")
    requests: list[InteractionRequest] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError("interaction request must be an object")
        recipient_id = _text(raw, "recipient_id")
        recipient = state.entities.get(recipient_id)
        if (
            recipient_id not in intent.referenced_entity_ids
            or recipient is None
            or recipient.kind not in {EntityKind.CHARACTER, EntityKind.NPC}
        ):
            raise ValueError("interaction recipient is outside intent scope")
        digest = hashlib.sha256(
            f"{intent.intent_id}|{recipient_id}|{index}".encode()
        ).hexdigest()[:20]
        requests.append(
            InteractionRequest(
                f"interaction:{digest}",
                intent.actor_id,
                recipient_id,
                intent.scene_id,
                _text(raw, "public_prompt"),
                str(raw.get("private_context") or ""),
            )
        )
    return tuple(requests)


def _validate_patch_shape(
    entity_id: str,
    component_type: str,
    data: dict[str, object],
    intent: CharacterIntent,
    state: WorldState,
) -> None:
    if entity_id not in {
        intent.actor_id,
        intent.scene_id,
        *intent.referenced_entity_ids,
    }:
        raise ValueError("patch entity is outside intent scope")
    entity = state.entities.get(entity_id)
    if entity is None:
        raise ValueError("patch entity does not exist")
    if component_type == BuiltinComponent.PRESENCE.value:
        if (
            data.get("scene_id") != intent.scene_id
            or data.get("anchor_id") not in state.entities
        ):
            raise ValueError("presence patch leaves the current scene")
        holder_id = _item_holder(state, entity_id)
        if holder_id is not None and holder_id != intent.actor_id:
            raise ValueError("intent cannot move an item held by another actor")
    if component_type == BuiltinComponent.INVENTORY.value:
        item_ids = data.get("item_ids")
        if not isinstance(item_ids, (list, tuple)) or len(item_ids) != len(
            set(item_ids)
        ):
            raise ValueError("inventory item_ids must be a unique list")
        for item_id in item_ids:
            item = state.entities.get(str(item_id))
            if item is None or item.kind is not EntityKind.ITEM:
                raise ValueError("inventory references a non-item entity")
            holder_id = _item_holder(state, str(item_id))
            if holder_id is not None and holder_id != entity_id:
                raise ValueError("item is already held by another actor")
    if (
        entity_id != intent.actor_id
        and entity.kind is EntityKind.CHARACTER
        and component_type
        not in {
            BuiltinComponent.RELATIONSHIP.value,
            BuiltinComponent.KNOWLEDGE.value,
        }
    ):
        raise ValueError("intent cannot decide another character's state")


def _item_holder(state: WorldState, item_id: str) -> str | None:
    return next(
        (
            entity_id
            for entity_id, entity in state.entities.items()
            if item_id
            in entity.components.get(
                BuiltinComponent.INVENTORY.value, {}
            ).get("item_ids", ())
        ),
        None,
    )


def _entity_record(entity: EntityState) -> dict[str, object]:
    return {
        "kind": entity.kind.value,
        "version": entity.version,
        "components": _plain(entity.components),
    }


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"adjudication field {key} must be non-empty text")
    return item.strip()
