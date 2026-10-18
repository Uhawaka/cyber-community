"""Commit adjudicated free-form intentions as replayable scene turns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from engine.contracts import (
    AdjudicatedTurn,
    BuiltinComponent,
    CharacterIntent,
    ComponentPatch,
    ComponentValue,
    EntityKind,
    PatchOperation,
)
from engine.runtime.kernel.events import Delta, EventType, WorldEvent
from engine.runtime.scene.validation import (
    validate_adjudicated_turn,
    validate_intent,
)
from engine.runtime.simulation.run import AutonomousRun


def commit_turn(
    run: AutonomousRun,
    intent: CharacterIntent,
    turn: AdjudicatedTurn,
    *,
    chain_id: str | None = None,
) -> WorldEvent:
    validate_intent(intent, run.state)
    validate_adjudicated_turn(turn, intent, run.state)
    patches = list(turn.patches)
    _apply_interaction_queue(run, intent, turn, patches)
    scene = run.state.entities[intent.scene_id]
    attributes = dict(
        scene.components.get(BuiltinComponent.ATTRIBUTES.value, {})
    )
    attributes["turn_count"] = int(attributes.get("turn_count", 0)) + 1
    recent_turns = [
        dict(item)
        for item in attributes.get("recent_turns", ())
        if isinstance(item, Mapping)
    ]
    recent_turns.append(
        {
            "actor_id": intent.actor_id,
            "goal": intent.goal,
            "public_action": turn.public_action,
            "spoken_text": turn.spoken_text,
            "status": turn.status,
            "decision": intent.decision,
        }
    )
    attributes["recent_turns"] = tuple(recent_turns[-8:])
    patches.append(
        ComponentPatch(
            PatchOperation.UPSERT_COMPONENT,
            intent.scene_id,
            component=ComponentValue(
                BuiltinComponent.ATTRIBUTES.value, attributes
            ),
        )
    )
    dramatic = dict(
        scene.components.get(BuiltinComponent.DRAMATIC.value, {})
    )
    effective_progress = turn.dramatic_progress
    effective_outcome = turn.scene_outcome
    restated = False
    if dramatic and dramatic.get("status") == "open":
        decisions = {
            str(key): str(value)
            for key, value in dict(
                dramatic.get("decisions", {})
            ).items()
        }
        committed_decision = (
            intent.decision
            if turn.status in {"accepted", "partial"}
            and intent.decision
            else None
        )
        awaiting = str(dramatic.get("awaiting_actor_id") or "")
        addressee = _addressed_actor(run, intent)
        repeats = _restates_recent(
            turn.spoken_text or turn.public_action or committed_decision or "",
            [
                item
                for item in recent_turns[:-1]
                if item.get("actor_id") == intent.actor_id
            ],
        )
        restated = bool(committed_decision) and repeats
        if repeats:
            effective_progress = "none"
            if restated:
                committed_decision = None
        elif (
            effective_progress == "advance"
            and intent.speech
            and not committed_decision
            and awaiting
            and intent.actor_id != awaiting
        ):
            effective_progress = "none"
        if awaiting and intent.actor_id == awaiting:
            dramatic["awaiting_actor_id"] = addressee or ""
        elif addressee and intent.speech and not committed_decision:
            dramatic["awaiting_actor_id"] = addressee
        if not restated and (
            turn.dramatic_progress == "decision" or committed_decision
        ):
            decisions[intent.actor_id] = (
                intent.decision or turn.public_action
            )
            dramatic["decisions"] = decisions
            if effective_progress not in {"decision", "resolved"}:
                effective_progress = "decision"
            participants = {
                entity_id
                for entity_id, entity in run.state.entities.items()
                if entity.kind is EntityKind.CHARACTER
                and entity.components.get(
                    BuiltinComponent.PRESENCE.value, {}
                ).get("scene_id")
                == intent.scene_id
            }
            resolution_modes = set(
                str(item)
                for item in dramatic.get(
                    "resolution_modes",
                    ("closure_signals", "participant_decisions"),
                )
            )
            if (
                "participant_decisions" in resolution_modes
                and participants
                and participants.issubset(decisions)
            ):
                effective_progress = "resolved"
                effective_outcome = (
                    "在场完整角色均已提交可约束后续行为的决定。"
                )
        stagnant = int(dramatic.get("stagnant_turns", 0))
        if effective_progress == "none":
            stagnant += 1
        else:
            stagnant = 0
        dramatic["stagnant_turns"] = stagnant
        escalation_turns = int(
            dramatic.get("pressure_escalation_turns", 3)
        )
        max_pressure = int(dramatic.get("max_pressure_level", 3))
        dramatic["pressure_level"] = min(
            max_pressure,
            int(dramatic.get("pressure_level", 0))
            + (
                1
                if stagnant
                and stagnant % max(1, escalation_turns) == 0
                else 0
            ),
        )
        dramatic["last_progress"] = effective_progress
        if effective_progress == "resolved":
            dramatic["status"] = "resolved"
            dramatic["outcome"] = effective_outcome or ""
            dramatic["resolved_by"] = intent.actor_id
            dramatic["resolved_at"] = run.state.world_time
            dramatic["awaiting_actor_id"] = ""
        if committed_decision:
            dramatic["awaiting_actor_id"] = ""
        patches.append(
            ComponentPatch(
                PatchOperation.UPSERT_COMPONENT,
                intent.scene_id,
                component=ComponentValue(
                    BuiltinComponent.DRAMATIC.value, dramatic
                ),
            )
        )
    patches = _bind_versions(run, patches)
    observers = tuple(
        sorted(
            entity_id
            for entity_id, entity in run.state.entities.items()
            if entity_id in run.state.characters
            and entity.components.get(
                BuiltinComponent.PRESENCE.value, {}
            ).get("scene_id")
            == intent.scene_id
        )
    )
    pre_hash = run.state.state_hash()
    return run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=run.state.tick,
            event_type=EventType.TURN_RESOLVED,
            actor_id=intent.actor_id,
            observers=observers,
            delta=Delta(entity_patches=tuple(patches)),
            data={
                "intent_id": intent.intent_id,
                "scene_id": intent.scene_id,
                "goal": intent.goal,
                "intended_action": intent.description,
                "referenced_entity_ids": intent.referenced_entity_ids,
                "status": turn.status,
                "public_action": turn.public_action,
                "actor_feedback": turn.actor_feedback,
                "spoken_text": turn.spoken_text,
                "observer_feedback": dict(turn.observer_feedback),
                "interaction_requests": tuple(
                    {
                        "interaction_id": item.interaction_id,
                        "initiator_id": item.initiator_id,
                        "recipient_id": item.recipient_id,
                        "scene_id": item.scene_id,
                        "public_prompt": item.public_prompt,
                    }
                    for item in turn.interaction_requests
                ),
                "reply_to_interaction_id": intent.reply_to_interaction_id,
                "decision": intent.decision,
                "scene_transition": (
                    None
                    if turn.scene_transition is None
                    else {
                        "location_id": (
                            turn.scene_transition.location_id
                        ),
                        "scene_key": turn.scene_transition.scene_key,
                    }
                ),
                "dispatch": intent.dispatch,
                "chain_id": chain_id or intent.intent_id,
                "restated": restated if dramatic else False,
                "dramatic_progress": effective_progress,
                "scene_outcome": effective_outcome,
            },
            pre_state_hash=pre_hash,
            world_hash=run.state.world_hash,
            deterministic_cursor=len(run.events),
            target_entity_id=intent.scene_id,
            rule_basis=turn.rule_basis,
        )
    )


def _addressed_actor(
    run: AutonomousRun, intent: CharacterIntent
) -> str:
    """The character or NPC this speech is waiting on, if any."""

    if not intent.speech:
        return ""
    for entity_id in intent.referenced_entity_ids:
        if entity_id in {intent.actor_id, intent.scene_id}:
            continue
        entity = run.state.entities.get(entity_id)
        if entity is not None and entity.kind in {
            EntityKind.CHARACTER,
            EntityKind.NPC,
        }:
            return entity_id
    return ""


def _restates_recent(text: str, prior: list[Mapping[str, object]]) -> bool:
    """True when this public claim adds almost nothing to the scene record."""

    current = _bigrams(text)
    if len(current) < 6:
        return False
    seen: set[str] = set()
    for item in prior[-6:]:
        seen.update(_bigrams(str(item.get("spoken_text") or "")))
        seen.update(_bigrams(str(item.get("public_action") or "")))
    if not seen:
        return False
    novel = current - seen
    return len(novel) / len(current) < 0.35


def _bigrams(value: str) -> set[str]:
    compact = "".join(
        character
        for character in value.lower()
        if character.isalnum() or "\u4e00" <= character <= "\u9fff"
    )
    return {
        compact[index : index + 2]
        for index in range(max(0, len(compact) - 1))
    }


def _apply_interaction_queue(
    run: AutonomousRun,
    intent: CharacterIntent,
    turn: AdjudicatedTurn,
    patches: list[ComponentPatch],
) -> None:
    affected = {
        intent.actor_id,
        *(item.recipient_id for item in turn.interaction_requests),
    }
    for entity_id in affected:
        entity = run.state.entities[entity_id]
        component_type = (
            BuiltinComponent.AMBIENT_BEHAVIOR.value
            if entity.kind is EntityKind.NPC
            else BuiltinComponent.AGENT.value
        )
        agent = dict(entity.components.get(component_type, {}))
        pending = [
            dict(item)
            for item in agent.get("pending_interactions", ())
            if isinstance(item, Mapping)
            and item.get("interaction_id") != intent.reply_to_interaction_id
        ]
        incoming_initiators = {
            item.initiator_id
            for item in turn.interaction_requests
            if item.recipient_id == entity_id
        }
        pending = [
            item
            for item in pending
            if item.get("initiator_id") not in incoming_initiators
        ]
        pending.extend(
            {
                "interaction_id": item.interaction_id,
                "initiator_id": item.initiator_id,
                "recipient_id": item.recipient_id,
                "public_prompt": item.public_prompt,
                "private_context": item.private_context,
            }
            for item in turn.interaction_requests
            if item.recipient_id == entity_id
        )
        agent["pending_interactions"] = tuple(pending)
        if entity_id == intent.actor_id:
            agent["last_turn"] = {
                "intent_id": intent.intent_id,
                "goal": intent.goal,
                "public_action": turn.public_action,
                "status": turn.status,
            }
        patches.append(
            ComponentPatch(
                PatchOperation.UPSERT_COMPONENT,
                entity_id,
                component=ComponentValue(
                    component_type, agent
                ),
            )
        )


def _bind_versions(
    run: AutonomousRun, patches: list[ComponentPatch]
) -> list[ComponentPatch]:
    versions = {
        entity_id: entity.version
        for entity_id, entity in run.state.entities.items()
    }
    bound: list[ComponentPatch] = []
    for patch in patches:
        if patch.operation is PatchOperation.CREATE_ENTITY:
            bound.append(patch)
            versions[patch.entity_id] = patch.entity.version if patch.entity else 0
            continue
        expected = versions.get(patch.entity_id)
        if expected is None:
            bound.append(patch)
            continue
        bound.append(replace(patch, expected_entity_version=expected))
        versions[patch.entity_id] = expected + 1
    return bound
