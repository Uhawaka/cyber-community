"""Immutable replayable state for the autonomous runtime."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping

from engine.contracts import (
    BuiltinComponent,
    EntityKind,
    PatchOperation,
)
from engine.runtime.kernel.events import ActionRecord, Delta, EventValidationError
from engine.runtime.character.contracts import Scheme, SchemeStatus


def _copy_nested(value: Mapping[str, Mapping[str, int]]) -> dict[str, dict[str, int]]:
    return {key: dict(items) for key, items in value.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class SoulOverlay:
    version: int = 0
    traits: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    last_evolution_tick: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "traits", MappingProxyType(dict(self.traits)))
        object.__setattr__(
            self,
            "evidence",
            MappingProxyType(
                {key: tuple(sequences) for key, sequences in self.evidence.items()}
            ),
        )


@dataclass(frozen=True)
class CharacterState:
    location_id: str
    needs: Mapping[str, int]
    short_plan: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    participant_kind: str = "npc"
    display_name: str = ""
    recent_actions: tuple[ActionRecord, ...] = ()
    active: bool = True
    soul_overlay: SoulOverlay = field(default_factory=SoulOverlay)

    def __post_init__(self) -> None:
        object.__setattr__(self, "needs", MappingProxyType(dict(self.needs)))
        object.__setattr__(self, "recent_actions", tuple(self.recent_actions))


@dataclass(frozen=True)
class EntityState:
    kind: EntityKind
    version: int
    components: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        if self.version < 0:
            raise ValueError("entity version must be non-negative")
        object.__setattr__(
            self,
            "components",
            MappingProxyType(
                {
                    key: MappingProxyType(dict(value))
                    for key, value in self.components.items()
                }
            ),
        )


@dataclass(frozen=True)
class WorldState:
    world_id: str
    world_hash: str
    seed: int
    tick: int
    world_time: int
    characters: Mapping[str, CharacterState]
    resources: Mapping[str, int]
    inventories: Mapping[str, Mapping[str, int]]
    relationships: Mapping[str, Mapping[str, int]]
    location_ids: tuple[str, ...] = ()
    schemes: Mapping[str, Scheme[tuple[str, ...]]] = field(default_factory=dict)
    knowledge: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    disclosures: Mapping[str, Mapping[str, tuple[str, ...]]] = field(
        default_factory=dict
    )
    facts: Mapping[str, str] = field(default_factory=dict)
    entities: Mapping[str, EntityState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "characters", MappingProxyType(dict(self.characters)))
        object.__setattr__(self, "resources", MappingProxyType(dict(self.resources)))
        object.__setattr__(
            self,
            "inventories",
            MappingProxyType(
                {
                    key: MappingProxyType(dict(items))
                    for key, items in self.inventories.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "relationships",
            MappingProxyType(
                {
                    key: MappingProxyType(dict(items))
                    for key, items in self.relationships.items()
                }
            ),
        )
        object.__setattr__(self, "location_ids", tuple(sorted(set(self.location_ids))))
        object.__setattr__(self, "schemes", MappingProxyType(dict(self.schemes)))
        object.__setattr__(
            self,
            "knowledge",
            MappingProxyType(
                {
                    key: tuple(dict.fromkeys(values))
                    for key, values in self.knowledge.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "disclosures",
            MappingProxyType(
                {
                    speaker: MappingProxyType(
                        {
                            listener: tuple(dict.fromkeys(facts))
                            for listener, facts in listeners.items()
                        }
                    )
                    for speaker, listeners in self.disclosures.items()
                }
            ),
        )
        object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))
        object.__setattr__(self, "entities", MappingProxyType(dict(self.entities)))

    def state_hash(self) -> str:
        """Stable precondition hash used by opportunities and event provenance."""

        value = {
            "world_id": self.world_id,
            "world_hash": self.world_hash,
            "seed": self.seed,
            "tick": self.tick,
            "world_time": self.world_time,
            "characters": {
                key: {
                    "location_id": item.location_id,
                    "needs": dict(item.needs),
                    "short_plan": item.short_plan,
                    "goals": item.goals,
                    "participant_kind": item.participant_kind,
                    "display_name": item.display_name,
                    "recent_actions": [
                        {
                            "kind": action.kind,
                            "target_id": action.target_id,
                            "tick": action.tick,
                        }
                        for action in item.recent_actions
                    ],
                    "active": item.active,
                    "soul_overlay": {
                        "version": item.soul_overlay.version,
                        "traits": dict(item.soul_overlay.traits),
                        "evidence": {
                            trait: sequences
                            for trait, sequences in item.soul_overlay.evidence.items()
                        },
                        "last_evolution_tick": item.soul_overlay.last_evolution_tick,
                    },
                }
                for key, item in self.characters.items()
            },
            "resources": dict(self.resources),
            "inventories": {
                key: dict(items) for key, items in self.inventories.items()
            },
            "relationships": {
                key: dict(items) for key, items in self.relationships.items()
            },
            "knowledge": {
                key: list(items) for key, items in self.knowledge.items()
            },
            "disclosures": {
                speaker: {
                    listener: list(facts)
                    for listener, facts in listeners.items()
                }
                for speaker, listeners in self.disclosures.items()
            },
            "facts": dict(self.facts),
            "entities": {
                entity_id: {
                    "kind": entity.kind.value,
                    "version": entity.version,
                    "components": {
                        component_type: _json_value(data)
                        for component_type, data in entity.components.items()
                    },
                }
                for entity_id, entity in self.entities.items()
            },
            "location_ids": self.location_ids,
            "schemes": {
                key: {
                    "character_id": item.character_id,
                    "target_state": item.target_state,
                    "progress": item.progress,
                    "status": item.status.value,
                }
                for key, item in self.schemes.items()
            },
        }
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def apply(self, delta: Delta) -> "WorldState":
        """Validate a whole delta against copies, then return the committed state."""

        characters = dict(self.characters)
        resources = dict(self.resources)
        inventories = _copy_nested(self.inventories)
        relationships = _copy_nested(self.relationships)
        schemes = dict(self.schemes)
        knowledge = {
            key: list(items) for key, items in self.knowledge.items()
        }
        disclosures = {
            speaker: {
                listener: list(facts)
                for listener, facts in listeners.items()
            }
            for speaker, listeners in self.disclosures.items()
        }
        entities = dict(self.entities)

        for addition in delta.characters:
            if addition.character_id in characters:
                raise EventValidationError("character already exists")
            if self.location_ids and addition.location_id not in self.location_ids:
                raise EventValidationError("unknown character entry location")
            characters[addition.character_id] = CharacterState(
                location_id=addition.location_id,
                needs=addition.needs,
                short_plan=addition.goals[:3],
                goals=addition.goals,
                participant_kind=addition.participant_kind,
                display_name=addition.display_name,
                active=True,
            )
            inventories[addition.character_id] = {}
            knowledge[addition.character_id] = []
            disclosures[addition.character_id] = {}
            relationships[addition.character_id] = {
                character_id: 0
                for character_id in characters
                if character_id != addition.character_id
            }
            for character_id in characters:
                if character_id != addition.character_id:
                    relationships.setdefault(character_id, {})[
                        addition.character_id
                    ] = 0
        for presence in delta.avatar_presence:
            character = characters.get(presence.character_id)
            if character is None or character.participant_kind != "avatar":
                raise EventValidationError("avatar presence requires a known avatar")
            characters[presence.character_id] = replace(
                character, active=presence.active
            )
        for move in delta.moves:
            character = characters.get(move.character_id)
            if character is None or character.location_id != move.origin_id:
                raise EventValidationError("move origin does not match current state")
            if self.location_ids and move.destination_id not in self.location_ids:
                raise EventValidationError("unknown move destination")
            characters[move.character_id] = replace(
                character, location_id=move.destination_id
            )
        for change in delta.resources:
            if change.item_id not in resources:
                raise EventValidationError("unknown resource")
            updated = resources[change.item_id] + change.amount
            if updated < 0:
                raise EventValidationError("resource quantity cannot be negative")
            resources[change.item_id] = updated
        for change in delta.inventories:
            if change.owner_id not in characters:
                raise EventValidationError("unknown inventory owner")
            inventory = inventories.setdefault(change.owner_id, {})
            updated = inventory.get(change.item_id, 0) + change.amount
            if updated < 0:
                raise EventValidationError("inventory quantity cannot be negative")
            inventory[change.item_id] = updated
        for change in delta.needs:
            character = characters.get(change.character_id)
            if character is None:
                raise EventValidationError("unknown character need owner")
            needs = dict(character.needs)
            needs[change.need] = min(100, max(0, needs.get(change.need, 0) + change.amount))
            characters[change.character_id] = replace(character, needs=needs)
        for change in delta.relationships:
            if change.source_id not in characters or change.target_id not in characters:
                raise EventValidationError("unknown relationship participant")
            relation = relationships.setdefault(change.source_id, {})
            relation[change.target_id] = min(
                100, max(-100, relation.get(change.target_id, 0) + change.amount)
            )
        for change in delta.knowledge:
            if (
                change.character_id not in characters
                or (
                    change.source_id != "world"
                    and change.source_id not in characters
                )
            ):
                raise EventValidationError("unknown knowledge participant")
            if change.fact_id not in self.facts:
                raise EventValidationError("unknown knowledge fact")
            facts = knowledge.setdefault(change.character_id, [])
            if change.fact_id not in facts:
                facts.append(change.fact_id)
        for change in delta.disclosures:
            if (
                change.speaker_id not in characters
                or change.listener_id not in characters
            ):
                raise EventValidationError("unknown disclosure participant")
            facts = disclosures.setdefault(
                change.speaker_id, {}
            ).setdefault(change.listener_id, [])
            if change.fact_id not in facts:
                facts.append(change.fact_id)
        for change in delta.plans:
            character = characters.get(change.character_id)
            if character is None:
                raise EventValidationError("unknown plan owner")
            characters[change.character_id] = replace(character, short_plan=change.plan[:3])
        for action in delta.actions:
            character = characters.get(action.character_id)
            if character is None:
                raise EventValidationError("unknown action owner")
            if action.tick != self.tick:
                raise EventValidationError("action tick must match current state")
            characters[action.character_id] = replace(
                character,
                recent_actions=(character.recent_actions + (action,))[-8:],
            )
        for change in delta.schemes:
            if change.character_id not in characters:
                raise EventValidationError("unknown scheme owner")
            schemes[change.scheme_id] = Scheme(
                scheme_id=change.scheme_id,
                character_id=change.character_id,
                target_state=tuple(change.target_state),
                progress=change.progress,
                status=SchemeStatus(change.status),
            )
        for change in delta.souls:
            character = characters.get(change.character_id)
            if character is None:
                raise EventValidationError("unknown soul owner")
            overlay = character.soul_overlay
            if overlay.version != change.expected_version:
                raise EventValidationError("soul overlay version conflict")
            traits = dict(overlay.traits)
            traits[change.trait] = change.value
            evidence = dict(overlay.evidence)
            evidence[change.trait] = change.evidence_sequences
            characters[change.character_id] = replace(
                character,
                soul_overlay=SoulOverlay(
                    version=overlay.version + 1,
                    traits=traits,
                    evidence=evidence,
                    last_evolution_tick=self.tick,
                ),
            )
        for patch in delta.entity_patches:
            if patch.operation is PatchOperation.CREATE_ENTITY:
                if patch.entity_id in entities or patch.entity is None:
                    raise EventValidationError("entity already exists")
                entities[patch.entity_id] = EntityState(
                    patch.entity.kind,
                    patch.entity.version,
                    {
                        item.component_type: dict(item.data)
                        for item in patch.entity.components
                    },
                )
                continue
            current = entities.get(patch.entity_id)
            if current is None:
                raise EventValidationError("unknown patch entity")
            if (
                patch.expected_entity_version is not None
                and current.version != patch.expected_entity_version
            ):
                raise EventValidationError("entity version conflict")
            components = {
                key: dict(value) for key, value in current.components.items()
            }
            if patch.operation is PatchOperation.UPSERT_COMPONENT:
                if patch.component is None:
                    raise EventValidationError("component patch is missing")
                components[patch.component.component_type] = dict(
                    patch.component.data
                )
            else:
                if patch.component_type not in components:
                    raise EventValidationError("cannot remove missing component")
                del components[patch.component_type]
            entities[patch.entity_id] = EntityState(
                current.kind, current.version + 1, components
            )
        for entity_id, entity in entities.items():
            presence = entity.components.get(BuiltinComponent.PRESENCE.value)
            if presence is None:
                continue
            scene_id = presence.get("scene_id")
            anchor_id = presence.get("anchor_id")
            if (
                scene_id not in entities
                or entities[scene_id].kind is not EntityKind.SCENE
                or anchor_id not in entities
                or entities[anchor_id].kind is not EntityKind.ANCHOR
            ):
                raise EventValidationError("presence references an invalid scene anchor")
            if entity_id in characters:
                location_id = str(presence.get("location_id", ""))
                if not location_id:
                    raise EventValidationError(
                        "character presence requires a location id"
                    )
                characters[entity_id] = replace(
                    characters[entity_id], location_id=location_id
                )
        if delta.advance_time < 0:
            raise EventValidationError("world time cannot move backwards")
        if delta.advance_tick < 0:
            raise EventValidationError("tick cannot move backwards")
        return replace(
            self,
            characters=characters,
            resources=resources,
            inventories=inventories,
            relationships=relationships,
            schemes=schemes,
            knowledge={
                key: tuple(items) for key, items in knowledge.items()
            },
            disclosures={
                speaker: {
                    listener: tuple(facts)
                    for listener, facts in listeners.items()
                }
                for speaker, listeners in disclosures.items()
            },
            entities=entities,
            world_time=self.world_time + delta.advance_time,
            tick=self.tick + delta.advance_tick,
        )
