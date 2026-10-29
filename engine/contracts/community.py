"""Versioned contracts for persistent community decisions and activities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from engine.contracts.intent import IntentPlan, IntentStep, intent_budget, validate_intent_steps
from engine.contracts.validation import require_int, require_sources, require_text

COMMUNITY_RUNTIME_VERSION = "community-runtime/v1"
COMMUNITY_PACKAGE_VERSION = "world-package/v1alpha3"
MINUTES_PER_TICK = 60
UTTERANCE_COOLDOWN_TICKS = 4
SPEECH_ACTS = frozenset({"", "request", "promise", "refuse", "clarify", "inform"})


class ActionVerb(str, Enum):
    WAIT = "wait"
    REST = "rest"
    MOVE = "move"
    INSPECT = "inspect"
    REPAIR = "repair"
    TAKE = "take"
    TRANSFER = "transfer"
    USE = "use"
    SPEAK = "speak"
    OFFER = "offer"
    ACCEPT = "accept"
    REJECT = "reject"
    COMMIT = "commit"
    LEARN = "learn"
    PURSUE = "pursue"
    ABANDON = "abandon"
    REQUEST = "request"
    HANDOFF = "handoff"
    RECORD = "record"
    READ = "read"
    LEND = "lend"
    REPAY = "repay"
    RESIGN = "resign"
    JOIN = "join"
    INVITE = "invite"
    TAKE_ROLE = "take_role"
    LEAVE_ROLE = "leave_role"
    CENSURE = "censure"
    LEASE = "lease"
    RETURN_LEASE = "return_lease"
    PLAN = "plan"
    ABANDON_PLAN = "abandon_plan"
    BRANCH_PLAN = "branch_plan"


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    actor_id: str
    verb: ActionVerb
    target_id: str
    intent: str
    source_refs: tuple[str, ...]
    expected_state_hash: str
    quantity: int = 1
    item_id: str = ""
    speech: str = ""
    reply_to: str = ""
    requested_item_id: str = ""
    requested_quantity: int = 0
    plan_steps: tuple[IntentStep, ...] = ()
    plan_budget: tuple[tuple[str, int], ...] = ()
    intent_plan_id: str = ""
    intent_step_index: int = -1
    plan_goal_id: str = ""
    plan_deadline_tick: int | None = None
    speech_act: str = ""
    topic_ref: str = ""

    def __post_init__(self) -> None:
        for field in ("proposal_id", "actor_id", "target_id", "intent", "expected_state_hash"):
            require_text(getattr(self, field), field)
        if not isinstance(self.verb, ActionVerb):
            raise ValueError("action requires a registered verb")
        require_sources(self.source_refs)
        require_int(self.quantity, "quantity", 1)
        if self.quantity > 100:
            raise ValueError("quantity exceeds action capacity")
        if not all(isinstance(value, str) for value in
                   (self.item_id, self.speech, self.reply_to, self.requested_item_id)):
            raise ValueError("action optional text must be strings")
        try:
            for value in (self.item_id, self.speech, self.reply_to, self.requested_item_id):
                value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("action optional text requires valid Unicode") from exc
        if len(self.speech) > 2000:
            raise ValueError("speech exceeds budget")
        if self.speech_act not in SPEECH_ACTS:
            raise ValueError("speech act must be request, promise, refuse, clarify, inform or empty")
        if not isinstance(self.topic_ref, str):
            raise ValueError("speech topic reference must be text")
        if len(self.topic_ref) > 200:
            raise ValueError("speech topic reference exceeds budget")
        if (self.speech_act or self.topic_ref) and self.verb is not ActionVerb.SPEAK:
            raise ValueError("speech act and topic reference require the speak action")
        require_int(self.requested_quantity, "requested_quantity")
        if self.requested_quantity > 100:
            raise ValueError("requested quantity exceeds action capacity")
        if not isinstance(self.plan_steps, (tuple, list)) or len(self.plan_steps) > 8:
            raise ValueError("invalid plan steps")
        steps = tuple(IntentStep(**step) if isinstance(step, dict) else step for step in self.plan_steps)
        if not all(isinstance(step, IntentStep) for step in steps):
            raise ValueError("invalid plan step")
        validate_intent_steps(steps)
        object.__setattr__(self, "plan_steps", steps)
        object.__setattr__(self, "plan_budget", intent_budget(self.plan_budget))
        if not isinstance(self.intent_plan_id, str):
            raise ValueError("plan reference must be text")
        if self.intent_plan_id:
            require_text(self.intent_plan_id, "plan reference")
        if (isinstance(self.intent_step_index, bool) or not isinstance(self.intent_step_index, int)
                or self.intent_step_index < -1):
            raise ValueError("plan step index must be an integer")
        if bool(self.intent_plan_id) != (self.intent_step_index >= 0):
            raise ValueError("plan selection requires id and step index")
        if not isinstance(self.plan_goal_id, str):
            raise ValueError("plan goal reference must be text")
        if self.plan_goal_id:
            require_text(self.plan_goal_id, "plan goal reference")
        if self.plan_deadline_tick is not None:
            require_int(self.plan_deadline_tick, "plan deadline")
        if self.verb is ActionVerb.PLAN:
            if not steps or self.intent_plan_id or self.target_id != self.actor_id:
                raise ValueError("plan creation requires own bounded steps")
        elif steps or self.plan_budget or self.plan_goal_id or self.plan_deadline_tick is not None:
            raise ValueError("steps and budget belong only to plan creation")


@dataclass(frozen=True)
class Activity:
    activity_id: str
    actor_id: str
    verb: ActionVerb
    target_id: str
    started_tick: int
    due_tick: int
    source_refs: tuple[str, ...]
    target_version: int = 0
    status: str = "pending"

    def __post_init__(self) -> None:
        for field in ("activity_id", "actor_id", "target_id"):
            require_text(getattr(self, field), field)
        require_int(self.started_tick, "started_tick")
        require_int(self.due_tick, "due_tick")
        require_int(self.target_version, "target_version")
        if self.due_tick <= self.started_tick:
            raise ValueError("activity must have positive duration")
        if self.status not in {"pending", "completed", "cancelled", "failed"}:
            raise ValueError("invalid activity status")
        require_sources(self.source_refs)


@dataclass(frozen=True)
class VisibleEntity:
    entity_id: str
    name: str
    kind: str
    features: tuple[str, ...]
    source_ref: str


@dataclass(frozen=True)
class PerceptionEnvelope:
    actor_id: str
    tick: int
    location_id: str
    description: str
    entities: tuple[VisibleEntity, ...] = ()
    known_routes: tuple[str, ...] = ()
    received_event_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.actor_id, "actor_id")
        require_text(self.location_id, "location_id")
        require_int(self.tick, "tick")
        if len(self.entities) > 64 or len(self.received_event_refs) > 32:
            raise ValueError("perception exceeds budget")


@dataclass(frozen=True)
class Goal:
    goal_id: str
    owner_id: str
    description: str
    source_refs: tuple[str, ...]
    priority: int = 50
    deadline_tick: int | None = None
    status: str = "active"
    target_id: str = ""
    action_verb: str = "wait"
    quantity: int = 1

    def __post_init__(self) -> None:
        for field in ("goal_id", "owner_id", "description"):
            require_text(getattr(self, field), field)
        require_sources(self.source_refs)
        require_int(self.priority, "priority")
        if self.priority > 100 or self.status not in {"active", "completed", "abandoned"}:
            raise ValueError("invalid goal state")
        if self.deadline_tick is not None:
            require_int(self.deadline_tick, "deadline_tick")
        if self.action_verb not in {"wait", "repair", "take", "learn", "move", "speak"}:
            raise ValueError("goal requires a registered completion criterion")
        require_int(self.quantity, "quantity", 1)
        if self.quantity > 100 or (self.action_verb != "wait" and not self.target_id):
            raise ValueError("goal requires bounded quantity and concrete target")


@dataclass(frozen=True)
class Plan:
    plan_id: str
    owner_id: str
    goal_id: str
    source_refs: tuple[str, ...]
    attempts: int = 0
    next_attempt_tick: int = 0
    status: str = "ready"

    def __post_init__(self) -> None:
        for field in ("plan_id", "owner_id", "goal_id"):
            require_text(getattr(self, field), field)
        require_sources(self.source_refs)
        require_int(self.attempts, "attempts")
        require_int(self.next_attempt_tick, "next_attempt_tick")
        if self.attempts > 8 or self.status not in {"ready", "blocked", "completed", "abandoned"}:
            raise ValueError("invalid plan lifecycle")


@dataclass(frozen=True)
class Commitment:
    commitment_id: str
    promisor_id: str
    beneficiary_id: str
    description: str
    source_refs: tuple[str, ...]
    deadline_tick: int
    status: str = "proposed"
    target_id: str = ""
    action_verb: str = "speak"
    quantity: int = 1

    def __post_init__(self) -> None:
        for field in ("commitment_id", "promisor_id", "beneficiary_id", "description"):
            require_text(getattr(self, field), field)
        require_sources(self.source_refs)
        require_int(self.deadline_tick, "deadline_tick")
        if self.status not in {"proposed", "accepted", "fulfilled", "breached", "rejected"}:
            raise ValueError("invalid commitment state")
        if self.promisor_id == self.beneficiary_id or self.action_verb not in {"speak", "repair", "transfer"}:
            raise ValueError("commitment requires distinct parties and registered criterion")
        require_int(self.quantity, "quantity", 1)
        if self.quantity > 100:
            raise ValueError("commitment quantity exceeds capacity")


@dataclass(frozen=True)
class KnownOperation:
    verb: ActionVerb
    target_id: str
    source_ref: str
    available_quantity: int = 0
    duration_ticks: int = 0
    inputs: tuple[tuple[str, int], ...] = ()
    learned_skill: str = ""
    use_effects: tuple[tuple[str, int], ...] = ()
    material_stock: tuple[tuple[str, int], ...] = ()
    restored_condition: int = 100
    reserved: bool = False


@dataclass(frozen=True)
class DecisionContext:
    actor_id: str
    state_hash: str
    perception: PerceptionEnvelope
    soul: tuple[tuple[str, str], ...]
    memories: tuple[tuple[str, str], ...]
    claims: tuple[tuple[str, str], ...]
    goals: tuple[Goal, ...]
    needs: tuple[tuple[str, int], ...]
    available_verbs: tuple[ActionVerb, ...]
    skills: tuple[str, ...] = ()
    plans: tuple[Plan, ...] = ()
    offers: tuple = ()
    commitments: tuple[Commitment, ...] = ()
    relationships: tuple[tuple[str, int], ...] = ()
    inventory: tuple[tuple[str, int], ...] = ()
    operations: tuple[KnownOperation, ...] = ()
    known_map: tuple[tuple[str, str, str], ...] = ()
    responsibilities: tuple[tuple[str, str], ...] = ()
    learning_interests: tuple[str, ...] = ()
    home_location_id: str = ""
    routine_locations: tuple[str, ...] = ()
    reported_claims: tuple[tuple[str, str], ...] = ()
    organizations: tuple = ()
    knowledge: tuple = ()
    learning_places: tuple[tuple[str, str, str], ...] = ()
    supply_places: tuple[tuple[str, str], ...] = ()
    requests: tuple = ()
    stocking_interests: tuple[str, ...] = ()
    stocking_places: tuple[tuple[str, str], ...] = ()
    known_repair_costs: tuple[KnownOperation, ...] = ()
    commitment_history: tuple[Commitment, ...] = ()
    handoffs: tuple = ()
    handoff_history: tuple = ()
    responsibility_sources: tuple[tuple[str, str], ...] = ()
    capabilities: tuple = ()
    maintenance_requirements: tuple[tuple[str, tuple[str, ...], str], ...] = ()
    organization_groups: tuple[tuple[str, tuple[str, ...]], ...] = ()
    organization_records: tuple[tuple[str, str, str, int], ...] = ()
    read_organization_records: tuple[str, ...] = ()
    recorded_organization_claims: tuple[tuple[str, str], ...] = ()
    loans: tuple = ()
    organization_roles: tuple[tuple[str, str, str, tuple[str, ...], tuple[str, ...]], ...] = ()
    leases: tuple = ()
    organization_seats: tuple[tuple[str, str, str, str, tuple[str, ...], tuple[str, ...]], ...] = ()
    membership_invitations: tuple[tuple[str, str, str], ...] = ()
    own_censures: tuple[tuple[str, str, int, int], ...] = ()
    sent_membership_invitations: tuple[tuple[str, str, str], ...] = ()
    invitation_groups: tuple[tuple[str, tuple[str, ...]], ...] = ()
    trust_sources: tuple[tuple[str, str], ...] = ()
    loaned_requests: tuple[str, ...] = ()
    intent_plans: tuple[IntentPlan, ...] = ()
    intent_plan_history: tuple[IntentPlan, ...] = ()
    plan_review_inputs: tuple[tuple[str, str, str, str, str, str], ...] = ()
    relationship_stances: tuple[tuple[str, str, str], ...] = ()
    recent_utterances: tuple[tuple[int, str], ...] = ()
    private_knowledge: tuple[tuple[str, str], ...] = ()
    pressing_need: str = ""
    told_secrets: tuple[str, ...] = ()
    confidences: tuple[tuple[str, str], ...] = ()
    leaked: tuple[tuple[str, str], ...] = ()
    danger_here: int = 0
    reachable: tuple[tuple[str, str], ...] = ()
    authored_goals: tuple[str, ...] = ()
    errands: tuple[tuple[str, str, str, str], ...] = ()
    requests_to_me: tuple[tuple[str, str, str], ...] = ()


class CommunityPolicy(Protocol):
    def propose(self, context: DecisionContext) -> ActionProposal: ...
