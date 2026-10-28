"""Run-local, disposable projections reconstructed from community events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.contracts.community import Activity, ActionVerb, Commitment, Goal, IntentPlan, Plan
from engine.contracts.cognition import KnowledgeClaim, MemoryRecord
from engine.contracts.society import (
    ExchangeOffer, MaterialRequest, ResponsibilityHandoff, OrganizationRecord, MaterialLoan, MaterialLease, decode_organization_record,
)
from engine.runtime.kernel.events import EventType
from engine.runtime.character.community_memory import MemoryIndex, memory_from_event
from engine.runtime.character.community_knowledge import OwnedClaims, claims_from_event, public_claim, seed_claim, skill_claims
from engine.runtime.character.community_pending import PendingRecords
from engine.runtime.character.community_outcomes import OutcomeIndex
from engine.runtime.character.community_goal_index import GoalEvidenceIndex


@dataclass
class CommunityProjection:
    cursor: int = 0
    activities: dict[str, Activity] = field(default_factory=dict)
    goals: PendingRecords = field(default_factory=lambda: PendingRecords(
        "goal_id", {"active"}, ("owner_id",)))
    plans: PendingRecords = field(default_factory=lambda: PendingRecords(
        "plan_id", {"ready", "blocked"}, ("owner_id",)))
    intent_plans: PendingRecords = field(default_factory=lambda: PendingRecords(
        "plan_id", {"ready", "blocked"}, ("owner_id",)))
    intent_plan_sequences: dict[str, int] = field(default_factory=dict)
    goal_evidence: GoalEvidenceIndex = field(default_factory=GoalEvidenceIndex)
    commitments: PendingRecords = field(default_factory=lambda: PendingRecords(
        "commitment_id", {"proposed", "accepted"}, ("promisor_id", "beneficiary_id")))
    offers: PendingRecords = field(default_factory=lambda: PendingRecords(
        "offer_id", {"proposed"}, ("sender_id", "recipient_id")))
    requests: PendingRecords = field(default_factory=lambda: PendingRecords(
        "request_id", {"open"}, ("requester_id", "helper_id")))
    handoffs: PendingRecords = field(default_factory=lambda: PendingRecords(
        "handoff_id", {"proposed"}, ("sender_id", "recipient_id")))
    loans: PendingRecords = field(default_factory=lambda: PendingRecords(
        "loan_id", {"proposed", "accepted"}, ("lender_id", "borrower_id")))
    leases: PendingRecords = field(default_factory=lambda: PendingRecords(
        "lease_id", {"proposed", "accepted"}, ("lessor_id", "lessee_id")))
    social_origins: dict[tuple[str, str, str], int] = field(default_factory=dict)
    social_latest: dict[tuple[str, str], int] = field(default_factory=dict)
    loan_proposal_sources: dict[str, set[tuple[str, str, str]]] = field(default_factory=dict)
    last_decisions: dict[str, int] = field(default_factory=dict)
    last_wakeups: dict[str, int] = field(default_factory=dict)
    outcomes: OutcomeIndex = field(default_factory=OutcomeIndex)
    organization_records: dict[str, OrganizationRecord] = field(default_factory=dict)
    records_by_group: dict[str, list[str]] = field(default_factory=dict)
    records_by_author: dict[str, list[str]] = field(default_factory=dict)
    record_sequences: dict[str, int] = field(default_factory=dict)
    reported_claims: dict[str, set[tuple[str, str]]] = field(default_factory=dict)
    read_organization_records: set[tuple[str, str]] = field(default_factory=set)
    read_records_by_owner: dict[str, set[str]] = field(default_factory=dict)
    memberships: set[tuple[str, str]] = field(default_factory=set)
    membership_invitations: dict[tuple[str, str], int] = field(default_factory=dict)
    sent_membership_invitations: dict[str, set[tuple[str, str, str]]] = field(default_factory=dict)
    role_holders: dict[tuple[str, str], str] = field(default_factory=dict)
    censures: dict[int, Any] = field(default_factory=dict)
    censures_by_issuer: dict[str, list[int]] = field(default_factory=dict)
    responsibilities: set[tuple[str, str]] = field(default_factory=set)
    responsibility_sources: dict[tuple[str, str], str] = field(default_factory=dict)
    subjective_trust: dict[tuple[str, str], int] = field(default_factory=dict)
    trust_sources: dict[tuple[str, str], str] = field(default_factory=dict)
    memories: dict[str, MemoryRecord] = field(default_factory=dict)
    claims: OwnedClaims = field(default_factory=OwnedClaims)
    learned_skills: dict[str, set[str]] = field(default_factory=dict)
    index: MemoryIndex = field(default_factory=MemoryIndex)

    def seed(self, compiled) -> None:
        from engine.runtime.kernel.community_handoff_validation import responsibility_assignments
        self.responsibilities = responsibility_assignments(compiled.world)
        self.memberships = {(group.organization_id, member) for group in compiled.community.organizations
                            for member in group.member_ids}
        self.role_holders = {(group.organization_id, role.role_id): role.initial_holder_id
                             for group in compiled.community.organizations for role in group.roles}
        for character in compiled.world.characters:
            for claim in skill_claims(character):
                self.claims[claim.claim_id] = claim
            for number, text in enumerate(compiled.community.public_knowledge):
                claim = public_claim(character.id, compiled.world.world_id, number, text)
                self.claims[claim.claim_id] = claim
            for number, item in enumerate(character.memory_seed):
                summary = str(item.get("summary") or "").strip()
                if not summary:
                    continue
                source = f"seed:{character.id}:{number}"
                kind = str(item.get("kind", "belief"))
                record = MemoryRecord(
                    f"memory:{source}", character.id, 0, summary, (source,),
                    "observation" if kind == "observation" else "experience" if kind == "experience" else "inference",
                    tuple(item.get("participants", ())), tuple(item.get("entity_ids", ())),
                    tuple(item.get("topics", ())), int(item.get("importance", 70)),
                    str(item.get("tier", "autobiographical" if kind == "experience" else "semantic")),
                )
                self.memories[record.memory_id] = record
                self.index.add(record)
                claim = seed_claim(character, number, item)
                if claim is not None:
                    self.claims[claim.claim_id] = claim

    def consume(self, events) -> None:
        for event in events[self.cursor:]:
            data = event.data
            self.outcomes.add(event)
            self.goal_evidence.add(event)
            if event.event_type is EventType.DIALOGUE and data.get("reported_claim"):
                signature = "|".join(str(data["reported_claim"][key])
                                     for key in ("subject", "predicate", "content"))
                self.reported_claims.setdefault(event.actor_id, set()).update(
                    (listener, signature) for listener in event.observers if listener != event.actor_id
                )
            if event.actor_id and (event.delta.actions or event.event_type is EventType.ACTION_REJECTED):
                self.last_decisions[event.actor_id] = event.sequence
            if event.event_type.value in {
                "dialogue", "activity_finished", "commitment_updated", "exchange_updated",
                "request_updated", "responsibility_updated", "process_settled", "loan_updated", "lease_updated", "membership_updated",
                "organization_role_updated", "organization_censured",
            }:
                for owner in event.observers:
                    self.last_wakeups[owner] = event.sequence
            for kind, identity in (("commitment", "commitment_id"), ("offer", "offer_id"),
                                   ("request", "request_id"), ("handoff", "handoff_id"), ("loan", "loan_id")):
                if kind in data:
                    raw = data[kind]
                    self.social_origins.setdefault((kind, raw[identity], raw["status"]), event.sequence)
                    self.social_latest[(kind, raw[identity])] = event.sequence
            if event.event_type is EventType.ACTIVITY_STARTED:
                activity = decode_activity(data["activity"])
                self.activities[activity.activity_id] = activity
            elif event.event_type is EventType.ACTIVITY_FINISHED:
                self.activities.pop(str(data["activity_id"]), None)
                if data.get("status") == "completed" and data.get("learned_skill"):
                    self.learned_skills.setdefault(event.actor_id, set()).add(data["learned_skill"])
            elif event.event_type is EventType.COGNITION_RECORDED:
                for raw in data.get("memories", ()):
                    record = decode_memory(raw)
                    self.memories[record.memory_id] = record
                    self.index.add(record)
                for raw in data.get("claims", ()):
                    claim = decode_claim(raw)
                    self.claims[claim.claim_id] = claim
            elif event.event_type is EventType.GOAL_UPDATED:
                goal = Goal(**{**data["goal"], "source_refs": tuple(data["goal"]["source_refs"])})
                self.goals[goal.goal_id] = goal
            elif event.event_type is EventType.PLAN_UPDATED:
                raw = data["plan"]
                plan = Plan(**{**raw, "source_refs": tuple(raw["source_refs"])})
                self.plans[plan.plan_id] = plan
            elif event.event_type is EventType.INTENT_PLAN_UPDATED:
                raw = data["intent_plan"]
                plan = IntentPlan(**{**raw, "source_refs": tuple(raw["source_refs"])})
                prior = self.intent_plans.get(plan.plan_id)
                if prior is not None and not prior.deadline_reached and plan.deadline_reached:
                    self.last_wakeups[plan.owner_id] = event.sequence
                self.intent_plans[plan.plan_id] = plan
                self.intent_plan_sequences[plan.plan_id] = event.sequence
            elif event.event_type is EventType.COMMITMENT_UPDATED:
                raw = data["commitment"]
                commitment = Commitment(**{**raw, "source_refs": tuple(raw["source_refs"])})
                self.commitments[commitment.commitment_id] = commitment
                if commitment.status in {"fulfilled", "breached"} and commitment.beneficiary_id in event.observers:
                    key = (commitment.beneficiary_id, commitment.promisor_id)
                    change = 5 if commitment.status == "fulfilled" else -10
                    self.subjective_trust[key] = max(-100, min(100, self.subjective_trust.get(key, 0) + change))
                    self.trust_sources[key] = f"event:{event.sequence}"
            elif event.event_type is EventType.EXCHANGE_UPDATED:
                raw = data["offer"]
                offer = ExchangeOffer(**{**raw, "source_refs": tuple(raw["source_refs"])})
                self.offers[offer.offer_id] = offer
            elif event.event_type is EventType.REQUEST_UPDATED:
                raw = data["request"]
                request = MaterialRequest(**{**raw, "source_refs": tuple(raw["source_refs"])})
                self.requests[request.request_id] = request
            elif event.event_type is EventType.RESPONSIBILITY_UPDATED:
                raw = data["handoff"]
                handoff = ResponsibilityHandoff(**{**raw, "source_refs": tuple(raw["source_refs"])})
                self.handoffs[handoff.handoff_id] = handoff
                if handoff.status == "accepted":
                    self.responsibilities.discard((handoff.sender_id, handoff.target_id))
                    self.responsibilities.add((handoff.recipient_id, handoff.target_id))
                    self.responsibility_sources.pop((handoff.sender_id, handoff.target_id), None)
                    self.responsibility_sources[(handoff.recipient_id, handoff.target_id)] = f"event:{event.sequence}"
            elif event.event_type is EventType.ORGANIZATION_RECORDED:
                record = decode_organization_record(data["record"])
                self.organization_records[record.record_id] = record
                self.records_by_group.setdefault(record.organization_id, []).append(record.record_id)
                self.records_by_author.setdefault(record.author_id, []).append(record.record_id)
                self.record_sequences[record.record_id] = event.sequence
            elif event.event_type is EventType.MEMBERSHIP_UPDATED:
                raw = data["membership"]
                if raw["status"] == "invited":
                    self.membership_invitations[(event.target_entity_id, raw["member_id"])] = event.sequence
                    self.sent_membership_invitations.setdefault(event.actor_id, set()).update(
                        (event.target_entity_id, raw["member_id"], source)
                        for source in data.get("source_refs", ())
                    )
                elif raw["status"] == "joined":
                    self.memberships.add((event.target_entity_id, event.actor_id))
                    self.membership_invitations.pop((event.target_entity_id, event.actor_id), None)
                elif raw["status"] == "left":
                    self.memberships.discard((event.target_entity_id, event.actor_id))
                    for key, holder in self.role_holders.items():
                        if key[0] == event.target_entity_id and holder == event.actor_id:
                            self.role_holders[key] = ""
            elif event.event_type is EventType.ORGANIZATION_ROLE_UPDATED:
                raw = data["role"]
                self.role_holders[(raw["organization_id"], raw["role_id"])] = (
                    raw["holder_id"] if raw["status"] == "held" else ""
                )
            elif event.event_type is EventType.ORGANIZATION_CENSURED:
                from engine.contracts.society import OrganizationCensure
                self.censures[event.sequence] = OrganizationCensure(**data["censure"])
                self.censures_by_issuer.setdefault(event.actor_id, []).append(event.sequence)
            elif event.event_type is EventType.ORGANIZATION_READ:
                identity = data["record"]["record_id"]
                self.read_organization_records.add((event.actor_id, identity))
                self.read_records_by_owner.setdefault(event.actor_id, set()).add(identity)
            elif event.event_type is EventType.LOAN_UPDATED:
                raw = data["loan"]
                loan = MaterialLoan(**{**raw, "source_refs": tuple(raw["source_refs"])})
                self.loans[loan.loan_id] = loan
                if loan.status == "proposed":
                    self.loan_proposal_sources.setdefault(loan.lender_id, set()).update(
                        (loan.borrower_id, loan.item_id, source) for source in loan.source_refs
                    )
                if loan.status == "overdue" and loan.lender_id in event.observers:
                    key = (loan.lender_id, loan.borrower_id)
                    self.subjective_trust[key] = max(-100, self.subjective_trust.get(key, 0) - 10)
                    self.trust_sources[key] = f"event:{event.sequence}"
            elif event.event_type is EventType.LEASE_UPDATED:
                raw = data["lease"]
                record = MaterialLease(**{**raw, "source_refs": tuple(raw["source_refs"])})
                self.leases[record.lease_id] = record
                self.social_origins[("lease", record.lease_id, record.status)] = event.sequence
                self.social_latest[("lease", record.lease_id)] = event.sequence
            authors = {event.actor_id} if event.actor_id and not data.get("system_update") else set()
            for owner_id in sorted(set(event.observers) | authors):
                record = memory_from_event(event, owner_id)
                if record is not None:
                    self.memories[record.memory_id] = record
                    self.index.add(record)
                for claim in claims_from_event(event, owner_id, self.claims):
                    self.claims[claim.claim_id] = claim
            self.cursor = event.sequence + 1

    def pending_for(self, actor_id: str) -> tuple[Activity, ...]:
        return tuple(a for a in self.activities.values() if a.actor_id == actor_id)


def decode_activity(raw: Any) -> Activity:
    return Activity(**{
        **raw, "verb": ActionVerb(raw["verb"]),
        "source_refs": tuple(raw["source_refs"]),
    })


def decode_memory(raw: Any) -> MemoryRecord:
    return MemoryRecord(**{
        **raw, **{key: tuple(raw.get(key, ())) for key in (
            "source_refs", "participants", "entity_ids", "topics",
        )},
    })


def decode_claim(raw: Any) -> KnowledgeClaim:
    return KnowledgeClaim(**{
        **raw, "source_refs": tuple(raw["source_refs"]),
        "contradicts": tuple(raw.get("contradicts", ())),
    })


def community_projection(run) -> CommunityProjection:
    cached = getattr(run, "_community_projection", None)
    if cached is None or cached.cursor > len(run.events):
        cached = CommunityProjection()
        cached.seed(run.compiled)
        run._community_projection = cached
    cached.consume(run.events)
    return cached
