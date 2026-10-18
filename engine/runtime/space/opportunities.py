"""World-authored affordances and actor-specific opportunities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.runtime.kernel.state import WorldState
from engine.world.package_spec import AutonomousWorldSpec


class ActionKind(str, Enum):
    MOVE = "move"
    GATHER = "gather"
    INSPECT = "inspect"
    OBSERVE = "observe"
    TALK = "talk"
    REST = "rest"
    WAIT = "wait"


class DialogueAct(str, Enum):
    INQUIRE = "inquire"
    DISCLOSE = "disclose"
    PROPOSE = "propose"
    CHALLENGE = "challenge"
    REASSURE = "reassure"


@dataclass(frozen=True)
class Affordance:
    kind: ActionKind
    target_id: str
    location_id: str
    cost: int = 1


@dataclass(frozen=True)
class Opportunity:
    actor_id: str
    affordance: Affordance
    utility: int
    reason: str
    opportunity_id: str = ""
    pre_state_hash: str = ""


@dataclass(frozen=True)
class ActionAttempt:
    actor_id: str
    kind: ActionKind
    target_id: str
    expected_location_id: str
    cost: int
    reason: str
    opportunity_id: str = ""
    replacement_plan: tuple[str, ...] | None = None
    utterance: str | None = None
    dialogue_act: DialogueAct | None = None
    dialogue_topic: str | None = None
    information_ids: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    pre_state_hash: str = ""
    reservation_id: str = ""


def enumerate_affordances(
    world: AutonomousWorldSpec,
    state: WorldState,
    actor_id: str,
    *,
    limit: int | None = None,
    character_scope: frozenset[str] | None = None,
) -> tuple[Affordance, ...]:
    if actor_id not in state.characters:
        raise ValueError("unknown opportunity actor")
    if limit is not None and limit < 0:
        raise ValueError("opportunity limit must be non-negative")
    location_id = state.characters[actor_id].location_id
    location = next(item for item in world.locations if item.id == location_id)
    character = next(
        (item for item in world.characters if item.id == actor_id), None
    )
    profile = dict(character.profile) if character is not None else {}
    skills = {
        str(item) for item in profile.get("skills", ())
    } if isinstance(profile.get("skills", ()), list) else set()
    values: list[Affordance] = []

    def add(value: Affordance) -> bool:
        if limit is not None and len(values) >= limit:
            return False
        values.append(value)
        return True

    # Generate directly in the public stable sort order so a limit stops work,
    # rather than materialising an unbounded co-location list before slicing it.
    for resource in sorted(world.resources, key=lambda item: item.id):
        if (
            resource.location_id == location_id
            and state.resources.get(resource.id, 0) > 0
            and location.allows(ActionKind.GATHER.value)
            and set(resource.required_skills).issubset(skills)
            and not add(Affordance(ActionKind.GATHER, resource.id, location_id))
        ):
            return tuple(values)
    for resource in sorted(world.resources, key=lambda item: item.id):
        fact_id = f"resource:{resource.id}:inspection"
        if (
            state.inventories.get(actor_id, {}).get(resource.id, 0) > 0
            and fact_id in state.facts
            and fact_id not in state.knowledge.get(actor_id, ())
            and not add(
                Affordance(
                    ActionKind.INSPECT,
                    resource.id,
                    location_id,
                )
            )
        ):
            return tuple(values)
    for passage in sorted(world.passages, key=lambda item: item.id):
        destination = next(
            item for item in world.locations if item.id == passage.destination_id
        )
        if (
            passage.origin_id == location_id
            and _can_traverse(world, state, actor_id, passage.id)
            and _occupancy(state, passage.destination_id) < destination.capacity
            and not add(
            Affordance(
                ActionKind.MOVE,
                passage.id,
                location_id,
                max(1, passage.travel_time),
            )
            )
        ):
            return tuple(values)
    if location.allows(ActionKind.OBSERVE.value) and not add(
        Affordance(ActionKind.OBSERVE, location_id, location_id)
    ):
        return tuple(values)
    if location.allows(ActionKind.REST.value) and not add(
        Affordance(ActionKind.REST, actor_id, location_id)
    ):
        return tuple(values)
    for other_id in sorted(state.characters):
        character = state.characters[other_id]
        if (
            other_id != actor_id
            and character.location_id == location_id
            and location.allows("social")
            and (character_scope is None or other_id in character_scope)
            and not add(Affordance(ActionKind.TALK, other_id, location_id))
        ):
            return tuple(values)
    add(Affordance(ActionKind.WAIT, actor_id, location_id))
    return tuple(values)


def _occupancy(state: WorldState, location_id: str) -> int:
    return sum(
        character.location_id == location_id and character.active
        for character in state.characters.values()
    )


def _can_traverse(
    world: AutonomousWorldSpec,
    state: WorldState,
    actor_id: str,
    passage_id: str,
) -> bool:
    passage = next((item for item in world.passages if item.id == passage_id), None)
    character = next((item for item in world.characters if item.id == actor_id), None)
    if passage is None:
        return False
    profile = dict(character.profile) if character is not None else {}
    role = character.role if character is not None else ""
    actor_tags = set(str(item) for item in profile.get("access_tags", ()))
    skills = set(str(item) for item in profile.get("skills", ()))
    destination = next(
        item for item in world.locations if item.id == passage.destination_id
    )
    if destination.allowed_roles and role not in destination.allowed_roles:
        return False
    if not set(destination.access_tags).issubset(actor_tags):
        return False
    properties = dict(passage.properties)
    allowed_roles = set(properties.get("allowed_roles", ()))
    return (
        (not allowed_roles or role in allowed_roles)
        and set(properties.get("required_access_tags", ())).issubset(actor_tags)
        and set(properties.get("required_skills", ())).issubset(skills)
    )
