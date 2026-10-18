"""Pure services for user gates and shared opportunity resolution."""

from __future__ import annotations

from dataclasses import replace
from typing import TypeVar

from engine.participation.contracts import (
    ContextT,
    GateDecision,
    GateStatus,
    InterventionAttempt,
    Opportunity,
    OpportunityResolver,
    UserGate,
)


ResultT = TypeVar("ResultT")


def resolve_intervention(
    opportunity: Opportunity[ContextT],
    attempt: InterventionAttempt,
    resolver: OpportunityResolver[
        ContextT,
        InterventionAttempt,
        ResultT,
    ],
) -> ResultT:
    """Route Avatar and NPC attempts through the same consequence port."""

    if attempt.opportunity_id != opportunity.opportunity_id:
        raise ValueError("attempt does not belong to this opportunity")
    if attempt.participant_id != opportunity.participant_id:
        raise ValueError("attempt participant does not own this opportunity")
    return resolver.resolve(opportunity, attempt)


def answer_gate(
    gate: UserGate,
    decision: GateDecision,
    *,
    answered_at: float,
) -> UserGate:
    if gate.status is not GateStatus.PENDING:
        raise ValueError("gate is already closed")
    if answered_at >= gate.deadline:
        return expire_gate(gate, now=answered_at)
    return replace(
        gate,
        status=GateStatus.ANSWERED,
        decision=decision,
    )


def expire_gate(gate: UserGate, *, now: float) -> UserGate:
    """Apply the authored abstention default once the deadline is reached."""

    if gate.status is not GateStatus.PENDING:
        return gate
    if now < gate.deadline:
        return gate
    return replace(
        gate,
        status=GateStatus.EXPIRED,
        decision=gate.default,
    )
