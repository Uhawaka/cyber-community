"""Deterministic Affordance -> Opportunity -> ActionAttempt selection."""

from __future__ import annotations

import hashlib
from collections import deque
from typing import Any

from engine.runtime.kernel.state import WorldState
from engine.runtime.space import (
    ActionAttempt,
    ActionKind,
    Affordance,
    Opportunity,
    enumerate_affordances,
)
from engine.world.package_spec import AutonomousWorldSpec, PackageCharacter


def _stable_noise(seed: int, tick: int, actor: str, value: str) -> int:
    digest = hashlib.sha256(f"{seed}:{tick}:{actor}:{value}".encode()).digest()
    return int.from_bytes(digest[:2], "big") % 7


def _profile(character: PackageCharacter) -> dict[str, Any]:
    return dict(character.profile)


def opportunities_for(
    world: AutonomousWorldSpec,
    state: WorldState,
    actor_id: str,
    *,
    limit: int | None = None,
    character_scope: frozenset[str] | None = None,
) -> tuple[Opportunity, ...]:
    character = next((item for item in world.characters if item.id == actor_id), None)
    profile = _profile(character) if character is not None else {}
    soul = dict(character.soul) if character is not None else {}
    actor = state.characters[actor_id]
    authored_goals = profile.get("goals", ())
    goals = tuple(str(item) for item in (authored_goals or actor.goals))
    plan, _ = _current_plan(world, state, actor_id, goals)
    needs = actor.needs
    values: list[Opportunity] = []
    for affordance in enumerate_affordances(
        world,
        state,
        actor_id,
        limit=limit,
        character_scope=character_scope,
    ):
        base, reason = _utility(affordance, needs)
        target_text = affordance.target_id
        base, reason = _score_plan_step(
            world, state, actor_id, affordance, plan, base, reason
        )
        base += _soul_adjustment(soul, affordance)
        base += _recent_action_adjustment(actor.recent_actions, affordance, state.tick)
        if affordance.kind is ActionKind.TALK:
            base += _conversation_progress_adjustment(
                state, actor_id, affordance.target_id
            )
        utility = base + _stable_noise(
            state.seed, state.tick, actor_id, f"{affordance.kind.value}:{target_text}"
        )
        pre_state_hash = state.state_hash()
        identity = (
            f"{pre_state_hash}:{actor_id}:{affordance.kind.value}:"
            f"{affordance.target_id}:{affordance.location_id}"
        )
        opportunity_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        values.append(
            Opportunity(
                actor_id,
                affordance,
                utility,
                reason,
                opportunity_id,
                pre_state_hash,
            )
        )
    return tuple(values)


def choose_attempt(
    world: AutonomousWorldSpec, state: WorldState, actor_id: str
) -> ActionAttempt:
    options = opportunities_for(world, state, actor_id)
    selected = max(
        options,
        key=lambda item: (
            item.utility,
            -item.affordance.cost,
            item.affordance.kind.value,
            item.affordance.target_id,
        ),
    )
    return attempt_from_opportunity(world, state, actor_id, selected)


def attempt_from_opportunity(
    world: AutonomousWorldSpec,
    state: WorldState,
    actor_id: str,
    selected: Opportunity,
) -> ActionAttempt:
    if (
        selected.actor_id != actor_id
        or selected.pre_state_hash != state.state_hash()
        or not _is_legal_affordance(world, state, actor_id, selected.affordance)
    ):
        raise ValueError("opportunity is not legal in current state")
    character = next((item for item in world.characters if item.id == actor_id), None)
    profile = _profile(character) if character is not None else {}
    authored_goals = profile.get("goals", ())
    goals = tuple(
        str(item) for item in (authored_goals or state.characters[actor_id].goals)
    )
    plan, replacement = _current_plan(world, state, actor_id, goals)
    affordance = selected.affordance
    return ActionAttempt(
        actor_id=actor_id,
        kind=affordance.kind,
        target_id=affordance.target_id,
        expected_location_id=affordance.location_id,
        cost=affordance.cost,
        reason=selected.reason,
        opportunity_id=selected.opportunity_id,
        replacement_plan=plan if replacement else None,
        pre_state_hash=selected.pre_state_hash,
    )


def _is_legal_affordance(
    world: AutonomousWorldSpec,
    state: WorldState,
    actor_id: str,
    affordance: Affordance,
) -> bool:
    return any(
        candidate.kind is affordance.kind
        and candidate.target_id == affordance.target_id
        and candidate.location_id == affordance.location_id
        for candidate in enumerate_affordances(world, state, actor_id)
    )


def _soul_adjustment(soul: dict[str, Any], affordance: Affordance) -> int:
    """Small identity bias over legal choices; it can never create an outcome."""

    text = " ".join(
        [
            *(str(item) for item in soul.get("values", ())),
            *(str(item) for item in soul.get("preferences", ())),
            str(soul.get("temperament", "")),
        ]
    ).lower()
    tokens = {
        ActionKind.TALK: ("social", "people", "倾听", "关系", "交流", "同伴"),
        ActionKind.GATHER: ("resource", "craft", "资源", "手艺", "收集", "实用"),
        ActionKind.INSPECT: ("knowledge", "verify", "查验", "证据", "谨慎"),
        ActionKind.MOVE: ("explore", "curious", "探索", "好奇", "远行"),
        ActionKind.OBSERVE: ("knowledge", "verify", "观察", "验证", "谨慎", "信号"),
        ActionKind.REST: ("rest", "patient", "休息", "耐心", "稳妥"),
        ActionKind.WAIT: ("wait", "patient", "等待", "耐心"),
    }[affordance.kind]
    return min(12, 3 * sum(token in text for token in tokens))


def _current_plan(
    world: AutonomousWorldSpec,
    state: WorldState,
    actor_id: str,
    goals: tuple[str, ...],
) -> tuple[tuple[str, ...], bool]:
    actor = state.characters[actor_id]
    current = actor.short_plan
    if (
        len(current) == 3
        and not _plan_complete(state, actor_id, current)
        and _plan_valid(world, state, actor_id, current)
    ):
        return current, False
    return _make_plan(world, state, actor_id, goals), True


def _plan_complete(
    state: WorldState, actor_id: str, plan: tuple[str, ...]
) -> bool:
    kind, target_id, destination_id = plan
    actor = state.characters[actor_id]
    if kind == "reach":
        return actor.location_id == destination_id
    return bool(
        actor.recent_actions
        and actor.recent_actions[-1].kind == kind
        and actor.recent_actions[-1].target_id == target_id
    )


def _plan_valid(
    world: AutonomousWorldSpec,
    state: WorldState,
    actor_id: str,
    plan: tuple[str, ...],
) -> bool:
    kind, target_id, destination_id = plan
    if destination_id not in state.location_ids:
        return False
    if _distance(world, state.characters[actor_id].location_id, destination_id) is None:
        return False
    if kind == ActionKind.GATHER.value:
        return state.resources.get(target_id, 0) > 0 and any(
            item.id == target_id and item.location_id == destination_id
            for item in world.resources
        )
    if kind == ActionKind.INSPECT.value:
        fact_id = f"resource:{target_id}:inspection"
        return (
            state.inventories.get(actor_id, {}).get(target_id, 0) > 0
            and fact_id in state.facts
            and fact_id not in state.knowledge.get(actor_id, ())
        )
    if kind == ActionKind.TALK.value:
        target = state.characters.get(target_id)
        return target is not None and target.location_id == destination_id
    return kind in {
        "reach",
        ActionKind.OBSERVE.value,
        ActionKind.REST.value,
    }


def _make_plan(
    world: AutonomousWorldSpec,
    state: WorldState,
    actor_id: str,
    goals: tuple[str, ...],
) -> tuple[str, ...]:
    actor = state.characters[actor_id]
    goal_text = " ".join(goals)

    for resource in world.resources:
        if (
            resource.id in goal_text
            and state.resources.get(resource.id, 0) > 0
            and state.inventories.get(actor_id, {}).get(resource.id, 0) == 0
            and _distance(world, actor.location_id, resource.location_id) is not None
        ):
            return (ActionKind.GATHER.value, resource.id, resource.location_id)
        fact_id = f"resource:{resource.id}:inspection"
        if (
            resource.id in goal_text
            and state.inventories.get(actor_id, {}).get(resource.id, 0) > 0
            and fact_id in state.facts
            and fact_id not in state.knowledge.get(actor_id, ())
        ):
            return (
                ActionKind.INSPECT.value,
                resource.id,
                actor.location_id,
            )
    for other_id, other in state.characters.items():
        if (
            other_id != actor_id
            and other_id in goal_text
            and _distance(world, actor.location_id, other.location_id) is not None
        ):
            return (ActionKind.TALK.value, other_id, other.location_id)
    for location_id in state.location_ids:
        if (
            location_id in goal_text
            and location_id != actor.location_id
            and _distance(world, actor.location_id, location_id) is not None
        ):
            return ("reach", location_id, location_id)

    candidates: list[tuple[int, int, str, str, str]] = []
    for resource in world.resources:
        if state.resources.get(resource.id, 0) <= 0:
            continue
        distance = _distance(world, actor.location_id, resource.location_id)
        if distance is not None:
            candidates.append(
                (
                    int(actor.needs.get("resources", 0)),
                    -distance,
                    ActionKind.GATHER.value,
                    resource.id,
                    resource.location_id,
                )
            )
    for resource in world.resources:
        fact_id = f"resource:{resource.id}:inspection"
        if (
            state.inventories.get(actor_id, {}).get(resource.id, 0) > 0
            and fact_id in state.facts
            and fact_id not in state.knowledge.get(actor_id, ())
        ):
            candidates.append(
                (
                    int(actor.needs.get("knowledge", 0)) + 40,
                    0,
                    ActionKind.INSPECT.value,
                    resource.id,
                    actor.location_id,
                )
            )
    for other_id, other in state.characters.items():
        if other_id == actor_id:
            continue
        distance = _distance(world, actor.location_id, other.location_id)
        if distance is not None:
            candidates.append(
                (
                    int(actor.needs.get("social", 0)),
                    -distance,
                    ActionKind.TALK.value,
                    other_id,
                    other.location_id,
                )
            )
    candidates.append(
        (
            int(actor.needs.get("knowledge", 0)),
            0,
            ActionKind.OBSERVE.value,
            actor.location_id,
            actor.location_id,
        )
    )
    candidates.append(
        (
            int(actor.needs.get("fatigue", 0)),
            0,
            ActionKind.REST.value,
            actor_id,
            actor.location_id,
        )
    )
    if not candidates:
        return (ActionKind.REST.value, actor_id, actor.location_id)
    _, _, kind, target_id, destination_id = max(candidates)
    return (kind, target_id, destination_id)


def _score_plan_step(
    world: AutonomousWorldSpec,
    state: WorldState,
    actor_id: str,
    affordance: Affordance,
    plan: tuple[str, ...],
    base: int,
    reason: str,
) -> tuple[int, str]:
    kind, target_id, destination_id = plan
    location_id = state.characters[actor_id].location_id
    if location_id != destination_id and affordance.kind is ActionKind.MOVE:
        if affordance.target_id in _shortest_first_passages(
            world, location_id, destination_id
        ):
            return base + 70, "shortest path toward active plan"
    if location_id == destination_id:
        expected_kind = ActionKind(kind) if kind != "reach" else None
        if expected_kind is affordance.kind and target_id == affordance.target_id:
            repeated = sum(
                action.kind == affordance.kind.value
                and action.target_id == affordance.target_id
                for action in state.characters[actor_id].recent_actions
            )
            return (
                base + max(0, 120 - repeated * 100),
                "active plan objective",
            )
    return base, reason


def _recent_action_adjustment(
    recent_actions: tuple[Any, ...],
    affordance: Affordance,
    tick: int,
) -> int:
    adjustment = 0
    for index, action in enumerate(reversed(recent_actions)):
        age = max(0, tick - action.tick)
        if action.kind == affordance.kind.value:
            adjustment -= max(0, 18 - age * 4)
        if (
            action.kind == affordance.kind.value
            and action.target_id == affordance.target_id
        ):
            adjustment -= max(0, 52 - age * 12)
        if index == 0 and action.kind == affordance.kind.value:
            adjustment -= 45
    return adjustment


def _conversation_progress_adjustment(
    state: WorldState, actor_id: str, target_id: str
) -> int:
    actor_knows = set(state.knowledge.get(actor_id, ()))
    target_knows = set(state.knowledge.get(target_id, ()))
    undisclosed = actor_knows - target_knows
    learnable = target_knows - actor_knows
    addressed = {
        fact_id
        for listeners in state.disclosures.values()
        for facts in listeners.values()
        for fact_id in facts
    }
    shared_incidents = {
        fact_id
        for fact_id in actor_knows.intersection(target_knows)
        if fact_id.startswith("incident:") and fact_id not in addressed
    }
    if undisclosed or learnable or shared_incidents:
        return 70
    return -160


def _distance(
    world: AutonomousWorldSpec, origin_id: str, destination_id: str
) -> int | None:
    if origin_id == destination_id:
        return 0
    queue = deque([(origin_id, 0)])
    visited = {origin_id}
    while queue:
        location_id, distance = queue.popleft()
        for passage in world.passages:
            if passage.origin_id != location_id:
                continue
            if passage.destination_id == destination_id:
                return distance + 1
            if passage.destination_id not in visited:
                visited.add(passage.destination_id)
                queue.append((passage.destination_id, distance + 1))
    return None


def _shortest_first_passages(
    world: AutonomousWorldSpec, origin_id: str, destination_id: str
) -> tuple[str, ...]:
    distance = _distance(world, origin_id, destination_id)
    if distance is None or distance == 0:
        return ()
    return tuple(
        passage.id
        for passage in world.passages
        if passage.origin_id == origin_id
        and _distance(world, passage.destination_id, destination_id) == distance - 1
    )


def _utility(affordance: Affordance, needs: dict[str, int] | Any) -> tuple[int, str]:
    if affordance.kind is ActionKind.TALK:
        return 95 + int(needs.get("social", 0)), "co-located social need"
    if affordance.kind is ActionKind.GATHER:
        return 80 + int(needs.get("resources", 0)), "available local resource"
    if affordance.kind is ActionKind.INSPECT:
        return 105 + int(needs.get("knowledge", 0)), "unexamined held evidence"
    if affordance.kind is ActionKind.MOVE:
        return 64 + int(needs.get("exploration", 0)), "reachable passage"
    if affordance.kind is ActionKind.REST:
        return 25 + int(needs.get("fatigue", 0)), "fatigue"
    if affordance.kind is ActionKind.OBSERVE:
        return 44 + int(needs.get("knowledge", 0)), "local knowledge"
    return 5, "no stronger opportunity"
