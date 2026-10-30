"""One bounded model decision from owned, source-labelled context."""

from __future__ import annotations

from dataclasses import asdict
import json
import math
from hashlib import sha256

from engine.contracts.community import ActionProposal, ActionVerb, IntentStep
from engine.contracts.intent import INTENT_STEP_VERBS, ready_intent_steps
from engine.runtime.character.community_context import resolve_visible_claim_refs

MAX_MODEL_PROMPT_BYTES = 131072


class ModelCommunityPolicy:
    records_model_attempts = True
    version = "community-model-policy/v20"

    def __init__(self, model, *, timeout_seconds=10.0, max_requests=1000):
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 600
                or isinstance(max_requests, bool) or not isinstance(max_requests, int)
                or not 0 <= max_requests <= 100000):
            raise ValueError("invalid community model budget")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_requests = max_requests
        self.requests = 0

    def for_run(self):
        return ModelCommunityPolicy(self.model, timeout_seconds=self.timeout_seconds, max_requests=self.max_requests)

    def managed_identity(self):
        from engine.adapters.openai_compatible import OpenAICompatibleTextModel
        if type(self.model) is OpenAICompatibleTextModel:
            model = self.model
            values = {"provider": model.provider, "model": model.model, "temperature": model.temperature,
                      "max_tokens": model.max_tokens,
                      "endpoint_sha256": sha256(model.base_url.encode()).hexdigest(), "transport_attempts": 1}
        else:
            identity = getattr(self.model, "community_identity", None)
            if not isinstance(identity, str) or not identity.strip() or len(identity) > 2000:
                raise ValueError("custom managed model must declare community_identity")
            values = {"implementation": f"{type(self.model).__module__}.{type(self.model).__qualname__}",
                      "identity": identity}
        return sha256(json.dumps(values, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def propose(self, context):
        if self.requests >= self.max_requests:
            raise RuntimeError("community model request budget exhausted")
        self.requests += 1
        return self.interpret(context, self.complete(context))

    def complete(self, context):
        """One model call. Safe to run beside other characters from the same snapshot."""
        from engine.adapters.community_prompt import decision_prompt
        from engine.runtime.character.community_window import assemble_window
        prompt = decision_prompt(assemble_window(context))
        if len(prompt.encode("utf-8")) > MAX_MODEL_PROMPT_BYTES:
            raise ValueError("model input exceeds decision budget")
        from engine.adapters.openai_compatible import OpenAICompatibleTextModel
        complete = self.model.complete_once if type(self.model) is OpenAICompatibleTextModel else self.model.complete
        return complete(prompt, timeout_seconds=self.timeout_seconds)

    def interpret(self, context, answer):
        if not isinstance(answer, str) or len(answer) > 8000:
            raise ValueError("model response exceeds decision budget")
        try:
            raw = json.loads(answer)
        except RecursionError as exc:
            raise ValueError("model decision nesting exceeds budget") from exc
        if isinstance(raw, dict) and "source_refs" in raw:
            raw["source_refs"] = resolve_visible_claim_refs(context, raw["source_refs"])
        if isinstance(raw, dict) and "intent_kind" in raw:
            kind = raw["intent_kind"]
            if not isinstance(raw.get("source_refs"), list):
                raise ValueError("invalid structured intention")
            if kind in ("navigate", "navigate_plan") and set(raw) == {"intent_kind", "target_id", "intent", "source_refs"}:
                from engine.runtime.character.community_intents import compile_navigation, compile_navigation_plan
                compiler = compile_navigation if kind == "navigate" else compile_navigation_plan
                return compiler(context, raw["target_id"], raw["intent"], raw["source_refs"])
            if (kind == "plan"
                    and {"intent_kind", "intent", "source_refs", "steps"} <= set(raw)
                    and set(raw) <= {"intent_kind", "intent", "source_refs", "steps", "budget", "goal_id", "deadline_tick"}):
                if not isinstance(raw["steps"], list) or not 1 <= len(raw["steps"]) <= 8:
                    raise ValueError("invalid structured plan steps")
                try:
                    steps = tuple(IntentStep(**step) for step in raw["steps"])
                except (TypeError, ValueError) as exc:
                    raise ValueError("invalid structured plan steps") from exc
                return ActionProposal(
                    f"decision:{context.actor_id}:{context.perception.tick}", context.actor_id,
                    ActionVerb.PLAN, context.actor_id, raw["intent"], tuple(raw["source_refs"]),
                    context.state_hash, plan_steps=steps, plan_budget=raw.get("budget", ()),
                    plan_goal_id=raw.get("goal_id", ""), plan_deadline_tick=raw.get("deadline_tick"),
                )
            if kind == "continue_plan" and set(raw) in (
                {"intent_kind", "plan_id", "intent", "source_refs"},
                {"intent_kind", "plan_id", "intent", "source_refs", "step_index"},
            ):
                plan = next((p for p in context.intent_plans if p.plan_id == raw["plan_id"]), None)
                if plan is None or plan.owner_id != context.actor_id or plan.status not in {"ready", "blocked"}:
                    raise ValueError("personal plan is unavailable")
                index = raw.get("step_index", plan.cursor)
                if (isinstance(index, bool) or not isinstance(index, int)
                        or index not in (ready_intent_steps(plan) if plan.status == "ready" else (plan.cursor,))):
                    raise ValueError("plan step dependencies are not satisfied")
                step = plan.steps[index]
                return ActionProposal(
                    f"decision:{context.actor_id}:{context.perception.tick}", context.actor_id,
                    ActionVerb(step.verb), step.target_id, raw["intent"], tuple(raw["source_refs"]),
                    context.state_hash, quantity=step.quantity, item_id=step.item_id, speech=step.speech,
                    intent_plan_id=plan.plan_id, intent_step_index=index,
                )
            raise ValueError("invalid structured intention")
        allowed = {"verb", "target_id", "intent", "source_refs", "quantity", "item_id", "speech", "reply_to",
                   "requested_item_id", "requested_quantity", "speech_act", "topic_ref"}
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError("model decision has unknown fields")
        if not {"verb", "target_id", "intent", "source_refs"} <= set(raw):
            raise ValueError("model decision is missing required fields")
        if not isinstance(raw.get("source_refs"), list):
            raise ValueError("model decision needs source_refs")
        return ActionProposal(
            f"decision:{context.actor_id}:{context.perception.tick}", context.actor_id,
            ActionVerb(raw["verb"]), raw["target_id"], raw["intent"],
            tuple(raw["source_refs"]), context.state_hash, raw.get("quantity", 1),
            raw.get("item_id", ""), raw.get("speech", ""), raw.get("reply_to", ""),
            raw.get("requested_item_id", ""), raw.get("requested_quantity", 0),
            speech_act=raw.get("speech_act", ""), topic_ref=raw.get("topic_ref", ""),
        )
