"""Implementation-independent contracts for entity-oriented world scenes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


JsonValue = (
    None
    | bool
    | int
    | float
    | str
    | tuple["JsonValue", ...]
    | Mapping[str, "JsonValue"]
)


class EntityKind(str, Enum):
    WORLD = "world"
    LOCATION = "location"
    SCENE = "scene"
    CHARACTER = "character"
    NPC = "npc"
    ITEM = "item"
    ANCHOR = "anchor"


class BuiltinComponent(str, Enum):
    IDENTITY = "identity"
    PRESENCE = "presence"
    LAYOUT = "layout"
    INTERACTABLE = "interactable"
    AGENT = "agent"
    ATTRIBUTES = "attributes"
    INVENTORY = "inventory"
    KNOWLEDGE = "knowledge"
    RELATIONSHIP = "relationship"
    AMBIENT_BEHAVIOR = "ambient_behavior"
    DRAMATIC = "dramatic"


class PatchOperation(str, Enum):
    CREATE_ENTITY = "create_entity"
    UPSERT_COMPONENT = "upsert_component"
    REMOVE_COMPONENT = "remove_component"


def scene_entity_id(location_id: str, scene_key: str = "default") -> str:
    """Return a stable scene identity within one map location."""

    if not location_id.strip() or not scene_key.strip():
        raise ValueError("scene identity requires location and key")
    base = f"scene:{location_id}"
    return base if scene_key == "default" else f"{base}:{scene_key}"


def _freeze(value: Any) -> JsonValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    raise ValueError(f"component values must be JSON-like, got {type(value).__name__}")


@dataclass(frozen=True)
class ComponentValue:
    component_type: str
    data: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.component_type.strip():
            raise ValueError("component type is required")
        object.__setattr__(self, "data", _freeze(dict(self.data)))


@dataclass(frozen=True)
class EntitySpec:
    entity_id: str
    kind: EntityKind
    components: tuple[ComponentValue, ...]
    version: int = 0

    def __post_init__(self) -> None:
        if not self.entity_id.strip():
            raise ValueError("entity id is required")
        if self.version < 0:
            raise ValueError("entity version must be non-negative")
        names = tuple(item.component_type for item in self.components)
        if len(names) != len(set(names)):
            raise ValueError("entity component types must be unique")

    def component(self, component_type: str) -> ComponentValue | None:
        return next(
            (
                item
                for item in self.components
                if item.component_type == component_type
            ),
            None,
        )


@dataclass(frozen=True)
class SceneBlueprint:
    scene_id: str
    location_id: str
    entry_anchor_id: str
    entities: tuple[EntitySpec, ...]
    local_rules: tuple[str, ...] = ()
    generation_basis: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.scene_id.strip() or not self.location_id.strip():
            raise ValueError("scene and location ids are required")
        ids = tuple(item.entity_id for item in self.entities)
        if len(ids) != len(set(ids)):
            raise ValueError("scene entity ids must be unique")
        if self.scene_id not in ids:
            raise ValueError("scene blueprint must contain its scene entity")
        if self.entry_anchor_id not in ids:
            raise ValueError("scene entry anchor must reference an entity")
        scene = next(item for item in self.entities if item.entity_id == self.scene_id)
        if scene.kind is not EntityKind.SCENE:
            raise ValueError("scene id must reference a scene entity")
        anchor = next(
            item for item in self.entities if item.entity_id == self.entry_anchor_id
        )
        if anchor.kind is not EntityKind.ANCHOR:
            raise ValueError("entry anchor must reference an anchor entity")


@dataclass(frozen=True)
class SceneGenerationContext:
    world_id: str
    world_title: str
    premise: str
    seed: int
    location_id: str
    location_name: str
    location_seed: str
    scene_key: str = "default"
    scene_seed: str = ""
    dramatic_question: str = ""
    failure_pressure: str = ""
    closure_signals: tuple[str, ...] = ()
    world_time: float = 0.0
    prior_scene_ids: tuple[str, ...] = ()
    world_rules: tuple[Mapping[str, JsonValue], ...] = ()
    authored_items: tuple[Mapping[str, JsonValue], ...] = ()
    max_anchors: int = 6
    max_entities: int = 16
    max_ambient_npcs: int = 3
    pressure_escalation_turns: int = 3
    max_pressure_level: int = 3
    decision_pressure_level: int = 2
    resolution_modes: tuple[str, ...] = (
        "closure_signals",
        "participant_decisions",
    )

    def __post_init__(self) -> None:
        if any(
            not item.strip()
            for item in (
                self.world_id,
                self.location_id,
                self.location_name,
                self.location_seed,
                self.scene_key,
            )
        ):
            raise ValueError("scene generation context is incomplete")
        if min(self.max_anchors, self.max_entities) < 1:
            raise ValueError("scene generation budgets must be positive")
        if (
            self.pressure_escalation_turns < 1
            or self.max_pressure_level < 1
            or not 0 <= self.decision_pressure_level <= self.max_pressure_level
        ):
            raise ValueError("scene pressure policy is invalid")
        object.__setattr__(
            self,
            "world_rules",
            tuple(_freeze(dict(item)) for item in self.world_rules),
        )
        object.__setattr__(
            self,
            "authored_items",
            tuple(_freeze(dict(item)) for item in self.authored_items),
        )


@dataclass(frozen=True)
class PerceptionView:
    actor_id: str
    scene_id: str
    scene_version: int
    first_person_context: str
    visible_entity_ids: tuple[str, ...]
    known_fact_ids: tuple[str, ...] = ()
    pending_interaction_ids: tuple[str, ...] = ()
    pressure_level: int = 0
    decision_required: bool = False
    closure_signals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.scene_version < 0:
            raise ValueError("scene version must be non-negative")
        if not self.actor_id.strip() or not self.scene_id.strip():
            raise ValueError("perception requires actor and scene")
        if not self.first_person_context.strip():
            raise ValueError("perception requires first-person context")
        if self.pressure_level < 0:
            raise ValueError("perception pressure must be non-negative")


@dataclass(frozen=True)
class CharacterIntent:
    intent_id: str
    actor_id: str
    scene_id: str
    expected_scene_version: int
    goal: str
    description: str
    referenced_entity_ids: tuple[str, ...]
    speech: str | None = None
    private_reasoning: str | None = None
    reply_to_interaction_id: str | None = None
    decision: str | None = None
    dispatch: str = "act"

    def __post_init__(self) -> None:
        if self.dispatch not in {"think", "address", "act"}:
            raise ValueError("intent dispatch is invalid")
        if self.expected_scene_version < 0:
            raise ValueError("intent scene version must be non-negative")
        required = (
            self.intent_id,
            self.actor_id,
            self.scene_id,
            self.goal,
            self.description,
        )
        if any(not item.strip() for item in required):
            raise ValueError("intent requires ids, goal, and description")
        if len(self.referenced_entity_ids) != len(
            set(self.referenced_entity_ids)
        ):
            raise ValueError("intent references must be unique")


@dataclass(frozen=True)
class ComponentPatch:
    operation: PatchOperation
    entity_id: str
    expected_entity_version: int | None = None
    entity: EntitySpec | None = None
    component: ComponentValue | None = None
    component_type: str | None = None

    def __post_init__(self) -> None:
        if not self.entity_id.strip():
            raise ValueError("patch entity id is required")
        if (
            self.expected_entity_version is not None
            and self.expected_entity_version < 0
        ):
            raise ValueError("expected entity version must be non-negative")
        if self.operation is PatchOperation.CREATE_ENTITY:
            if self.entity is None or self.entity.entity_id != self.entity_id:
                raise ValueError("create patch requires the matching entity")
        elif self.operation is PatchOperation.UPSERT_COMPONENT:
            if self.component is None:
                raise ValueError("upsert patch requires a component")
        elif not self.component_type:
            raise ValueError("remove patch requires a component type")


@dataclass(frozen=True)
class InteractionRequest:
    interaction_id: str
    initiator_id: str
    recipient_id: str
    scene_id: str
    public_prompt: str
    private_context: str = ""

    def __post_init__(self) -> None:
        required = (
            self.interaction_id,
            self.initiator_id,
            self.recipient_id,
            self.scene_id,
            self.public_prompt,
        )
        if any(not item.strip() for item in required):
            raise ValueError("interaction request is incomplete")


@dataclass(frozen=True)
class SceneTransition:
    location_id: str
    scene_key: str

    def __post_init__(self) -> None:
        if not self.location_id.strip() or not self.scene_key.strip():
            raise ValueError("scene transition requires location and key")


@dataclass(frozen=True)
class AdjudicatedTurn:
    intent_id: str
    actor_id: str
    scene_id: str
    expected_scene_version: int
    status: str
    public_action: str
    actor_feedback: str
    patches: tuple[ComponentPatch, ...] = ()
    spoken_text: str | None = None
    observer_feedback: Mapping[str, str] = field(default_factory=dict)
    interaction_requests: tuple[InteractionRequest, ...] = ()
    rule_basis: tuple[str, ...] = ()
    scene_transition: SceneTransition | None = None
    dramatic_progress: str = "none"
    scene_outcome: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"accepted", "partial", "rejected"}:
            raise ValueError("turn status is invalid")
        if self.dramatic_progress not in {
            "none",
            "advance",
            "decision",
            "resolved",
        }:
            raise ValueError("turn dramatic progress is invalid")
        if (self.dramatic_progress == "resolved") != (
            self.scene_outcome is not None
        ):
            raise ValueError(
                "resolved dramatic progress requires exactly one outcome"
            )
        if (
            self.scene_outcome is not None
            and not self.scene_outcome.strip()
        ):
            raise ValueError("scene outcome must be non-empty text")
        if self.expected_scene_version < 0:
            raise ValueError("turn scene version must be non-negative")
        if not self.public_action.strip() or not self.actor_feedback.strip():
            raise ValueError("turn requires public action and actor feedback")
        object.__setattr__(
            self,
            "observer_feedback",
            _freeze(dict(self.observer_feedback)),
        )
