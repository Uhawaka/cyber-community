"""Stable, immutable source facts consumed by the narrative layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class NarrativeChange:
    category: str
    subject_id: str
    target_id: str | None
    value: str
    is_cost: bool = False


@dataclass(frozen=True)
class SourceEventView:
    """The only event shape visible to narrative code."""

    source_event_id: str
    world_time: float
    kind: str
    actor_ids: tuple[str, ...]
    observer_ids: tuple[str, ...]
    location_id: str | None
    target_id: str | None
    goal: str | None
    summary: str
    utterance: str | None
    causal_source_ids: tuple[str, ...]
    changes: tuple[NarrativeChange, ...]
    unresolved_points: tuple[str, ...]
    facts: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor_ids", tuple(self.actor_ids))
        object.__setattr__(self, "observer_ids", tuple(self.observer_ids))
        object.__setattr__(self, "causal_source_ids", tuple(self.causal_source_ids))
        object.__setattr__(self, "changes", tuple(self.changes))
        object.__setattr__(self, "unresolved_points", tuple(self.unresolved_points))
        object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))


@runtime_checkable
class SourceEvent(Protocol):
    """Structural protocol intentionally independent of runtime packages."""


def adapt_source_event(event: object) -> SourceEventView:
    if isinstance(event, SourceEventView):
        return event
    if hasattr(event, "event_id") and hasattr(event, "state_version_after"):
        return _adapt_turn_event(event)
    if hasattr(event, "sequence") and hasattr(event, "event_type"):
        return _adapt_world_event(event)
    raise TypeError(f"unsupported narrative source event: {type(event).__name__}")


def _engine_outcome(outcome: str) -> bool:
    return outcome == "在场完整角色均已提交可约束后续行为的决定。"


def _spoken_summary(action: str | None, spoken: str | None) -> str | None:
    """Prefer the committed line over a stub that only names the listener."""

    if not spoken:
        return None
    if action and spoken in action:
        return action
    if action and "回应了" in action:
        name = action.split("回应了", 1)[0].strip("。 ")
        if name:
            return f"{name}说：“{spoken}”"
    return f"{spoken}"


def adapt_source_events(events: Sequence[object]) -> tuple[SourceEventView, ...]:
    return tuple(adapt_source_event(event) for event in events)


def _adapt_turn_event(event: object) -> SourceEventView:
    action = _mapping(getattr(event, "action", None))
    intention = _mapping(getattr(event, "intention", None))
    actor = str(getattr(event, "actor_id"))
    target = _first_text(action, "target_id", "listener_id", "subject_id")
    location = _first_text(action, "location_id", "destination_id", "origin_id")
    utterance = _first_text(action, "utterance", "dialogue")
    changes = tuple(
        NarrativeChange(
            category=str(getattr(delta, "kind", "state_change")),
            subject_id=str(getattr(delta, "subject_id", actor)),
            target_id=_optional_text(getattr(delta, "target_id", None)),
            value=_stable_value(getattr(delta, "value", None)),
            is_cost=_is_cost(str(getattr(delta, "kind", "")), getattr(delta, "value", None)),
        )
        for delta in tuple(getattr(event, "deltas", ()))
    )
    if not changes:
        changes = (
            NarrativeChange(
                "state_version",
                actor,
                None,
                (
                    f"{getattr(event, 'state_version_before')}→"
                    f"{getattr(event, 'state_version_after')}"
                ),
            ),
        )
    causal = tuple(
        dict.fromkeys(
            (
                *tuple(str(item) for item in getattr(event, "consumed_anchor_ids", ())),
                *_text_sequence(action.get("source_event_ids")),
            )
        )
    )
    goal = _first_text(intention, "goal", "objective", "reason")
    unresolved = _text_sequence(intention.get("unresolved_points"))
    if goal and bool(intention.get("pending", False)):
        unresolved = (*unresolved, goal)
    return SourceEventView(
        source_event_id=str(getattr(event, "event_id")),
        world_time=float(getattr(event, "world_time")),
        kind=str(getattr(event, "kind")),
        actor_ids=(actor,),
        observer_ids=tuple(str(item) for item in getattr(event, "observers", ())),
        location_id=location,
        target_id=target,
        goal=goal,
        summary=str(getattr(event, "summary")),
        utterance=utterance,
        causal_source_ids=causal,
        changes=changes,
        unresolved_points=unresolved,
        facts={key: _stable_value(value) for key, value in action.items()},
    )


def _adapt_world_event(event: object) -> SourceEventView:
    data = _mapping(getattr(event, "data", None))
    delta = getattr(event, "delta")
    actor = _optional_text(getattr(event, "actor_id", None))
    event_type = getattr(event, "event_type")
    kind = str(event_type.value if isinstance(event_type, Enum) else event_type)
    sequence = int(getattr(event, "sequence"))
    changes: list[NarrativeChange] = []
    for move in tuple(getattr(delta, "moves", ())):
        changes.append(
            NarrativeChange(
                "move",
                str(move.character_id),
                str(move.destination_id),
                f"{move.origin_id}→{move.destination_id}",
            )
        )
    for category in ("resources", "inventories", "needs", "relationships"):
        for change in tuple(getattr(delta, category, ())):
            subject = _change_subject(change)
            target = _change_target(change)
            amount = int(getattr(change, "amount"))
            changes.append(
                NarrativeChange(
                    category.rstrip("s"),
                    subject,
                    target,
                    f"{amount:+d}",
                    is_cost=(category == "needs" and amount > 0)
                    or (category in {"resources", "inventories"} and amount < 0),
                )
            )
    for patch in tuple(getattr(delta, "entity_patches", ())):
        operation = getattr(patch, "operation", "component_patch")
        operation_value = getattr(operation, "value", operation)
        component = getattr(patch, "component", None)
        component_type = (
            getattr(component, "component_type", None)
            or getattr(patch, "component_type", None)
            or "entity"
        )
        changes.append(
            NarrativeChange(
                str(component_type),
                str(getattr(patch, "entity_id", "world")),
                None,
                str(operation_value),
            )
        )
    unresolved: list[str] = []
    for plan in tuple(getattr(delta, "plans", ())):
        value = " / ".join(str(item) for item in plan.plan)
        changes.append(NarrativeChange("plan", str(plan.character_id), None, value))
        if value:
            unresolved.append(value)
    location = (
        _first_text(data, "scene_id", "location_id")
        if kind
        in {
            "scene_instantiated",
            "scene_entered",
            "scene_evolved",
            "turn_resolved",
        }
        else _first_text(
            data, "location_id", "scene_id", "destination_id", "origin_id"
        )
    )
    target = _first_text(
        data,
        "target_id",
        "listener_id",
        "resource_id",
        "passage_id",
    )
    if target is None and kind == "turn_resolved":
        target = next(
            iter(_text_sequence(data.get("referenced_entity_ids"))),
            None,
        )
    utterance = _first_text(data, "utterance", "spoken_text")
    summary = _first_text(data, "summary")
    scene_description, scene_elements = _scene_material(delta)
    if summary is None and kind == "scene_instantiated":
        summary = scene_description
    if summary is None and kind == "gate_opened":
        summary = _first_text(data, "prompt")
    if summary is None and kind == "inspected":
        summary = _first_text(data, "finding")
    if summary is None and kind == "user_intervention":
        summary = _first_text(data, "observation", "prompt")
    if summary is None and kind == "turn_resolved":
        action = _first_text(data, "public_action")
        outcome = _first_text(data, "scene_outcome")
        spoken = _first_text(data, "spoken_text")
        summary = _spoken_summary(action, spoken) or (
            f"{action} 阶段结果：{outcome}"
            if action and outcome and not _engine_outcome(outcome)
            else action or outcome
        )
    if summary is None:
        summary = _world_summary(kind, actor, location, target)
    causal = tuple(
        dict.fromkeys(
            (
                *_text_sequence(data.get("source_event_ids")),
                *_text_sequence(data.get("caused_by")),
            )
        )
    )
    goal = _first_text(data, "goal", "objective", "reason")
    unresolved.extend(_text_sequence(data.get("unresolved_points")))
    facts = {key: _stable_value(value) for key, value in data.items()}
    if scene_description:
        facts["scene_description"] = scene_description
    if scene_elements:
        facts["scene_elements"] = "；".join(scene_elements)
    for patch in tuple(getattr(delta, "entity_patches", ())):
        components = [getattr(patch, "component", None)]
        entity = getattr(patch, "entity", None)
        components.extend(tuple(getattr(entity, "components", ())))
        for component in components:
            component_type = getattr(component, "component_type", None)
            if component_type is None:
                continue
            facts[
                (
                    f"component:{getattr(patch, 'entity_id', 'world')}:"
                    f"{component_type}"
                )
            ] = _stable_value(getattr(component, "data", None))
    return SourceEventView(
        source_event_id=f"world-{sequence:06d}",
        world_time=float(data.get("world_time", getattr(event, "tick"))),
        kind=kind,
        actor_ids=(actor,) if actor else (),
        observer_ids=tuple(str(item) for item in getattr(event, "observers", ())),
        location_id=location,
        target_id=target,
        goal=goal,
        summary=summary,
        utterance=utterance,
        causal_source_ids=causal,
        changes=tuple(changes),
        unresolved_points=tuple(dict.fromkeys(unresolved)),
        facts=facts,
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _scene_material(delta: object) -> tuple[str | None, tuple[str, ...]]:
    description: str | None = None
    elements: list[str] = []
    for patch in tuple(getattr(delta, "entity_patches", ())):
        entity = getattr(patch, "entity", None)
        if entity is None:
            continue
        identity = next(
            (
                component
                for component in getattr(entity, "components", ())
                if getattr(component, "component_type", None)
                == "identity"
            ),
            None,
        )
        if identity is None:
            continue
        data = getattr(identity, "data", {})
        name = str(data.get("name", "")).strip()
        detail = str(data.get("description", "")).strip()
        kind = getattr(getattr(entity, "kind", None), "value", "")
        if kind == "scene":
            description = detail or name
        elif name and kind in {"anchor", "item", "npc"}:
            elements.append(name + (f"：{detail}" if detail else ""))
    return description, tuple(elements)


def _first_text(values: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = values.get(key)
        if value is not None and not isinstance(value, (dict, list, tuple, set)):
            return str(value)
    return None


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _text_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(item) for item in value)
    return (str(value),) if value else ()


def _stable_value(value: object) -> str:
    if isinstance(value, Mapping):
        return ", ".join(
            f"{key}={_stable_value(item)}" for key, item in sorted(value.items())
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _change_subject(change: object) -> str:
    for name in ("character_id", "owner_id", "source_id"):
        value = getattr(change, name, None)
        if value is not None:
            return str(value)
    return "world"


def _change_target(change: object) -> str | None:
    for name in ("item_id", "target_id", "need"):
        value = getattr(change, name, None)
        if value is not None:
            return str(value)
    return None


def _is_cost(kind: str, value: object) -> bool:
    return "cost" in kind or "consume" in kind or "breach" in kind or (
        isinstance(value, (int, float)) and value < 0
    )


def _world_summary(
    kind: str, actor: str | None, location: str | None, target: str | None
) -> str:
    parts = [actor or "world", kind]
    if target:
        parts.append(target)
    if location:
        parts.append(f"at {location}")
    return " ".join(parts)
