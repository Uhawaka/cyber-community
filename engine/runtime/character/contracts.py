"""Reusable character-development contracts independent of runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar


StateT = TypeVar("StateT")


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SchemeStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class SoulEvolutionProposal:
    proposal_id: str
    character_id: str
    trait: str
    proposed_value: object
    evidence_event_ids: tuple[str, ...]
    magnitude: float
    proposed_at_version: int
    cooldown_until_version: int
    status: ProposalStatus = ProposalStatus.PENDING
    decision_reason: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.proposal_id,
                self.character_id,
                self.trait,
            )
        ):
            raise ValueError("soul proposal requires ids and a trait")
        if not self.evidence_event_ids or any(
            not event_id.strip() for event_id in self.evidence_event_ids
        ):
            raise ValueError("soul proposal requires event evidence")
        if len(set(self.evidence_event_ids)) != len(self.evidence_event_ids):
            raise ValueError("soul proposal evidence must be unique")
        if not 0.0 < self.magnitude <= 1.0:
            raise ValueError("soul proposal magnitude must be in (0, 1]")
        if self.proposed_at_version < 0:
            raise ValueError("proposal version must be non-negative")
        if self.cooldown_until_version < self.proposed_at_version:
            raise ValueError("cooldown cannot end before proposal creation")
        if self.status is ProposalStatus.PENDING and self.decision_reason:
            raise ValueError("pending proposal cannot have a decision reason")
        if self.status is not ProposalStatus.PENDING and not self.decision_reason:
            raise ValueError("decided proposal requires a decision reason")


@dataclass(frozen=True)
class Scheme(Generic[StateT]):
    scheme_id: str
    character_id: str
    target_state: StateT
    progress: float = 0.0
    status: SchemeStatus = SchemeStatus.PLANNED

    def __post_init__(self) -> None:
        if not self.scheme_id.strip() or not self.character_id.strip():
            raise ValueError("scheme requires ids")
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("scheme progress must be between 0 and 1")
        if self.status is SchemeStatus.COMPLETED and self.progress != 1.0:
            raise ValueError("completed scheme must have full progress")
        if self.progress == 1.0 and self.status is not SchemeStatus.COMPLETED:
            raise ValueError("full progress requires completed status")
