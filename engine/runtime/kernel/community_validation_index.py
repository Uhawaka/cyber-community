"""Committed-only authoritative validation indexes rebuilt by normal replay."""

from dataclasses import dataclass, field


@dataclass
class CommunityValidationIndex:
    commit_ids: set[str] = field(default_factory=set)
    activity_starts: dict[str, object] = field(default_factory=dict)
    activity_finishes: set[str] = field(default_factory=set)
    pending_actors: set[str] = field(default_factory=set)
    pending_repairs: set[str] = field(default_factory=set)
    membership_changes: dict[str, dict[str, bool]] = field(default_factory=dict)
    membership_exits: dict[tuple[str, str], int] = field(default_factory=dict)
    role_changes: dict[str, dict[str, tuple[int, str]]] = field(default_factory=dict)
    censures: set[tuple[str, str, str, int, int]] = field(default_factory=set)
    claims_by_actor: dict[str, set[object]] = field(default_factory=dict)
    invalid_claim_history: set[str] = field(default_factory=set)
    report_event_sequences_by_actor: dict[str, list[int]] = field(default_factory=dict)
    organization_records: dict[str, object] = field(default_factory=dict)
    model_request_count: int = 0
    model_budget: dict | None = None
    pending_model_attempts: dict[tuple[int, str | None], tuple[int, object | None]] = field(default_factory=dict)
    decision_tick: int | None = None
    decision_requests_or_actions: set[tuple[str | None, int]] = field(default_factory=set)
    decision_responses_or_actions: dict[tuple[str | None, int], int] = field(default_factory=dict)

    def add(self, event):
        identity = event.data.get("commit_id")
        if isinstance(identity, str):
            self.commit_ids.add(identity)
        if event.actor_id is not None and "claims" in event.data:
            try:
                identities = {raw["claim_id"] for raw in event.data["claims"]}
            except (TypeError, KeyError):
                self.invalid_claim_history.add(event.actor_id)
            else:
                self.claims_by_actor.setdefault(event.actor_id, set()).update(identities)
        kind = event.event_type.value
        report_owners = set()
        if event.actor_id is not None and "claims" in event.data:
            report_owners.add(event.actor_id)
        if kind in {"inspected", "activity_finished", "dialogue", "organization_censured", "organization_read"}:
            report_owners.update(event.observers)
            if event.actor_id is not None:
                report_owners.add(event.actor_id)
        for owner in report_owners:
            self.report_event_sequences_by_actor.setdefault(owner, []).append(event.sequence)
        if self.decision_tick != event.tick:
            self.decision_tick = event.tick
            self.decision_requests_or_actions.clear()
            self.decision_responses_or_actions.clear()
        decision_key = (event.actor_id, event.tick)
        if event.delta.actions or kind in {"model_decision_requested", "action_rejected"}:
            self.decision_requests_or_actions.add(decision_key)
        if event.delta.actions or kind in {"model_decision_resolved", "action_rejected"}:
            self.decision_responses_or_actions[decision_key] = event.sequence
        if kind == "model_decision_requested":
            self.model_request_count += 1
            if self.model_budget is None:
                self.model_budget = dict(event.data["model_budget"])
            self.pending_model_attempts[(event.tick, event.actor_id)] = (event.sequence, None)
        elif kind == "model_decision_resolved":
            key = (event.tick, event.actor_id)
            self.pending_model_attempts[key] = (event.data["model_response"]["request_sequence"],
                                                event.data["model_response"])
        if event.delta.actions or kind == "action_rejected":
            self.pending_model_attempts.pop((event.tick, event.actor_id), None)
        if kind == "activity_started":
            raw = event.data["activity"]
            self.activity_starts[raw["activity_id"]] = event
            self.pending_actors.add(event.actor_id)
            if raw["verb"] == "repair":
                self.pending_repairs.add(raw["target_id"])
        elif kind == "activity_finished":
            identity = event.data["activity_id"]
            self.activity_finishes.add(identity)
            start = self.activity_starts[identity]
            self.pending_actors.discard(start.actor_id)
            if start.data["activity"]["verb"] == "repair":
                self.pending_repairs.discard(start.data["activity"]["target_id"])
        elif kind == "membership_updated":
            status = event.data["membership"]["status"]
            if status in {"joined", "left"}:
                group = event.target_entity_id
                self.membership_changes.setdefault(group, {})[event.actor_id] = status == "joined"
                if status == "left":
                    self.membership_exits[(group, event.actor_id)] = event.sequence
        elif kind == "organization_role_updated":
            role = event.data["role"]
            holder = role["holder_id"] if role["status"] == "held" else ""
            self.role_changes.setdefault(event.target_entity_id, {})[role["role_id"]] = (
                event.sequence, holder,
            )
        elif kind == "organization_censured":
            notice = event.data["censure"]
            self.censures.add(tuple(notice[key] for key in (
                "organization_id", "issuer_id", "subject_id", "norm_index", "evidence_sequence",
            )))
        elif kind == "organization_recorded":
            self.organization_records.setdefault(event.data["record"]["record_id"], event)
