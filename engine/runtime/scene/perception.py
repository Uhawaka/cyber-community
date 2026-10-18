"""First-person projections over authoritative entity components."""

from __future__ import annotations

from collections.abc import Mapping

from engine.contracts import BuiltinComponent, EntityKind, PerceptionView
from engine.runtime.kernel.state import EntityState, WorldState


def project_perception(state: WorldState, actor_id: str) -> PerceptionView:
    actor = state.entities.get(actor_id)
    if actor is None or actor.kind is not EntityKind.CHARACTER:
        raise ValueError("perception actor must be a full character entity")
    presence = actor.components.get(BuiltinComponent.PRESENCE.value)
    if presence is None:
        raise ValueError("perception actor has no presence")
    scene_id = str(presence.get("scene_id", ""))
    scene = state.entities.get(scene_id)
    if scene is None or scene.kind is not EntityKind.SCENE:
        raise ValueError("perception actor references an unknown scene")
    visible = _visible_entities(state, scene_id)
    lines = [_scene_opening(scene)]
    anchor_id = str(presence.get("anchor_id", ""))
    anchor = state.entities.get(anchor_id)
    if anchor is not None:
        lines.append(f"我现在位于{_name(anchor)}。")
    other_lines = [
        _visible_description(state, entity_id, entity)
        for entity_id, entity in visible
        if entity_id not in {scene_id, anchor_id, actor_id}
    ]
    if other_lines:
        lines.append("我能看到：" + "；".join(other_lines) + "。")
    scene_attributes = scene.components.get(
        BuiltinComponent.ATTRIBUTES.value, {}
    )
    dramatic = scene.components.get(
        BuiltinComponent.DRAMATIC.value, {}
    )
    if (
        dramatic.get("status") == "open"
        and dramatic.get("question")
    ):
        lines.append(
            f"这一处只能看清这一层：{dramatic['question']}"
        )
        if dramatic.get("failure_pressure"):
            lines.append(
                f"这里的时限：{dramatic['failure_pressure']}"
            )
        signals = tuple(
            str(item)
            for item in dramatic.get("closure_signals", ())
        )
        if signals:
            lines.append(
                "取到这一层就离开。离开时要能看见："
                + "；".join(signals)
                + "。"
            )
        pressure_level = int(
            dramatic.get("pressure_level", 0)
        )
        decision_required = pressure_level >= int(
            dramatic.get("decision_pressure_level", 2)
        )
        if pressure_level:
            lines.append(f"场景压力已升至{pressure_level}级。")
        if decision_required:
            lines.append(
                "不能继续换一种"
                "说法查验同一线索，必须作出会改变承诺、关系、"
                "持有或去向的决定。"
            )
    else:
        decision_required = False
    recent_turns = tuple(
        item
        for item in scene_attributes.get("recent_turns", ())
        if isinstance(item, Mapping)
    )
    if recent_turns:
        lines.append(
            "刚刚已经发生："
            + "；".join(
                (
                    f"{_speaker_name(state, item.get('actor_id'))}："
                    f"{item.get('public_action', '')}"
                    + (
                        f" 原话：“{item['spoken_text']}”"
                        if item.get("spoken_text")
                        else ""
                    )
                )
                for item in recent_turns[-6:]
            )
            + "。"
        )
        if _local_voice_answered(state, recent_turns):
            lines.append(
                "这里的人已经把能说的说完了。不要再问第二遍，"
                "也不要再核对同一件东西。这一手是带着听到的离开。"
            )
    recent_world_events = tuple(
        item
        for item in scene_attributes.get(
            "recent_world_events", ()
        )
        if isinstance(item, Mapping)
    )
    if recent_world_events:
        lines.append(
            "场景最近发生的外部变化："
            + "；".join(
                str(item.get("summary", ""))
                for item in recent_world_events
                if item.get("summary")
            )
            + "。"
        )
    agent = actor.components.get(BuiltinComponent.AGENT.value, {})
    motivation = agent.get("motivation", {})
    if isinstance(motivation, Mapping) and motivation:
        lines.append(
            "我的当前承诺："
            + str(motivation.get("active_commitment", ""))
            + "；最终想要："
            + str(motivation.get("terminal_desire", ""))
            + "；不能接受："
            + str(motivation.get("sacrifice_boundary", ""))
            + "。"
        )
    last_turn = agent.get("last_turn")
    if isinstance(last_turn, Mapping) and last_turn.get("public_action"):
        lines.append(
            f"我上一回合已经做过：{last_turn['public_action']}"
        )
    pending_records = tuple(
        item
        for item in agent.get("pending_interactions", ())
        if isinstance(item, Mapping)
    )
    pending = tuple(
        str(item["interaction_id"])
        for item in pending_records
        if item.get("interaction_id")
    )
    for item in pending_records:
        prompt = str(item.get("public_prompt", "")).strip()
        initiator_id = str(item.get("initiator_id", "")).strip()
        if prompt:
            lines.append(
                f"{initiator_id or '有人'}正在等我回应：{prompt}"
                f"（回应ID：{item.get('interaction_id', '')}）"
            )
    return PerceptionView(
        actor_id,
        scene_id,
        scene.version,
        "\n".join(lines),
        tuple(entity_id for entity_id, _ in visible),
        tuple(state.knowledge.get(actor_id, ())),
        pending,
        int(dramatic.get("pressure_level", 0)),
        decision_required,
        tuple(
            str(item)
            for item in dramatic.get("closure_signals", ())
        ),
    )


def _visible_entities(
    state: WorldState, scene_id: str
) -> tuple[tuple[str, EntityState], ...]:
    scene = state.entities[scene_id]
    layout = scene.components.get(BuiltinComponent.LAYOUT.value, {})
    anchor_ids = set(str(item) for item in layout.get("anchor_ids", ()))
    selected: list[tuple[str, EntityState]] = []
    for entity_id, entity in state.entities.items():
        presence = entity.components.get(BuiltinComponent.PRESENCE.value, {})
        if (
            entity_id == scene_id
            or entity_id in anchor_ids
            or presence.get("scene_id") == scene_id
        ):
            selected.append((entity_id, entity))
    return tuple(sorted(selected, key=lambda item: item[0]))


def _scene_opening(scene: EntityState) -> str:
    identity = scene.components.get(BuiltinComponent.IDENTITY.value, {})
    name = str(identity.get("name", "这个地方"))
    description = str(identity.get("description", "")).strip()
    return f"我身处{name}。" + (f"{description}" if description else "")


def _local_voice_answered(
    state: WorldState, recent_turns: tuple[Mapping[str, object], ...]
) -> bool:
    """A place has given its layer once someone who is not a full character speaks it."""

    for item in recent_turns:
        if not str(item.get("spoken_text") or "").strip():
            continue
        actor_id = str(item.get("actor_id") or "")
        if actor_id and actor_id not in state.characters:
            return True
    return False


def _speaker_name(state: WorldState, actor_id: object) -> str:
    entity = state.entities.get(str(actor_id or ""))
    if entity is None:
        return "有人"
    return _name(entity)


def _name(entity: EntityState) -> str:
    identity = entity.components.get(BuiltinComponent.IDENTITY.value, {})
    return str(identity.get("name", "未命名实体"))


def _visible_description(
    state: WorldState, entity_id: str, entity: EntityState
) -> str:
    identity = entity.components.get(BuiltinComponent.IDENTITY.value, {})
    name = str(identity.get("name", entity_id))
    description = str(identity.get("description", "")).strip()
    interactable = entity.components.get(
        BuiltinComponent.INTERACTABLE.value, {}
    )
    hints = tuple(
        str(item) for item in interactable.get("interaction_hints", ())
    )
    result = name + (f"（{description}）" if description else "")
    presence = entity.components.get(BuiltinComponent.PRESENCE.value, {})
    current_anchor = state.entities.get(str(presence.get("anchor_id", "")))
    if current_anchor is not None:
        result += f"，当前在{_name(current_anchor)}"
    holder = next(
        (
            candidate
            for candidate in state.entities.values()
            if entity_id
            in candidate.components.get(
                BuiltinComponent.INVENTORY.value, {}
            ).get("item_ids", ())
        ),
        None,
    )
    if holder is not None:
        result += f"，当前由{_name(holder)}持有"
    if hints:
        result += f"，可以尝试{'、'.join(hints)}"
    return result
