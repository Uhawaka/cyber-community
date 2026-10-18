"""First-person free-intent policy for entity-oriented scene turns."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from engine.adapters.model_json import decode_json_object
from engine.contracts import (
    CharacterIntent,
    PerceptionView,
    SceneTransition,
    TextModel,
)
from engine.runtime.kernel.state import WorldState
from engine.runtime.scene.egress import EgressCandidate
from engine.world.package_spec import AutonomousWorldSpec, PackageCharacter


class ModelIntentPolicy:
    def __init__(
        self,
        model: TextModel,
        *,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.diagnostics: list[str] = []

    def decide(
        self,
        world: AutonomousWorldSpec,
        state: WorldState,
        perception: PerceptionView,
    ) -> CharacterIntent:
        authored = next(
            (
                item
                for item in world.characters
                if item.id == perception.actor_id
            ),
            None,
        )
        if authored is None:
            raise ValueError("intent actor is not world-authored")
        prompt = _character_turn_prompt(world, state, perception, authored)
        try:
            value = decode_json_object(
                self.model.complete(
                    prompt, timeout_seconds=self.timeout_seconds
                )
            )
            return _decode_intent(value, perception, state.tick)
        except Exception as exc:
            self.diagnostics.append(
                f"intent fallback for {perception.actor_id}: "
                f"{type(exc).__name__}: {exc}"
            )
            return _fallback_intent(perception, state.tick)

    def decide_egress(
        self,
        world: AutonomousWorldSpec,
        state: WorldState,
        perception: PerceptionView,
        candidates: tuple[EgressCandidate, ...],
    ) -> tuple[SceneTransition, str] | None:
        """Choose a legal next scene after closure, without plot routing."""

        if not candidates:
            return None
        actor = next(
            item
            for item in world.characters
            if item.id == perception.actor_id
        )
        prompt = (
            "这一处已经结束。按你的志向从给出的去向里选下一处。"
            "选还能往下走一层的地方，不要回到只为把同一件事再核对一遍的去向，"
            "也不要选择列表外的地点。只返回JSON对象："
            '{"location_id":"...","scene_key":"...","reason":"第一人称理由"}。输入：'
            + json.dumps(
                {
                    "name": actor.name,
                    "ambition": list(state.characters[actor.id].goals),
                    "conduct": _conduct(_as_dict(actor.soul)),
                    "perception": perception.first_person_context,
                    "candidates": [
                        {
                            "location_id": item.transition.location_id,
                            "scene_key": item.transition.scene_key,
                            "kind": item.kind,
                            "name": item.name,
                            "description": item.description,
                        }
                        for item in candidates
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        try:
            value = decode_json_object(
                self.model.complete(
                    prompt, timeout_seconds=self.timeout_seconds
                )
            )
            transition = SceneTransition(
                _text(value, "location_id"),
                _text(value, "scene_key"),
            )
            if transition not in {
                item.transition for item in candidates
            }:
                raise ValueError("egress selected an unavailable transition")
            return transition, _text(value, "reason")[:160]
        except Exception as exc:
            self.diagnostics.append(
                f"egress fallback for {perception.actor_id}: "
                f"{type(exc).__name__}: {exc}"
            )
            return None


def _character_turn_prompt(
    world: AutonomousWorldSpec,
    state: WorldState,
    perception: PerceptionView,
    authored: PackageCharacter,
) -> str:
    """One designed turn: ambition stays open, conduct stays stable, the hand is local."""

    soul = _as_dict(authored.soul)
    profile = _as_dict(authored.profile)
    character = state.characters[authored.id]
    motivation = _as_dict(profile.get("motivation", ()))
    horizon = world.dramatic_horizon
    known_facts = {
        fact_id: state.facts.get(fact_id, "")
        for fact_id in perception.known_fact_ids
    }
    return (
        "你是这个角色，只有自己眼里的信息。这一回合只决定眼前这一手。"
        "不能替别人回答，不能引用看不见的对象，不能直接改世界。\n"
        "三层不要混在一起：\n"
        "志向是整段路的方向，这一处完成不了。不要把它拆成在这里反复查证的清单。\n"
        "行事方式决定你怎么看、怎么说、怎么在冲突里站。它不随眼前的问题改口。\n"
        "眼前这一手从现场推出来，只做一件：\n"
        "有人在等你回应时，用你自己的方式回答，并填写 reply_to_interaction_id。\n"
        "现场写着这里的人已经把能说的说完了，就不要再问、再看、再比对。"
        "这一手是离开：dispatch 用 act，decision 写明离开。\n"
        "还没有人说过这一层时，只取和志向有关的那一层：问一个在场的人，或看一件眼前的东西，然后停。"
        "这里写明看不见的事，不要提前追问。\n"
        "场景问题是这一处的限度，不是第二个志向。\n"
        "不要重复自己上一手已经做过的动作，也不要把别人刚说完的话再说一遍。"
        "物品在别人手里时，只能向持有人请求。\n"
        "若 must_decide 为真，decision 必须写一条你公开承担的约束，内容是离开、交出、留下或拒绝。\n"
        "speech 只写说出口的话，最多一百二十个中文字符，不要复述动作或 decision。\n"
        "dispatch 只能是 think、address、act：心里权衡用 think；对在场的人说话用 address，"
        "并填写 address_target_id；只有离开、取放物品或改变大家都能看见的事实时用 act。\n"
        "只返回JSON对象："
        '{"goal":"这一手要做成的事","description":"以第一人称描述我要做什么",'
        '"dispatch":"think或address或act","address_target_id":null或"对象ID",'
        '"referenced_entity_ids":["..."],"speech":null或"实际说出的话",'
        '"private_reasoning":"不公开的理由",'
        '"reply_to_interaction_id":null或"待回应ID",'
        '"decision":null或"六十字以内、我公开承担的约束"}。输入：'
        + json.dumps(
            {
                "name": authored.name,
                "conduct": _conduct(soul),
                "skills": _as_list(profile.get("skills", ())),
                "only_i_know": _as_list(soul.get("secrets", ())),
                "ambition": {
                    "goals": list(character.goals),
                    "desire": str(motivation.get("terminal_desire", "")),
                    "fear": str(motivation.get("fear", "")),
                    "will_not": str(
                        motivation.get("sacrifice_boundary", "")
                    ),
                    "commitment": str(
                        motivation.get("active_commitment", "")
                    ),
                    "world_question": (
                        None
                        if horizon is None
                        else horizon.central_question
                    ),
                },
                "situation": perception.first_person_context,
                "visible_entity_ids": perception.visible_entity_ids,
                "known_facts": known_facts,
                "pending_interaction_ids": (
                    perception.pending_interaction_ids
                ),
                "must_decide": perception.decision_required,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, tuple):
        return dict(value)
    return {}


def _as_list(value: object) -> list[object]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _conduct(soul: Mapping[str, object]) -> dict[str, object]:
    kept = (
        "identity",
        "self_view",
        "protective_style",
        "voice",
        "values",
        "taboos",
        "relationship_stance",
        "beliefs",
        "drives",
    )
    return {
        key: _plain(soul[key]) for key in kept if key in soul
    }


def _decode_intent(
    value: object, perception: PerceptionView, tick: int
) -> CharacterIntent:
    if not isinstance(value, dict):
        raise ValueError("intent response must be an object")
    goal = _text(value, "goal")
    description = _text(value, "description")
    raw_references = value.get("referenced_entity_ids")
    if not isinstance(raw_references, list) or not all(
        isinstance(item, str) for item in raw_references
    ):
        raise ValueError("intent references must be a string list")
    references = list(raw_references)
    address_target = _optional_text(value.get("address_target_id"))
    if address_target is not None and address_target not in references:
        references.append(address_target)
    if not set(references).issubset(perception.visible_entity_ids):
        raise ValueError("intent references an entity outside perception")
    reply = _optional_text(value.get("reply_to_interaction_id"))
    decision = _optional_text(value.get("decision"))
    if decision is not None and len(decision) > 120:
        raise ValueError("intent decision exceeds 120 characters")
    if perception.decision_required and decision is None:
        raise ValueError(
            "high-pressure intent requires a binding decision"
        )
    if (
        reply is not None
        and reply not in perception.pending_interaction_ids
    ):
        raise ValueError("intent replies to an unknown interaction")
    intent_id = _intent_id(
        perception.actor_id,
        perception.scene_id,
        tick,
        goal,
        description,
    )
    speech = _optional_text(value.get("speech"))
    if speech is not None and len(speech) > 160:
        raise ValueError("intent speech exceeds 160 characters")
    dispatch = value.get("dispatch")
    if dispatch not in {"think", "address", "act"}:
        dispatch = (
            "address"
            if speech is not None
            and any(item != perception.scene_id for item in references)
            else "think"
            if speech is None
            else "act"
        )
    return CharacterIntent(
        intent_id,
        perception.actor_id,
        perception.scene_id,
        perception.scene_version,
        goal,
        description,
        tuple(dict.fromkeys(references)),
        speech,
        _optional_text(value.get("private_reasoning")),
        reply,
        decision,
        str(dispatch),
    )


def _fallback_intent(
    perception: PerceptionView, tick: int
) -> CharacterIntent:
    decision = (
        "我停止重复查验，在其他人作出决定前不再改变现场。"
        if perception.decision_required
        else None
    )
    description = (
        "我公开停止重复查验，并保留自己当前的承诺。"
        if decision
        else "我留在原处，先观察眼前的变化。"
    )
    return CharacterIntent(
        _intent_id(
            perception.actor_id,
            perception.scene_id,
            tick,
            "确认当前处境",
            description,
        ),
        perception.actor_id,
        perception.scene_id,
        perception.scene_version,
        "确认当前处境",
        description,
        (perception.scene_id,),
        decision=decision,
        dispatch="think",
    )


def _intent_id(
    actor_id: str,
    scene_id: str,
    tick: int,
    goal: str,
    description: str,
) -> str:
    payload = f"{actor_id}|{scene_id}|{tick}|{goal}|{description}"
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def _text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"intent field {key} must be non-empty text")
    return item.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("optional intent text must be non-empty")
    return value.strip()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value
