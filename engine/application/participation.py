"""Avatar and observer application services for autonomous runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from engine.participation import AvatarPackage, AvatarProfile, InterventionAttempt
from engine.runtime.autonomous_director import (
    PendingUserGate,
    apply_fate_intervention as _apply_fate_intervention,
    apply_gate_intervention,
    get_pending_user_gate as _get_pending_user_gate,
)
from engine.runtime.kernel.events import (
    AvatarPresenceDelta,
    CharacterDelta,
    Delta,
    EventType,
    WorldEvent,
)
from engine.runtime.kernel.state import WorldState
from engine.runtime.simulation.planner import opportunities_for
from engine.runtime.simulation.resolver import Resolver
from engine.runtime.kernel.lifecycle import fork_run
from engine.runtime.simulation.run import AutonomousRun
from engine.runtime.space import ActionAttempt, ActionKind, Opportunity


DEFAULT_AVATAR_NEEDS = {
    "fatigue": 8,
    "social": 16,
    "resources": 28,
    "knowledge": 18,
    "exploration": 12,
}


@dataclass(frozen=True)
class ObserverView:
    """A read-only point-in-time projection; constructing it has no side effects."""

    state: WorldState
    events: tuple[WorldEvent, ...]


def observe_run(run: AutonomousRun) -> ObserverView:
    return ObserverView(run.state, run.events)


def get_pending_user_gate(run: AutonomousRun) -> PendingUserGate | None:
    return _get_pending_user_gate(run)


def run_until_user_gate(
    run: AutonomousRun, budget: int
) -> PendingUserGate | None:
    """Advance at most ``budget`` ticks, stopping before any gated actor action."""

    if budget < 0:
        raise ValueError("budget must be non-negative")
    from engine.runtime.simulation.executor import run_ticks

    pending = _get_pending_user_gate(run)
    for _ in range(budget):
        if pending is not None:
            break
        run_ticks(run, 1)
        pending = _get_pending_user_gate(run)
    return pending


def apply_intervention(
    run: AutonomousRun, gate_id: str, choice_id: str | None = None
) -> WorldEvent:
    """Apply an authored gate choice; omitted choice defaults to abstain."""

    return apply_gate_intervention(run, gate_id, choice_id)


def apply_fate_intervention(run: AutonomousRun, intervention_id: str) -> WorldEvent:
    """Invoke a Fate rule independently of the blocking UserGate mechanism."""

    return _apply_fate_intervention(run, intervention_id)


def join_avatar(
    run: AutonomousRun,
    package: AvatarPackage | AvatarProfile,
    entry_location: str,
    goals: tuple[str, ...] | list[str] = (),
    needs: Mapping[str, int] | None = None,
) -> WorldEvent:
    """Join through the same typed event/delta gateway used by simulation."""

    offline_policy = dict(run.compiled.workflow.intervention.policy)[
        "avatar_offline_policy"
    ]
    if isinstance(package, AvatarProfile):
        package = AvatarPackage(
            package.avatar_id,
            package.display_name,
            profile={
                "goals": tuple(str(goal) for goal in goals),
                "needs": dict(needs or {}),
                "preferences": tuple(value for _, value in package.preferences),
            },
        )
    location = next(
        (item for item in run.compiled.world.locations if item.id == entry_location),
        None,
    )
    if location is None:
        raise ValueError("unknown avatar entry location")
    if not {"entry", "avatar-entry"}.intersection(location.tags) and not location.allow_avatar_entry:
        raise ValueError("location is not authorized for avatar entry")
    existing = run.state.characters.get(package.avatar_id)
    if existing is not None:
        if existing.participant_kind != "avatar":
            raise ValueError("avatar id conflicts with an existing character")
        if existing.active:
            raise ValueError("avatar is already joined")
        if existing.display_name != package.display_name:
            raise ValueError("rejoining avatar package identity does not match")
        if existing.location_id != entry_location:
            raise ValueError("rejoining avatar must preserve its location")
        pre_state_hash = run.state.state_hash()
        cursor = len(run.events)
        return run.log.append(
            WorldEvent(
                sequence=cursor,
                tick=run.state.tick,
                event_type=EventType.AVATAR_REJOINED,
                actor_id=package.avatar_id,
                observers=(package.avatar_id,),
                delta=Delta(
                    avatar_presence=(AvatarPresenceDelta(package.avatar_id, True),)
                ),
                data={
                    "avatar_id": package.avatar_id,
                    "session_policy": package.session_policy.value,
                    "pre_state_hash": pre_state_hash,
                    "world_hash": run.state.world_hash,
                    "deterministic_cursor": cursor,
                    "target_entity_id": package.avatar_id,
                    "rule_basis": ("existing avatar projection is preserved",),
                },
                pre_state_hash=pre_state_hash,
                world_hash=run.state.world_hash,
                deterministic_cursor=cursor,
                target_entity_id=package.avatar_id,
                rule_basis=("existing avatar projection is preserved",),
            )
        )
    normalized_needs = dict(DEFAULT_AVATAR_NEEDS)
    normalized_needs.update(package.needs)
    normalized_goals = package.goals
    pre_state_hash = run.state.state_hash()
    cursor = len(run.events)
    delta = Delta(
        characters=(
            CharacterDelta(
                character_id=package.avatar_id,
                display_name=package.display_name,
                location_id=entry_location,
                needs=normalized_needs,
                goals=normalized_goals,
            ),
        )
    )
    rule_basis = (
        "entry location is world-authorized",
        "avatar package passed the typed trust boundary",
    )
    event = run.log.append(
        WorldEvent(
            sequence=cursor,
            tick=run.state.tick,
            event_type=EventType.AVATAR_JOINED,
            actor_id=package.avatar_id,
            observers=(package.avatar_id,),
            delta=delta,
            data={
                "avatar_id": package.avatar_id,
                "display_name": package.display_name,
                "entry_location": entry_location,
                "goals": normalized_goals,
                "skills": package.skills,
                "offline_policy": offline_policy,
                "session_policy": package.session_policy.value,
                "memory_seed": tuple(dict(item) for item in package.memory_seed),
                "pre_state_hash": pre_state_hash,
                "world_hash": run.state.world_hash,
                "deterministic_cursor": cursor,
                "target_entity_id": package.avatar_id,
                "rule_basis": rule_basis,
            },
            pre_state_hash=pre_state_hash,
            world_hash=run.state.world_hash,
            deterministic_cursor=cursor,
            target_entity_id=package.avatar_id,
            rule_basis=rule_basis,
        )
    )
    run.memory.register_avatar(package.avatar_id, package.memory_seed)
    return event


def leave_avatar(run: AutonomousRun, avatar_id: str) -> WorldEvent:
    character = run.state.characters.get(avatar_id)
    if (
        character is None
        or character.participant_kind != "avatar"
        or not character.active
    ):
        raise ValueError("avatar is not currently joined")
    pre_state_hash = run.state.state_hash()
    cursor = len(run.events)
    return run.log.append(
        WorldEvent(
            sequence=cursor,
            tick=run.state.tick,
            event_type=EventType.AVATAR_LEFT,
            actor_id=avatar_id,
            observers=(avatar_id,),
            delta=Delta(
                avatar_presence=(AvatarPresenceDelta(avatar_id, False),)
            ),
            data={
                "avatar_id": avatar_id,
                "offline_policy": dict(run.compiled.workflow.intervention.policy)[
                    "avatar_offline_policy"
                ],
                "pre_state_hash": pre_state_hash,
                "world_hash": run.state.world_hash,
                "deterministic_cursor": cursor,
                "target_entity_id": avatar_id,
                "rule_basis": ("avatar explicitly left; no proxy action is allowed",),
            },
            pre_state_hash=pre_state_hash,
            world_hash=run.state.world_hash,
            deterministic_cursor=cursor,
            target_entity_id=avatar_id,
            rule_basis=("avatar explicitly left; no proxy action is allowed",),
        )
    )


def avatar_perception(
    run: AutonomousRun, avatar_id: str
) -> tuple[WorldEvent, ...]:
    character = run.state.characters.get(avatar_id)
    if character is None or character.participant_kind != "avatar":
        raise ValueError("unknown avatar")
    return tuple(event for event in run.events if avatar_id in event.observers)


def avatar_memory(run: AutonomousRun, avatar_id: str):
    """Return observed-event memory plus only this Avatar's private seed."""

    return run.memory.for_character(avatar_id, avatar_perception(run, avatar_id))


def avatar_opportunities(
    run: AutonomousRun, avatar_id: str
) -> tuple[Opportunity, ...]:
    character = run.state.characters.get(avatar_id)
    if character is None or character.participant_kind != "avatar":
        raise ValueError("unknown avatar")
    if not character.active:
        raise ValueError("avatar is offline")
    return opportunities_for(run.compiled.world, run.state, avatar_id)


def submit_avatar_attempt(
    run: AutonomousRun, attempt: InterventionAttempt
) -> WorldEvent:
    """Validate a current opportunity, then use the simulation Resolver."""

    character = run.state.characters.get(attempt.participant_id)
    if character is None or character.participant_kind != "avatar":
        raise ValueError("attempt participant is not a joined avatar")
    if not character.active:
        raise ValueError("attempt participant is offline")
    current = {
        opportunity.opportunity_id: opportunity
        for opportunity in avatar_opportunities(run, attempt.participant_id)
    }
    opportunity = current.get(attempt.opportunity_id)
    if opportunity is None:
        raise ValueError("attempt must reference a current legal opportunity")
    aliases = {
        "speak": ActionKind.TALK,
        "travel": ActionKind.MOVE,
        "look": ActionKind.OBSERVE,
    }
    try:
        requested_kind = aliases.get(attempt.action)
        if requested_kind is None:
            requested_kind = ActionKind(attempt.action)
    except ValueError as exc:
        raise ValueError("unknown avatar action") from exc
    if requested_kind is not opportunity.affordance.kind:
        raise ValueError("attempt action does not match opportunity")
    affordance = opportunity.affordance
    return Resolver(run.compiled.world, run.log).resolve(
        ActionAttempt(
            actor_id=attempt.participant_id,
            kind=affordance.kind,
            target_id=affordance.target_id,
            expected_location_id=affordance.location_id,
            cost=affordance.cost,
            reason=opportunity.reason,
            opportunity_id=opportunity.opportunity_id,
        )
    )


