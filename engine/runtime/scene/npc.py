"""Low-cost ambient NPC reactions without full agent memory or planning."""

from __future__ import annotations

from collections.abc import Mapping
import re

from engine.contracts import (
    AdjudicatedTurn,
    BuiltinComponent,
    CharacterIntent,
    EntityKind,
)
from engine.runtime.scene.turns import commit_turn
from engine.runtime.simulation.run import AutonomousRun


def resolve_ambient_npc_requests(
    run: AutonomousRun, *, limit: int = 4
) -> tuple[object, ...]:
    events: list[object] = []
    for npc_id, entity in sorted(run.state.entities.items()):
        if len(events) >= limit or entity.kind is not EntityKind.NPC:
            continue
        behavior = entity.components.get(
            BuiltinComponent.AMBIENT_BEHAVIOR.value, {}
        )
        pending = tuple(
            item
            for item in behavior.get("pending_interactions", ())
            if isinstance(item, Mapping)
        )
        for request in pending:
            if len(events) >= limit:
                break
            scene_id = str(
                entity.components.get(
                    BuiltinComponent.PRESENCE.value, {}
                ).get("scene_id", "")
            )
            scene = run.state.entities.get(scene_id)
            if scene is None:
                continue
            initiator_id = str(request.get("initiator_id", ""))
            interaction_id = str(request.get("interaction_id", ""))
            prompt = str(request.get("public_prompt", ""))
            response, disclosed_fact = _fresh_response(
                run,
                npc_id,
                *_response(behavior, prompt, _character_names(run)),
            )
            intent = CharacterIntent(
                f"{interaction_id}:npc-response",
                npc_id,
                scene_id,
                scene.version,
                "履行场景职责并回应来客",
                f"我按自己的职责回应{initiator_id}。",
                (initiator_id,),
                response,
                reply_to_interaction_id=interaction_id,
                dispatch="address",
            )
            turn = AdjudicatedTurn(
                intent.intent_id,
                npc_id,
                scene_id,
                scene.version,
                "accepted",
                f"{_name(entity)}说：“{response}”",
                "我已经作出简短回应。",
                spoken_text=response,
                observer_feedback={
                    initiator_id: f"{_name(entity)}回答：“{response}”"
                },
                dramatic_progress=(
                    "advance" if disclosed_fact else "none"
                ),
                rule_basis=("ambient NPC follows its generated local duty",),
            )
            events.append(commit_turn(run, intent, turn))
    return tuple(events)


def reply_to_speech(
    run: AutonomousRun,
    npc_id: str,
    speaker_id: str,
    speech: str,
    *,
    chain_id: str | None = None,
) -> object | None:
    """Load one ambient NPC because a character addressed them."""

    entity = run.state.entities.get(npc_id)
    if entity is None or entity.kind is not EntityKind.NPC:
        return None
    behavior = entity.components.get(
        BuiltinComponent.AMBIENT_BEHAVIOR.value, {}
    )
    scene_id = str(
        entity.components.get(BuiltinComponent.PRESENCE.value, {}).get(
            "scene_id", ""
        )
    )
    scene = run.state.entities.get(scene_id)
    if scene is None or not scene_id:
        return None
    response, disclosed_fact = _fresh_response(
        run, npc_id, *_response(behavior, speech, _character_names(run))
    )
    intent = CharacterIntent(
        f"{speaker_id}:{npc_id}:{run.state.tick}:reply",
        npc_id,
        scene_id,
        scene.version,
        "履行场景职责并回应来客",
        f"我按自己的职责回应{speaker_id}。",
        (speaker_id,),
        response,
        dispatch="address",
    )
    turn = AdjudicatedTurn(
        intent.intent_id,
        npc_id,
        scene_id,
        scene.version,
        "accepted",
        f"{_name(entity)}说：“{response}”",
        "我已经作出简短回应。",
        spoken_text=response,
        observer_feedback={speaker_id: f"{_name(entity)}回答：“{response}”"},
        dramatic_progress="advance" if disclosed_fact else "none",
        rule_basis=("addressed NPC replies from its local duty",),
    )
    return commit_turn(run, intent, turn, chain_id=chain_id)


def _fresh_response(
    run: AutonomousRun, npc_id: str, response: str, disclosed_fact: bool
) -> tuple[str, bool]:
    """A fact this NPC has already said is not new progress."""

    if any(
        event.actor_id == npc_id and event.data.get("spoken_text") == response
        for event in run.events
    ):
        return ("我刚才说的就是亲眼见到的全部，没有新的可补充。", False)
    return response, disclosed_fact


def _character_names(run: AutonomousRun) -> tuple[str, ...]:
    return tuple(
        str(character.display_name).strip()
        for character in run.state.characters.values()
        if str(character.display_name).strip()
    )


def _about_someone_else(fact: str, names: tuple[str, ...]) -> bool:
    """A local witness may not assign another person's history."""

    if any(len(name) >= 2 and name in fact for name in names):
        return True
    return re.search(r"(?<!其)[她他]", fact) is not None


def _response(
    behavior: Mapping[str, object],
    prompt: str,
    names: tuple[str, ...] = (),
) -> tuple[str, bool]:
    facts = tuple(
        str(item).strip()
        for item in behavior.get("known_facts", ())
        if isinstance(item, str)
        and item.strip()
        and not _about_someone_else(item, names)
    )
    if facts:
        prompt_pairs = _content_pairs(prompt)
        ranked = sorted(
            facts,
            key=lambda fact: len(prompt_pairs.intersection(_content_pairs(fact))),
            reverse=True,
        )
        if prompt_pairs.intersection(_content_pairs(ranked[0])):
            return (
                f"我只说亲眼见到的：{ranked[0].rstrip('。')}。",
                True,
            )
    return (
        "我只说亲眼见到的；没有把握的事，不能替你们下结论。",
        False,
    )


def _content_pairs(value: str) -> set[str]:
    """Overlap on a grammatical pair such as 的人 is not an answer."""

    particles = set("的了是在把被从和与或而也就都还又这那我你您吗呢吧啊")
    return {
        pair
        for pair in _pairs(value)
        if not any(character in particles for character in pair)
    }


def _pairs(value: str) -> set[str]:
    text = "".join(
        re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", value.lower())
    )
    return {
        text[index : index + 2]
        for index in range(max(0, len(text) - 1))
    }


def _name(entity: object) -> str:
    components = getattr(entity, "components", {})
    identity = components.get(BuiltinComponent.IDENTITY.value, {})
    return str(identity.get("name", "场景中的人"))
