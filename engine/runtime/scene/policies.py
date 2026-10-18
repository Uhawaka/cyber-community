"""Deterministic fallbacks for the scene-turn workflow."""

from __future__ import annotations

import hashlib

from engine.contracts import AdjudicatedTurn, CharacterIntent, PerceptionView
from engine.runtime.kernel.state import WorldState


class DeterministicIntentPolicy:
    def decide(
        self, world: object, state: WorldState, perception: PerceptionView
    ) -> CharacterIntent:
        del world
        reply = (
            perception.pending_interaction_ids[0]
            if perception.pending_interaction_ids
            else None
        )
        goal = "回应眼前的交流" if reply else "确认当前处境"
        description = (
            "我回应刚才向我提出请求的人。"
            if reply
            else "我留在当前场景，观察在场的人和物。"
        )
        payload = (
            f"{perception.actor_id}|{perception.scene_id}|"
            f"{state.tick}|{goal}|{description}"
        )
        return CharacterIntent(
            hashlib.sha256(payload.encode()).hexdigest()[:20],
            perception.actor_id,
            perception.scene_id,
            perception.scene_version,
            goal,
            description,
            (perception.scene_id,),
            reply_to_interaction_id=reply,
        )


class DeterministicWorldAdjudicator:
    def adjudicate(
        self, world: object, state: WorldState, intent: CharacterIntent
    ) -> AdjudicatedTurn:
        del world, state
        return AdjudicatedTurn(
            intent.intent_id,
            intent.actor_id,
            intent.scene_id,
            intent.expected_scene_version,
            "accepted",
            intent.description,
            "我完成了自己描述的行动，但没有产生额外的持久变化。",
            spoken_text=intent.speech,
            rule_basis=("deterministic scene-turn fallback",),
        )
