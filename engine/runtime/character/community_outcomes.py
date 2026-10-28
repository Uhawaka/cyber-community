"""Disposable committed-result candidates, indexed without changing authority."""

from bisect import bisect_right
from dataclasses import dataclass, field
from heapq import merge

from engine.runtime.kernel.community_obligation_outcomes import obligation_outcome_matches
from engine.runtime.kernel.community_request_validation import matches_request_delivery


@dataclass
class OutcomeIndex:
    candidates: dict[tuple[str, str, str, str], list[int]] = field(default_factory=dict)
    activity_starts: dict[str, int] = field(default_factory=dict)

    def add(self, event):
        kind, data = event.event_type.value, event.data
        key = None
        if kind == "activity_started":
            self.activity_starts[data["activity"]["activity_id"]] = event.sequence
        elif kind == "activity_finished" and data.get("status") == "completed":
            key = ("repair", event.actor_id, "", event.target_entity_id)
        elif kind == "dialogue" and data.get("listener_id"):
            key = ("speak", event.actor_id, data["listener_id"], "")
        elif kind == "exchange_updated" and data["offer"]["status"] == "accepted":
            offer = data["offer"]
            key = ("transfer", offer["sender_id"], offer["recipient_id"], offer["item_id"])
        elif kind == "loan_updated" and data["loan"]["status"] == "accepted":
            loan = data["loan"]
            key = ("loan_delivery", loan["lender_id"], loan["borrower_id"], loan["item_id"])
        if key is not None:
            self.candidates.setdefault(key, []).append(event.sequence)

    def after(self, key, sequence, deadline, events):
        candidates = self.candidates.get(key, ())
        for position in range(bisect_right(candidates, sequence), len(candidates)):
            event = events[candidates[position]]
            if event.tick > deadline:
                break
            yield event

    def obligation(self, obligation, accepted_sequence, events):
        verb = obligation.action_verb
        key = (verb, obligation.promisor_id,
               "" if verb == "repair" else obligation.beneficiary_id,
               "" if verb == "speak" else obligation.target_id)
        for event in self.after(key, accepted_sequence, obligation.deadline_tick, events):
            if obligation_outcome_matches(obligation, event, events, activity_starts=self.activity_starts):
                return event
        return None

    def delivery(self, request, origin_sequence, events):
        parties = (request.helper_id, request.requester_id, request.item_id)
        deliveries = merge(
            self.after(("transfer", *parties), origin_sequence, request.deadline_tick, events),
            self.after(("loan_delivery", *parties), origin_sequence, request.deadline_tick, events),
            key=lambda event: event.sequence,
        )
        return next((event for event in deliveries if matches_request_delivery(request, event)), None)
