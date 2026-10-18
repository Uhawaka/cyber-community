"""Lossless JSON codec for typed runtime events."""

from __future__ import annotations

from typing import Any, Mapping

from engine.contracts import (
    ComponentPatch,
    ComponentValue,
    EntityKind,
    EntitySpec,
    PatchOperation,
)
from engine.runtime.kernel.events import (
    EVENT_LOG_SCHEMA_VERSION,
    ActionRecord,
    AvatarPresenceDelta,
    CharacterDelta,
    Delta,
    DisclosureDelta,
    EventPersistenceError,
    EventType,
    MoveDelta,
    NeedDelta,
    KnowledgeDelta,
    PlanDelta,
    QuantityDelta,
    RelationshipDelta,
    SchemeDelta,
    SoulDelta,
    WorldEvent,
)


def event_record(event: WorldEvent) -> dict[str, Any]:
    return {
        "schema_version": EVENT_LOG_SCHEMA_VERSION,
        "world_hash": event.world_hash,
        "sequence": event.sequence,
        "event": {
            "sequence": event.sequence,
            "tick": event.tick,
            "event_type": event.event_type.value,
            "actor_id": event.actor_id,
            "observers": list(event.observers),
            "delta": {
                "characters": [
                    {
                        "character_id": item.character_id,
                        "display_name": item.display_name,
                        "location_id": item.location_id,
                        "needs": dict(item.needs),
                        "goals": list(item.goals),
                        "participant_kind": item.participant_kind,
                    }
                    for item in event.delta.characters
                ],
                "avatar_presence": [
                    {"character_id": item.character_id, "active": item.active}
                    for item in event.delta.avatar_presence
                ],
                "moves": [vars(item) for item in event.delta.moves],
                "resources": [vars(item) for item in event.delta.resources],
                "inventories": [vars(item) for item in event.delta.inventories],
                "needs": [vars(item) for item in event.delta.needs],
                "relationships": [vars(item) for item in event.delta.relationships],
                "knowledge": [vars(item) for item in event.delta.knowledge],
                "disclosures": [
                    vars(item) for item in event.delta.disclosures
                ],
                "plans": [
                    {"character_id": item.character_id, "plan": list(item.plan)}
                    for item in event.delta.plans
                ],
                "actions": [vars(item) for item in event.delta.actions],
                "schemes": [
                    {
                        **vars(item),
                        "target_state": list(item.target_state),
                    }
                    for item in event.delta.schemes
                ],
                "souls": [
                    {
                        **vars(item),
                        "value": _encode_value(item.value),
                        "evidence_sequences": list(item.evidence_sequences),
                    }
                    for item in event.delta.souls
                ],
                "entity_patches": [
                    _component_patch_record(item)
                    for item in event.delta.entity_patches
                ],
                "advance_time": event.delta.advance_time,
                "advance_tick": event.delta.advance_tick,
            },
            "data": _encode_value(dict(event.data)),
            "opportunity_id": event.opportunity_id,
            "pre_state_hash": event.pre_state_hash,
            "world_hash": event.world_hash,
            "deterministic_cursor": event.deterministic_cursor,
            "target_entity_id": event.target_entity_id,
            "rule_basis": list(event.rule_basis),
        },
    }


def event_from_record(record: Mapping[str, Any], *, world_hash: str) -> WorldEvent:
    if record.get("schema_version") != EVENT_LOG_SCHEMA_VERSION:
        raise EventPersistenceError("event log schema version mismatch")
    if record.get("world_hash") != world_hash:
        raise EventPersistenceError("event log world hash mismatch")
    value = record["event"]
    if record.get("sequence") != value.get("sequence"):
        raise EventPersistenceError("record and event sequence mismatch")
    raw = value.get("delta", {})
    delta = Delta(
        characters=tuple(
            CharacterDelta(
                item["character_id"],
                item["display_name"],
                item["location_id"],
                item["needs"],
                tuple(item.get("goals", ())),
                item.get("participant_kind", "avatar"),
            )
            for item in raw.get("characters", ())
        ),
        avatar_presence=tuple(
            AvatarPresenceDelta(**item) for item in raw.get("avatar_presence", ())
        ),
        moves=tuple(MoveDelta(**item) for item in raw.get("moves", ())),
        resources=tuple(QuantityDelta(**item) for item in raw.get("resources", ())),
        inventories=tuple(QuantityDelta(**item) for item in raw.get("inventories", ())),
        needs=tuple(NeedDelta(**item) for item in raw.get("needs", ())),
        relationships=tuple(
            RelationshipDelta(**item) for item in raw.get("relationships", ())
        ),
        knowledge=tuple(
            KnowledgeDelta(**item) for item in raw.get("knowledge", ())
        ),
        disclosures=tuple(
            DisclosureDelta(**item)
            for item in raw.get("disclosures", ())
        ),
        plans=tuple(
            PlanDelta(item["character_id"], tuple(item.get("plan", ())))
            for item in raw.get("plans", ())
        ),
        actions=tuple(ActionRecord(**item) for item in raw.get("actions", ())),
        schemes=tuple(
            SchemeDelta(
                item["scheme_id"],
                item["character_id"],
                tuple(item.get("target_state", ())),
                float(item.get("progress", 0.0)),
                item["status"],
            )
            for item in raw.get("schemes", ())
        ),
        souls=tuple(
            SoulDelta(
                item["character_id"],
                item["trait"],
                _decode_value(item.get("value")),
                item["expected_version"],
                tuple(item.get("evidence_sequences", ())),
            )
            for item in raw.get("souls", ())
        ),
        entity_patches=tuple(
            _component_patch_from_record(item)
            for item in raw.get("entity_patches", ())
        ),
        advance_time=raw.get("advance_time", 0),
        advance_tick=raw.get("advance_tick", 0),
    )
    return WorldEvent(
        sequence=value["sequence"],
        tick=value["tick"],
        event_type=EventType(value["event_type"]),
        actor_id=value.get("actor_id"),
        observers=tuple(value.get("observers", ())),
        delta=delta,
        data=_decode_value(value.get("data", {})),
        opportunity_id=value.get("opportunity_id"),
        pre_state_hash=value.get("pre_state_hash"),
        world_hash=value.get("world_hash"),
        deterministic_cursor=value.get("deterministic_cursor"),
        target_entity_id=value.get("target_entity_id"),
        rule_basis=tuple(value.get("rule_basis", ())),
    )


def _encode_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return {"$type": "tuple", "items": [_encode_value(item) for item in value]}
    if isinstance(value, Mapping):
        return {str(key): _encode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_encode_value(item) for item in value]
    return value


def _component_patch_record(value: ComponentPatch) -> dict[str, Any]:
    return {
        "operation": value.operation.value,
        "entity_id": value.entity_id,
        "expected_entity_version": value.expected_entity_version,
        "entity": (
            {
                "entity_id": value.entity.entity_id,
                "kind": value.entity.kind.value,
                "version": value.entity.version,
                "components": [
                    {
                        "component_type": item.component_type,
                        "data": _encode_value(dict(item.data)),
                    }
                    for item in value.entity.components
                ],
            }
            if value.entity is not None
            else None
        ),
        "component": (
            {
                "component_type": value.component.component_type,
                "data": _encode_value(dict(value.component.data)),
            }
            if value.component is not None
            else None
        ),
        "component_type": value.component_type,
    }


def _component_patch_from_record(value: Mapping[str, Any]) -> ComponentPatch:
    raw_entity = value.get("entity")
    entity = (
        EntitySpec(
            str(raw_entity["entity_id"]),
            EntityKind(str(raw_entity["kind"])),
            tuple(
                ComponentValue(
                    str(item["component_type"]),
                    _decode_value(item.get("data", {})),
                )
                for item in raw_entity.get("components", ())
            ),
            int(raw_entity.get("version", 0)),
        )
        if isinstance(raw_entity, Mapping)
        else None
    )
    raw_component = value.get("component")
    component = (
        ComponentValue(
            str(raw_component["component_type"]),
            _decode_value(raw_component.get("data", {})),
        )
        if isinstance(raw_component, Mapping)
        else None
    )
    return ComponentPatch(
        PatchOperation(str(value["operation"])),
        str(value["entity_id"]),
        value.get("expected_entity_version"),
        entity,
        component,
        value.get("component_type"),
    )


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$type", "items"} and value["$type"] == "tuple":
            return tuple(_decode_value(item) for item in value["items"])
        return {key: _decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    return value
