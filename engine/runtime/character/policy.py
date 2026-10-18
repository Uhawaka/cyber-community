"""Character decision port and deterministic/model-backed adapters."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from types import MappingProxyType
from typing import Any, Mapping

from engine.contracts import ActorPolicy, TextModel
from engine.runtime.character.dialogue import (
    DialogueDecision,
    deterministic_dialogue,
    deterministic_utterance,
)
from engine.runtime.kernel.state import WorldState
from engine.runtime.space import (
    ActionAttempt,
    ActionKind,
    DialogueAct,
    Opportunity,
)
from engine.world.package_spec import AutonomousWorldSpec, PackageCharacter


@dataclass(frozen=True)
class SoulDecisionContext:
    """Read-only authored identity supplied to decision code, never to the resolver."""

    identity: str = ""
    self_view: str = ""
    values: tuple[str, ...] = ()
    taboos: tuple[str, ...] = ()
    protective_style: str = ""
    drives: tuple[str, ...] = ()
    voice: Mapping[str, Any] | str = ""
    relationship_stance: Mapping[str, Any] | str = ""

    def __post_init__(self) -> None:
        if isinstance(self.voice, Mapping):
            object.__setattr__(self, "voice", MappingProxyType(dict(self.voice)))

    @classmethod
    def from_character(
        cls,
        character: PackageCharacter | None,
        state: WorldState | None = None,
    ) -> "SoulDecisionContext":
        soul = dict(character.soul) if character is not None else {}
        if character is not None and state is not None and character.id in state.characters:
            soul.update(state.characters[character.id].soul_overlay.traits)
        return cls(
            identity=str(soul.get("identity", "")),
            self_view=str(soul.get("self_view", "")),
            values=tuple(str(item) for item in soul.get("values", ())),
            taboos=tuple(str(item) for item in soul.get("taboos", ())),
            protective_style=str(soul.get("protective_style", "")),
            drives=tuple(str(item) for item in soul.get("drives", ())),
            voice=soul.get("voice", ""),
            relationship_stance=soul.get("relationship_stance", ""),
        )


@dataclass(frozen=True)
class ActorDecisionContext:
    actor_id: str
    tick: int
    location_id: str
    soul: SoulDecisionContext
    opportunities: tuple[Opportunity, ...]
    knowledge: tuple["KnowledgeFact", ...] = ()


@dataclass(frozen=True)
class KnowledgeFact:
    fact_id: str
    kind: str
    summary: str


class DeterministicActorPolicy:
    def choose(
        self,
        world: AutonomousWorldSpec,
        state: WorldState,
        actor_id: str,
        opportunities: tuple[Opportunity, ...],
    ) -> ActionAttempt:
        from engine.runtime.simulation.planner import attempt_from_opportunity

        character = next(
            (item for item in world.characters if item.id == actor_id), None
        )
        soul = SoulDecisionContext.from_character(character, state)
        knowledge = _known_knowledge(world, state, actor_id)
        selected = max(
            opportunities,
            key=lambda item: (
                item.utility + _soul_weight(soul, item),
                -item.affordance.cost,
                item.affordance.kind.value,
                item.affordance.target_id,
            ),
        )
        attempt = attempt_from_opportunity(world, state, actor_id, selected)
        if attempt.kind is ActionKind.TALK:
            knowledge = _undisclosed_knowledge(
                state, actor_id, attempt.target_id, knowledge
            )
            dialogue = deterministic_dialogue(
                soul,
                actor_id,
                attempt.target_id,
                knowledge,
                prior_talk_count=sum(
                    action.kind == ActionKind.TALK.value
                    for action in state.characters[actor_id].recent_actions
                ),
            )
            attempt = replace(
                attempt,
                utterance=dialogue.utterance,
                dialogue_act=dialogue.act,
                dialogue_topic=dialogue.topic,
                information_ids=dialogue.information_ids,
            )
        return attempt


class ModelDialogueActorPolicy:
    """Keep deterministic actions while using a model for grounded dialogue."""

    def __init__(
        self,
        model: TextModel,
        *,
        timeout_seconds: float = 20.0,
        fallback: ActorPolicy | None = None,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.fallback = fallback or DeterministicActorPolicy()
        self.diagnostics: list[str] = []

    def choose(
        self,
        world: AutonomousWorldSpec,
        state: WorldState,
        actor_id: str,
        opportunities: tuple[Opportunity, ...],
    ) -> ActionAttempt:
        attempt = self.fallback.choose(
            world, state, actor_id, opportunities
        )
        if attempt.kind is not ActionKind.TALK:
            return attempt
        character = next(
            item for item in world.characters if item.id == actor_id
        )
        known = {
            item.fact_id: item.summary
            for item in _known_knowledge(world, state, actor_id)
            if item.fact_id in attempt.information_ids
        }
        prompt = (
            "你只负责把已经决定的对话行动写成一句自然中文，不改变行动、"
            "言语行为、话题或事实。不得加入新的实体、线索、心理、承诺或结果。"
            "避免“线索、反证、下结论、先摆在这里”等报告腔；人物声音来自 soul。"
            "只返回 JSON：{\"utterance\":\"...\"}。输入："
            + json.dumps(
                {
                    "speaker_id": actor_id,
                    "listener_id": attempt.target_id,
                    "dialogue_act": (
                        attempt.dialogue_act.value
                        if attempt.dialogue_act is not None
                        else None
                    ),
                    "dialogue_topic": attempt.dialogue_topic,
                    "authorized_facts": known,
                    "fallback_utterance": attempt.utterance,
                    "soul": dict(character.soul),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        try:
            raw = self.model.complete(
                prompt, timeout_seconds=self.timeout_seconds
            )
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("invalid modeled dialogue")
            utterance = value.get("utterance")
            if (
                not isinstance(utterance, str)
                or not utterance.strip()
                or len(utterance) > 500
                or any(character in utterance for character in "\r\n\0")
            ):
                raise ValueError("invalid modeled dialogue")
            return replace(attempt, utterance=utterance.strip())
        except (ModelInvocationError, ValueError, json.JSONDecodeError) as exc:
            self.diagnostics.append(
                f"{actor_id}:dialogue:{type(exc).__name__}"
            )
            return attempt


class ModelActorPolicy:
    """Constrained model adapter: one repair, then deterministic fallback."""

    def __init__(
        self,
        model: TextModel,
        *,
        timeout_seconds: float = 5.0,
        fallback: ActorPolicy | None = None,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.fallback = fallback or DeterministicActorPolicy()
        self.diagnostics: list[str] = []

    def choose(
        self,
        world: AutonomousWorldSpec,
        state: WorldState,
        actor_id: str,
        opportunities: tuple[Opportunity, ...],
    ) -> ActionAttempt:
        character = next((item for item in world.characters if item.id == actor_id), None)
        soul = SoulDecisionContext.from_character(character, state)
        context = ActorDecisionContext(
            actor_id=actor_id,
            tick=state.tick,
            location_id=state.characters[actor_id].location_id,
            soul=soul,
            opportunities=opportunities,
            knowledge=_known_knowledge(world, state, actor_id),
        )
        prompt = self._prompt(context)
        failures: list[str] = []
        for attempt_number in range(2):
            try:
                raw = self._invoke(
                    prompt
                    if attempt_number == 0
                    else prompt
                    + "\n修复：只返回合法 JSON，并且 opportunity_id 必须来自清单。"
                )
                decision = json.loads(raw)
                if not isinstance(decision, dict):
                    raise ValueError("response is not an object")
                opportunity_id = decision.get("opportunity_id")
                selected = next(
                    (
                        item
                        for item in opportunities
                        if item.opportunity_id == opportunity_id
                    ),
                    None,
                )
                if selected is None:
                    raise ValueError("unknown opportunity id")
                from engine.runtime.simulation.planner import attempt_from_opportunity

                result = attempt_from_opportunity(world, state, actor_id, selected)
                utterance = decision.get("utterance")
                if utterance is not None and not isinstance(utterance, str):
                    raise ValueError("utterance must be a string")
                if result.kind is ActionKind.TALK:
                    available_knowledge = _undisclosed_knowledge(
                        state,
                        actor_id,
                        result.target_id,
                        context.knowledge,
                    )
                    fallback_dialogue = deterministic_dialogue(
                        soul,
                        actor_id,
                        result.target_id,
                        available_knowledge,
                        prior_talk_count=sum(
                            action.kind == ActionKind.TALK.value
                            for action in state.characters[
                                actor_id
                            ].recent_actions
                        ),
                    )
                    raw_act = decision.get("dialogue_act")
                    act = (
                        fallback_dialogue.act
                        if raw_act is None
                        else DialogueAct(str(raw_act))
                    )
                    topic = str(
                        decision.get("dialogue_topic")
                        or fallback_dialogue.topic
                    ).strip()
                    raw_information_ids = decision.get(
                        "information_ids", ()
                    )
                    if not isinstance(raw_information_ids, list) or any(
                        not isinstance(item, str)
                        for item in raw_information_ids
                    ):
                        raise ValueError(
                            "information_ids must be an array of strings"
                        )
                    allowed_ids = {
                        item.fact_id for item in available_knowledge
                    }
                    information_ids = tuple(raw_information_ids)
                    if not set(information_ids).issubset(allowed_ids):
                        raise ValueError("unknown information id")
                    supplied_utterance = (utterance or "").strip()
                    spoken = (
                        supplied_utterance
                        or fallback_dialogue.utterance
                    )
                    result = replace(
                        result,
                        utterance=spoken,
                        dialogue_act=act,
                        dialogue_topic=topic,
                        information_ids=(
                            information_ids
                            if supplied_utterance
                            else fallback_dialogue.information_ids
                        ),
                    )
                return result
            except (
                RuntimeError,
                TimeoutError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
        diagnostic = "actor_policy_fallback: " + " | ".join(failures)
        self.diagnostics.append(diagnostic)
        fallback = self.fallback.choose(world, state, actor_id, opportunities)
        return replace(fallback, diagnostics=fallback.diagnostics + (diagnostic,))

    def _invoke(self, prompt: str) -> str:
        return str(
            self.model.complete(prompt, timeout_seconds=self.timeout_seconds)
        )

    @staticmethod
    def _prompt(context: ActorDecisionContext) -> str:
        options = [
            {
                "opportunity_id": item.opportunity_id,
                "kind": item.affordance.kind.value,
                "target_id": item.affordance.target_id,
                "reason": item.reason,
                "utility": item.utility,
            }
            for item in context.opportunities
        ]
        soul = {
            "identity": context.soul.identity,
            "self_view": context.soul.self_view,
            "values": context.soul.values,
            "taboos": context.soul.taboos,
            "protective_style": context.soul.protective_style,
            "drives": context.soul.drives,
            "voice": dict(context.soul.voice)
            if isinstance(context.soul.voice, Mapping)
            else context.soul.voice,
            "relationship_stance": dict(context.soul.relationship_stance)
            if isinstance(context.soul.relationship_stance, Mapping)
            else context.soul.relationship_stance,
        }
        knowledge = [
            {
                "information_id": item.fact_id,
                "kind": item.kind,
                "summary": item.summary,
            }
            for item in context.knowledge
        ]
        return (
            "选择且只能选择一个给定 opportunity_id。若选择 talk，还要给出"
            " dialogue_act、dialogue_topic、information_ids 和 utterance。"
            "dialogue_act 只能是 inquire/disclose/propose/challenge/reassure；"
            "information_ids 只能来自 knowledge。台词只能表达意图、提问或转述"
            "所列知识，不得宣称世界结果或泄露未列出的秘密。只返回 JSON："
            + json.dumps(
                {
                    "soul": soul,
                    "knowledge": knowledge,
                    "opportunities": options,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


def _soul_weight(soul: SoulDecisionContext, opportunity: Opportunity) -> int:
    """Apply a small, replayable preference weight without bypassing legality."""

    kind = opportunity.affordance.kind.value.casefold()
    signals = (*soul.values, *soul.drives)
    return 25 if any(kind in signal.casefold() for signal in signals) else 0


def _known_knowledge(
    _world: AutonomousWorldSpec,
    state: WorldState,
    actor_id: str,
) -> tuple[KnowledgeFact, ...]:
    known_ids = set(state.knowledge.get(actor_id, ()))
    values = tuple(
        KnowledgeFact(fact_id, "fact", summary.strip())
        for fact_id, summary in state.facts.items()
        if fact_id in known_ids and summary.strip()
    )
    return tuple(
        sorted(
            values,
            key=lambda item: item.fact_id,
        )
    )


def _undisclosed_knowledge(
    state: WorldState,
    actor_id: str,
    target_id: str,
    knowledge: tuple[KnowledgeFact, ...],
) -> tuple[KnowledgeFact, ...]:
    disclosed = set(
        state.disclosures.get(actor_id, {}).get(target_id, ())
    )
    target_knows = set(state.knowledge.get(target_id, ()))
    addressed = {
        fact_id
        for listeners in state.disclosures.values()
        for facts in listeners.values()
        for fact_id in facts
    }
    return tuple(
        item
        for item in knowledge
        if item.fact_id not in disclosed
        and (
            item.fact_id not in target_knows
            or (
                item.fact_id.startswith("incident:")
                and item.fact_id not in addressed
            )
        )
    )
