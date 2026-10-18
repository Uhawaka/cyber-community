"""Long-term schemes, memory consolidation, and Soul evolution."""

from __future__ import annotations

import hashlib
from typing import Any

from engine.runtime.character.contracts import SchemeStatus
from engine.runtime.kernel.events import (
    Delta,
    EventType,
    SchemeDelta,
    SoulDelta,
    WorldEvent,
)
from engine.runtime.simulation.run import AutonomousRun
from engine.runtime.space import ActionAttempt, ActionKind

def _active_scheme(run: AutonomousRun, actor_id: str):
    candidates = [
        item
        for item in run.state.schemes.values()
        if item.character_id == actor_id
        and item.status in {SchemeStatus.PLANNED, SchemeStatus.ACTIVE}
    ]
    return candidates[-1] if candidates else None


def sync_scheme(run: AutonomousRun, attempt: ActionAttempt) -> None:
    target = attempt.replacement_plan
    active = _active_scheme(run, attempt.actor_id)
    if target is None:
        return
    if active is not None and active.target_state == target:
        return
    if active is not None:
        _append_long_term_event(
            run,
            EventType.SCHEME_INVALIDATED,
            actor_id=attempt.actor_id,
            delta=Delta(
                schemes=(
                    SchemeDelta(
                        active.scheme_id,
                        active.character_id,
                        active.target_state,
                        active.progress,
                        SchemeStatus.INVALIDATED.value,
                    ),
                )
            ),
            data={"scheme_id": active.scheme_id, "reason": "plan no longer legal"},
        )
    identity = (
        f"{run.state.seed}:{run.state.tick}:{attempt.actor_id}:"
        + ":".join(target)
    )
    scheme_id = hashlib.sha256(identity.encode()).hexdigest()[:20]
    _append_long_term_event(
        run,
        EventType.SCHEME_CREATED,
        actor_id=attempt.actor_id,
        delta=Delta(
            schemes=(
                SchemeDelta(
                    scheme_id,
                    attempt.actor_id,
                    target,
                    0.0,
                    SchemeStatus.PLANNED.value,
                ),
            )
        ),
        data={"scheme_id": scheme_id, "target_state": target},
    )


def advance_scheme_after_action(
    run: AutonomousRun, attempt: ActionAttempt, event: WorldEvent
) -> None:
    scheme = _active_scheme(run, attempt.actor_id)
    if scheme is None:
        return
    kind, target_id, destination_id = scheme.target_state
    completed = (
        kind == "reach"
        and event.event_type is EventType.MOVED
        and event.data.get("destination_id") == destination_id
    ) or (
        kind != "reach"
        and attempt.kind.value == kind
        and attempt.target_id == target_id
    )
    progress = 1.0 if completed else max(scheme.progress, 0.5 if attempt.kind is ActionKind.MOVE else 0.25)
    if progress == scheme.progress:
        return
    status = SchemeStatus.COMPLETED if completed else SchemeStatus.ACTIVE
    event_type = (
        EventType.SCHEME_COMPLETED if completed else EventType.SCHEME_ADVANCED
    )
    _append_long_term_event(
        run,
        event_type,
        actor_id=attempt.actor_id,
        delta=Delta(
            schemes=(
                SchemeDelta(
                    scheme.scheme_id,
                    scheme.character_id,
                    scheme.target_state,
                    progress,
                    status.value,
                ),
            )
        ),
        data={
            "scheme_id": scheme.scheme_id,
            "progress": progress,
            "source_event_sequence": event.sequence,
        },
    )


def consolidate_memory(
    run: AutonomousRun,
    *,
    budget: int,
    observer_ids: tuple[str, ...],
    interval: int = 4,
) -> int:
    if run.state.tick == 0 or run.state.tick % interval:
        return 0
    if any(
        event.event_type is EventType.MEMORY_CONSOLIDATED
        and event.tick == run.state.tick
        for event in run.events
    ):
        return 0
    if budget <= 0:
        return 0
    used = 0
    excluded = {
        EventType.MEMORY_CONSOLIDATED,
        EventType.SOUL_EVOLUTION_PROPOSED,
        EventType.SOUL_EVOLUTION_APPROVED,
        EventType.SOUL_EVOLUTION_REJECTED,
    }
    for observer_id in sorted(set(observer_ids)):
        if used >= budget:
            break
        prior = next(
            (
                event.sequence
                for event in reversed(run.events)
                if event.event_type is EventType.MEMORY_CONSOLIDATED
                and observer_id in event.observers
            ),
            -1,
        )
        sources = tuple(
            event
            for event in run.events[prior + 1 :]
            if event.event_type not in excluded and observer_id in event.observers
        )
        if not sources:
            continue
        belief_types = {
            str(event.data.get("belief_type", "fact")) for event in sources
        }
        belief_type = (
            "misbelief"
            if "misbelief" in belief_types
            else "inference"
            if "inference" in belief_types
            else "fact"
        )
        confidence = min(
            float(event.data.get("confidence", 1.0)) for event in sources
        )
        target_tier = (
            "core"
            if any(
                event.event_type
                in {EventType.INCIDENT_OCCURRED, EventType.SCHEME_COMPLETED}
                for event in sources
            )
            else "semantic"
        )
        _append_long_term_event(
            run,
            EventType.MEMORY_CONSOLIDATED,
            actor_id=observer_id,
            delta=Delta(),
            data={
                "source_sequences": tuple(event.sequence for event in sources),
                "target_tier": target_tier,
                "belief_type": belief_type,
                "confidence": confidence,
                "summary": _deterministic_memory_summary(sources),
            },
            observer_ids=(observer_id,),
        )
        used += 1
    return used


def evolve_souls(
    run: AutonomousRun, *, actor_ids: tuple[str, ...], budget: int
) -> int:
    used = 0
    for actor_id in actor_ids:
        if used >= budget:
            break
        overlay = run.state.characters[actor_id].soul_overlay
        # Authored Soul is intentionally slow-moving. A fresh run must first
        # accumulate a meaningful span of lived history before proposing any
        # personality change, even if several routine actions happen early.
        if overlay.last_evolution_tick is None and run.state.tick < 12:
            continue
        if (
            overlay.last_evolution_tick is not None
            and run.state.tick - overlay.last_evolution_tick < 12
        ):
            continue
        last_proposal = next(
            (
                event
                for event in reversed(run.events)
                if event.event_type is EventType.SOUL_EVOLUTION_PROPOSED
                and event.actor_id == actor_id
            ),
            None,
        )
        since = last_proposal.sequence if last_proposal is not None else -1
        evidence = tuple(
            event
            for event in run.events[since + 1 :]
            if _soul_evidence_intensity(event) >= 0.7
            and (event.actor_id == actor_id or actor_id in event.observers)
        )
        if len(evidence) < 3:
            continue
        evidence_sequences = tuple(event.sequence for event in evidence)
        evidence_ids = tuple(f"event:{sequence}" for sequence in evidence_sequences)
        magnitude = min(0.2, 0.04 * len(evidence))
        proposal_id = hashlib.sha256(
            f"{run.state.seed}:{actor_id}:{evidence_ids}".encode()
        ).hexdigest()[:20]
        authored = next(
            character for character in run.compiled.world.characters
            if character.id == actor_id
        )
        current_drives = tuple(
            str(item)
            for item in overlay.traits.get(
                "drives", dict(authored.soul).get("drives", ())
            )
        )
        reinforced_drive = _drive_from_evidence(evidence)
        proposed_value = tuple(dict.fromkeys((*current_drives, reinforced_drive)))
        _append_long_term_event(
            run,
            EventType.SOUL_EVOLUTION_PROPOSED,
            actor_id=actor_id,
            delta=Delta(),
            data={
                "proposal_id": proposal_id,
                "trait": "drives",
                "proposed_value": proposed_value,
                "evidence_event_ids": evidence_ids,
                "evidence_sequences": evidence_sequences,
                "magnitude": magnitude,
                "expected_version": overlay.version,
            },
        )
        enough_evidence = len(evidence_ids) >= 3
        cooldown_ok = True
        magnitude_ok = magnitude <= 0.25
        approved = enough_evidence and cooldown_ok and magnitude_ok
        reason = (
            "evidence, cooldown and magnitude guard passed"
            if approved
            else "guard rejected: "
            + ", ".join(
                name
                for name, passed in (
                    ("evidence", enough_evidence),
                    ("cooldown", cooldown_ok),
                    ("magnitude", magnitude_ok),
                )
                if not passed
            )
        )
        _append_long_term_event(
            run,
            EventType.SOUL_EVOLUTION_APPROVED
            if approved
            else EventType.SOUL_EVOLUTION_REJECTED,
            actor_id=actor_id,
            delta=Delta(
                souls=(
                    SoulDelta(
                        character_id=actor_id,
                        trait="drives",
                        value=proposed_value,
                        expected_version=overlay.version,
                        evidence_sequences=evidence_sequences,
                    ),
                )
            )
            if approved
            else Delta(),
            data={
                "proposal_id": proposal_id,
                "trait": "drives",
                "proposed_value": proposed_value,
                "evidence_event_ids": evidence_ids,
                "evidence_sequences": evidence_sequences,
                "magnitude": magnitude,
                "reason": reason,
            },
        )
        used += 1
    return used


def memory_work_due(run: AutonomousRun, actor_ids: tuple[str, ...]) -> bool:
    if run.state.tick and run.state.tick % 4 == 0:
        if not any(
            event.event_type is EventType.MEMORY_CONSOLIDATED
            and event.tick == run.state.tick
            for event in run.events
        ):
            return True
    for actor_id in actor_ids:
        last = next(
            (
                event.sequence
                for event in reversed(run.events)
                if event.event_type is EventType.SOUL_EVOLUTION_PROPOSED
                and event.actor_id == actor_id
            ),
            -1,
        )
        if sum(
            _soul_evidence_intensity(event) >= 0.7
            and (event.actor_id == actor_id or actor_id in event.observers)
            for event in run.events[last + 1 :]
        ) >= 3:
            return True
    return False


def _source_summary(event: WorldEvent) -> str:
    return str(
        event.data.get("utterance")
        or event.data.get("summary")
        or event.data.get("description")
        or event.event_type.value
    ).strip()


def _deterministic_memory_summary(sources: tuple[WorldEvent, ...]) -> str:
    summaries = tuple(dict.fromkeys(_source_summary(event) for event in sources))
    return "；".join(summaries[-3:])


def _soul_evidence_intensity(event: WorldEvent) -> float:
    explicit = event.data.get("intensity")
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
        return min(1.0, max(0.0, float(explicit)))
    return {
        EventType.GATHERED: 0.7,
        EventType.INCIDENT_OCCURRED: 1.0,
        EventType.SCHEME_COMPLETED: 0.9,
    }.get(event.event_type, 0.0)


def _drive_from_evidence(events: tuple[WorldEvent, ...]) -> str:
    latest = events[-1].event_type
    return {
        EventType.GATHERED: "gather",
        EventType.INCIDENT_OCCURRED: "observe",
        EventType.SCHEME_COMPLETED: "move",
    }.get(latest, "observe")


def _append_long_term_event(
    run: AutonomousRun,
    event_type: EventType,
    *,
    actor_id: str | None,
    delta: Delta,
    data: dict[str, Any],
    observer_ids: tuple[str, ...] | None = None,
) -> WorldEvent:
    state = run.state
    pre_state_hash = state.state_hash()
    cursor = len(run.events)
    target = actor_id or state.world_id
    rule_basis = ("evolution tick long-term projection",)
    return run.log.append(
        WorldEvent(
            sequence=cursor,
            tick=state.tick,
            event_type=event_type,
            actor_id=actor_id,
            observers=(
                ((actor_id,) if actor_id is not None else ())
                if observer_ids is None
                else observer_ids
            ),
            delta=delta,
            data={
                **data,
                "pre_state_hash": pre_state_hash,
                "world_hash": state.world_hash,
                "deterministic_cursor": cursor,
                "target_entity_id": target,
                "rule_basis": rule_basis,
            },
            pre_state_hash=pre_state_hash,
            world_hash=state.world_hash,
            deterministic_cursor=cursor,
            target_entity_id=target,
            rule_basis=rule_basis,
        )
    )


