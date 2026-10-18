"""Pure transition services for soul proposals and character schemes."""

from __future__ import annotations

from dataclasses import replace
from typing import TypeVar

from engine.runtime.character.contracts import (
    ProposalStatus,
    Scheme,
    SchemeStatus,
    SoulEvolutionProposal,
)


StateT = TypeVar("StateT")


def propose_soul_evolution(
    *,
    proposal_id: str,
    character_id: str,
    trait: str,
    proposed_value: object,
    evidence_event_ids: tuple[str, ...],
    magnitude: float,
    current_version: int,
    last_evolution_version: int | None,
    cooldown_versions: int,
    maximum_magnitude: float = 0.25,
) -> SoulEvolutionProposal:
    """Create an evidence-backed, bounded proposal after cooldown."""

    if cooldown_versions < 0:
        raise ValueError("cooldown must be non-negative")
    if not 0.0 < maximum_magnitude <= 1.0:
        raise ValueError("maximum magnitude must be in (0, 1]")
    if magnitude > maximum_magnitude:
        raise ValueError("soul proposal exceeds maximum magnitude")
    if (
        last_evolution_version is not None
        and current_version < last_evolution_version + cooldown_versions
    ):
        raise ValueError("soul evolution is still in cooldown")
    return SoulEvolutionProposal(
        proposal_id=proposal_id,
        character_id=character_id,
        trait=trait,
        proposed_value=proposed_value,
        evidence_event_ids=evidence_event_ids,
        magnitude=magnitude,
        proposed_at_version=current_version,
        cooldown_until_version=current_version + cooldown_versions,
    )


def approve_soul_evolution(
    proposal: SoulEvolutionProposal,
    *,
    reason: str,
) -> SoulEvolutionProposal:
    return _decide_proposal(proposal, ProposalStatus.APPROVED, reason)


def reject_soul_evolution(
    proposal: SoulEvolutionProposal,
    *,
    reason: str,
) -> SoulEvolutionProposal:
    return _decide_proposal(proposal, ProposalStatus.REJECTED, reason)


def advance_scheme(
    scheme: Scheme[StateT],
    *,
    progress: float,
) -> Scheme[StateT]:
    """Set monotonic absolute progress and derive lifecycle status."""

    if scheme.status in {
        SchemeStatus.COMPLETED,
        SchemeStatus.ABANDONED,
        SchemeStatus.INVALIDATED,
    }:
        raise ValueError("terminal scheme cannot advance")
    if progress < scheme.progress:
        raise ValueError("scheme progress cannot move backwards")
    if not 0.0 <= progress <= 1.0:
        raise ValueError("scheme progress must be between 0 and 1")
    status = (
        SchemeStatus.COMPLETED
        if progress == 1.0
        else SchemeStatus.ACTIVE
    )
    return replace(scheme, progress=progress, status=status)


def abandon_scheme(scheme: Scheme[StateT]) -> Scheme[StateT]:
    if scheme.status in {SchemeStatus.COMPLETED, SchemeStatus.INVALIDATED}:
        raise ValueError("terminal scheme cannot be abandoned")
    return replace(scheme, status=SchemeStatus.ABANDONED)


def invalidate_scheme(scheme: Scheme[StateT]) -> Scheme[StateT]:
    if scheme.status in {
        SchemeStatus.COMPLETED,
        SchemeStatus.ABANDONED,
        SchemeStatus.INVALIDATED,
    }:
        raise ValueError("terminal scheme cannot be invalidated")
    return replace(scheme, status=SchemeStatus.INVALIDATED)


def _decide_proposal(
    proposal: SoulEvolutionProposal,
    status: ProposalStatus,
    reason: str,
) -> SoulEvolutionProposal:
    if proposal.status is not ProposalStatus.PENDING:
        raise ValueError("soul proposal is already decided")
    if not reason.strip():
        raise ValueError("proposal decision requires a reason")
    return replace(
        proposal,
        status=status,
        decision_reason=reason.strip(),
    )
