"""Demand-driven loading of the object a character actually addresses."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from engine.contracts import (
    AdjudicatedTurn,
    BuiltinComponent,
    CharacterIntent,
    EntityKind,
)
from engine.runtime.kernel.events import EventType
from engine.runtime.scene.egress import (
    deterministic_egress,
    egress_candidates,
)
from engine.runtime.scene.labels import entity_label
from engine.runtime.scene.lifecycle import enter_scene, travel_to_scene
from engine.runtime.scene.npc import reply_to_speech
from engine.runtime.scene.perception import project_perception
from engine.runtime.scene.turns import commit_turn
from engine.runtime.simulation.run import AutonomousRun

_CHAIN_LIMIT = 6


def resolve_dispatched_intent(
    run: AutonomousRun,
    intent: CharacterIntent,
    *,
    intent_policy: object,
    adjudicator: object,
    generator: object,
    depth: int,
    spoken: set[str],
    chain_id: str | None = None,
) -> None:
    """Commit thought or dialogue locally; load the environment only for acts."""

    active_chain = chain_id or intent.intent_id
    spoken.add(intent.actor_id)
    kind = dispatch_kind(run, intent)
    if kind == "think":
        commit_turn(
            run, intent, local_turn(run, intent), chain_id=active_chain
        )
        return
    if kind == "address":
        commit_turn(
            run, intent, local_turn(run, intent), chain_id=active_chain
        )
        _load_addressee(
            run,
            intent,
            intent_policy=intent_policy,
            adjudicator=adjudicator,
            generator=generator,
            depth=depth,
            spoken=spoken,
            chain_id=active_chain,
        )
        return
    turn = adjudicator.adjudicate(  # type: ignore[attr-defined]
        run.compiled.world, run.state, intent
    )
    if (
        turn.scene_transition is None
        and turn.status != "rejected"
        and _layer_is_spent(run, intent)
        and not _exchange_is_open(run, intent)
    ):
        transition = _next_unvisited_place(run, intent.actor_id)
        if transition is not None:
            turn = replace(
                turn,
                scene_transition=transition,
                rule_basis=tuple(turn.rule_basis)
                + (
                    "this place already answered its layer; leaving opens the next place",
                ),
            )
    if turn.scene_transition is not None and _exchange_is_open(run, intent):
        turn = replace(turn, scene_transition=None)
    commit_turn(run, intent, turn, chain_id=active_chain)
    if turn.scene_transition is not None and turn.status != "rejected":
        destination = turn.scene_transition.location_id
        current = run.state.characters[intent.actor_id].location_id
        if destination != current:
            travel_to_scene(
                run,
                intent.actor_id,
                destination,
                generator,
                scene_key=turn.scene_transition.scene_key,
            )
        else:
            enter_scene(
                run,
                intent.actor_id,
                destination,
                generator,
                scene_key=turn.scene_transition.scene_key,
            )


def dispatch_kind(run: AutonomousRun, intent: CharacterIntent) -> str:
    """Honor the requested dispatch. Mentioning an object is not an act."""

    target = address_target(run, intent)
    if intent.dispatch == "think":
        return "think"
    if intent.dispatch == "act":
        return "act"
    if intent.speech and target is not None:
        return "address"
    if intent.dispatch == "address" and intent.speech:
        return "address"
    return "think"


def address_target(run: AutonomousRun, intent: CharacterIntent) -> str | None:
    candidates = [
        entity_id
        for entity_id in intent.referenced_entity_ids
        if entity_id not in {intent.actor_id, intent.scene_id}
        and _kind(run, entity_id) in {EntityKind.CHARACTER, EntityKind.NPC}
    ]
    return candidates[0] if candidates else None


def local_turn(run: AutonomousRun, intent: CharacterIntent) -> AdjudicatedTurn:
    display = entity_label(run, intent.actor_id)
    if intent.speech:
        public_action = f"{display}说：“{intent.speech}”"
        progress = "decision" if intent.decision else "advance"
    elif intent.decision:
        public_action = f"{display}决定：{intent.decision}"
        progress = "decision"
    else:
        public_action = intent.description
        progress = "none"
    return AdjudicatedTurn(
        intent.intent_id,
        intent.actor_id,
        intent.scene_id,
        intent.expected_scene_version,
        "accepted",
        public_action,
        intent.private_reasoning or "我已经完成这一步。",
        spoken_text=intent.speech,
        dramatic_progress=progress,
        rule_basis=(
            "character dispatch committed without environment adjudication",
        ),
    )


def _load_addressee(
    run: AutonomousRun,
    intent: CharacterIntent,
    *,
    intent_policy: object,
    adjudicator: object,
    generator: object,
    depth: int,
    spoken: set[str],
    chain_id: str,
) -> None:
    target = address_target(run, intent)
    if target is None or depth + 1 >= _CHAIN_LIMIT:
        return
    if _kind(run, target) is EntityKind.NPC:
        reply_to_speech(
            run,
            target,
            intent.actor_id,
            intent.speech or "",
            chain_id=chain_id,
        )
        spoken.add(target)
        return
    if target not in run.state.characters:
        return
    perception = project_perception(run.state, target)
    reply = intent_policy.decide(  # type: ignore[attr-defined]
        run.compiled.world, run.state, perception
    )
    resolve_dispatched_intent(
        run,
        reply,
        intent_policy=intent_policy,
        adjudicator=adjudicator,
        generator=generator,
        depth=depth + 1,
        spoken=spoken,
        chain_id=chain_id,
    )


def _layer_is_spent(run: AutonomousRun, intent: CharacterIntent) -> bool:
    """A place is spent once someone else has answered and this actor chooses to leave."""

    decision = str(intent.decision or "").strip()
    if decision in {"", "None", "null"} or "离开" not in (
        f"{decision} {intent.goal}"
    ):
        return False
    scene = run.state.entities.get(intent.scene_id)
    if scene is None:
        return False
    recent = scene.components.get(BuiltinComponent.ATTRIBUTES.value, {}).get(
        "recent_turns", ()
    )
    return any(
        str(item.get("spoken_text") or "").strip()
        and item.get("actor_id") != intent.actor_id
        for item in recent
        if isinstance(item, Mapping)
    )


def _next_unvisited_place(run: AutonomousRun, actor_id: str):
    visited = {run.state.characters[actor_id].location_id}
    for event in run.events:
        if event.event_type is not EventType.MOVED or event.actor_id != actor_id:
            continue
        visited.add(str(event.data.get("origin_id") or ""))
        visited.add(str(event.data.get("destination_id") or ""))
    visited.discard("")
    fresh = tuple(
        candidate
        for candidate in egress_candidates(run, actor_id)
        if candidate.kind == "travel"
        and candidate.transition.location_id not in visited
    )
    if not fresh:
        return None
    return deterministic_egress(run, actor_id, fresh)


def _exchange_is_open(run: AutonomousRun, intent: CharacterIntent) -> bool:
    """A place cannot be left while someone is still waiting to be answered."""

    if intent.decision:
        return False
    scene = run.state.entities.get(intent.scene_id)
    if scene is None:
        return False
    return bool(
        scene.components.get(BuiltinComponent.DRAMATIC.value, {}).get(
            "awaiting_actor_id"
        )
    )


def _kind(run: AutonomousRun, entity_id: str) -> EntityKind | None:
    entity = run.state.entities.get(entity_id)
    return None if entity is None else entity.kind

