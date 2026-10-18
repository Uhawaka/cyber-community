"""Deterministic, source-grounded dialogue decisions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping, Protocol

from engine.runtime.space import DialogueAct


class SoulLike(Protocol):
    voice: Mapping[str, Any] | str
    protective_style: str


class KnowledgeLike(Protocol):
    fact_id: str
    summary: str


@dataclass(frozen=True)
class DialogueDecision:
    act: DialogueAct
    topic: str
    utterance: str
    information_ids: tuple[str, ...] = ()


def deterministic_dialogue(
    soul: SoulLike,
    actor_id: str,
    target_id: str,
    knowledge: tuple[KnowledgeLike, ...],
    *,
    prior_talk_count: int = 0,
) -> DialogueDecision:
    """Choose a sourced communicative move rather than a stock greeting."""

    voice = soul.voice
    if isinstance(voice, Mapping):
        prefix = str(
            voice.get("prefix") or voice.get("style") or ""
        ).strip()
    else:
        prefix = str(voice).strip()
    tone = f"{prefix} {soul.protective_style}".strip()
    if not knowledge:
        return DialogueDecision(
            DialogueAct.INQUIRE,
            "眼前的危险",
            "先说你亲眼见到的，猜测暂且放下。",
        )
    incident = next(
        (
            item
            for item in knowledge
            if item.fact_id.startswith("incident:")
        ),
        None,
    )
    if incident is not None:
        fact = incident
    else:
        index = int.from_bytes(
            hashlib.sha256(
                f"{actor_id}:{target_id}:{prior_talk_count}".encode()
            ).digest()[:2],
            "big",
        ) % len(knowledge)
        fact = knowledge[index]
    topic = _dialogue_topic(fact.summary)
    if fact.fact_id.startswith("incident:"):
        return DialogueDecision(
            DialogueAct.PROPOSE,
            topic,
            f"{_incident_spoken(fact.summary)}。先查清声源，再谈别的。",
            (fact.fact_id,),
        )
    spoken = _first_person(fact.summary)
    if prior_talk_count % 2 == 0:
        if "礼貌" in tone or "克制" in tone:
            utterance = (
                f"我只说亲眼所见：{spoken}。"
                "这条线索先摆在这里。"
            )
        elif "直接" in tone or "警觉" in tone:
            utterance = f"{spoken}。若有反证，现在拿出来。"
        else:
            utterance = f"{spoken}。先别急着替它下结论。"
        return DialogueDecision(
            DialogueAct.DISCLOSE,
            topic,
            utterance,
            (fact.fact_id,),
        )
    return DialogueDecision(
        DialogueAct.CHALLENGE,
        topic,
        f"先把这处说清：{spoken}。这条若对不上，别的都作不得准。",
        (fact.fact_id,),
    )


def deterministic_utterance(
    soul: SoulLike, actor_id: str, target_id: str
) -> str:
    return deterministic_dialogue(
        soul, actor_id, target_id, ()
    ).utterance


def _dialogue_topic(summary: str) -> str:
    for topic in (
        "铜铃",
        "白色粉末",
        "浅白粉末",
        "苦叶草",
        "铃声",
        "脚印",
        "细线",
        "雨中痕迹",
    ):
        if topic in summary:
            return topic
    return "眼前的痕迹"


def _without_period(value: str) -> str:
    return value.rstrip("。！？!? ")


def _first_person(value: str) -> str:
    text = _without_period(value)
    for pronoun in ("她", "他"):
        if text.startswith(pronoun):
            return f"我{text[1:]}"
    return text


def _incident_spoken(value: str) -> str:
    clauses = [
        clause.strip()
        for clause in _without_period(value).replace("；", "，").split("，")
        if clause.strip()
    ]
    return (clauses[-1] if clauses else _without_period(value)).replace(
        "反而", ""
    )
