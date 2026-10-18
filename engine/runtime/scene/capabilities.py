"""Workflow-owned interaction capabilities over typed entity components."""

from __future__ import annotations

from dataclasses import dataclass

from engine.contracts import BuiltinComponent, CharacterIntent
from engine.runtime.kernel.state import WorldState


@dataclass(frozen=True)
class CapabilityPack:
    capability_id: str
    description: str
    actor_components: frozenset[str]
    target_any_components: frozenset[str]
    mutable_components: frozenset[str]


BUILTIN_CAPABILITIES = (
    CapabilityPack(
        "social",
        "对话、请求、拒绝、披露信息并形成关系或知识变化",
        frozenset({BuiltinComponent.AGENT.value}),
        frozenset(
            {
                BuiltinComponent.AGENT.value,
                BuiltinComponent.AMBIENT_BEHAVIOR.value,
            }
        ),
        frozenset(
            {
                BuiltinComponent.KNOWLEDGE.value,
                BuiltinComponent.RELATIONSHIP.value,
            }
        ),
    ),
    CapabilityPack(
        "trade",
        "在双方库存与场景物件约束内报价、赠予或交换",
        frozenset({BuiltinComponent.INVENTORY.value}),
        frozenset(
            {
                BuiltinComponent.INVENTORY.value,
                BuiltinComponent.INTERACTABLE.value,
            }
        ),
        frozenset(
            {
                BuiltinComponent.INVENTORY.value,
                BuiltinComponent.PRESENCE.value,
                BuiltinComponent.ATTRIBUTES.value,
            }
        ),
    ),
    CapabilityPack(
        "conflict",
        "依据双方属性进行粗粒度冲突、受伤、退让或退出，不模拟招式和碰撞",
        frozenset({BuiltinComponent.ATTRIBUTES.value}),
        frozenset({BuiltinComponent.ATTRIBUTES.value}),
        frozenset(
            {
                BuiltinComponent.ATTRIBUTES.value,
                BuiltinComponent.PRESENCE.value,
            }
        ),
    ),
    CapabilityPack(
        "scene_interaction",
        "在场景锚点间活动并使用可交互物件",
        frozenset({BuiltinComponent.PRESENCE.value}),
        frozenset(
            {
                BuiltinComponent.INTERACTABLE.value,
                BuiltinComponent.LAYOUT.value,
            }
        ),
        frozenset(
            {
                BuiltinComponent.PRESENCE.value,
                BuiltinComponent.INVENTORY.value,
                BuiltinComponent.ATTRIBUTES.value,
                BuiltinComponent.INTERACTABLE.value,
            }
        ),
    ),
)


def capabilities_for_intent(
    state: WorldState, intent: CharacterIntent
) -> tuple[CapabilityPack, ...]:
    actor = state.entities[intent.actor_id]
    actor_components = set(actor.components)
    target_components = {
        component_type
        for entity_id in intent.referenced_entity_ids
        if entity_id in state.entities
        for component_type in state.entities[entity_id].components
    }
    selected = [
        capability
        for capability in BUILTIN_CAPABILITIES
        if capability.actor_components.issubset(actor_components)
        and (
            not capability.target_any_components
            or capability.target_any_components.intersection(
                target_components
            )
        )
    ]
    return tuple(selected)
