"""Bilateral offers are proposals, never implied consent or transfers."""

from __future__ import annotations

from dataclasses import dataclass

from engine.contracts.cognition import KnowledgeClaim
from engine.contracts.community import require_int, require_sources, require_text


@dataclass(frozen=True)
class MaterialLease:
    lease_id: str
    lessor_id: str
    lessee_id: str
    item_id: str
    quantity: int
    duration_ticks: int
    source_refs: tuple[str, ...]
    answer_deadline_tick: int
    due_tick: int | None = None
    status: str = "proposed"

    def __post_init__(self):
        for key in ("lease_id", "lessor_id", "lessee_id", "item_id"):
            require_text(getattr(self, key), key, 200)
        require_sources(self.source_refs)
        require_int(self.answer_deadline_tick, "lease answer deadline")
        for key in ("quantity", "duration_ticks"):
            require_int(getattr(self, key), key, 1)
            if getattr(self, key) > 100:
                raise ValueError("lease exceeds quantity or duration budget")
        if self.lessor_id == self.lessee_id:
            raise ValueError("lease requires independent parties")
        if self.status not in {"proposed", "accepted", "rejected", "expired", "overdue", "returned"}:
            raise ValueError("invalid lease status")
        if self.status in {"accepted", "overdue", "returned"}:
            require_int(self.due_tick, "lease due tick")
        elif self.due_tick is not None:
            raise ValueError("unaccepted lease cannot have a return deadline")


@dataclass(frozen=True)
class OrganizationCensure:
    organization_id: str
    issuer_id: str
    subject_id: str
    norm_index: int
    evidence_sequence: int
    statement: str

    def __post_init__(self):
        for key in ("organization_id", "issuer_id", "subject_id"):
            require_text(getattr(self, key), key, 200)
        require_text(self.statement, "censure statement")
        require_int(self.norm_index, "norm index")
        require_int(self.evidence_sequence, "evidence sequence")
        if self.issuer_id == self.subject_id:
            raise ValueError("censure requires distinct issuer and subject")


@dataclass(frozen=True)
class MaterialLoan:
    loan_id: str
    lender_id: str
    borrower_id: str
    item_id: str
    quantity: int
    repayment_quantity: int
    source_refs: tuple[str, ...]
    deadline_tick: int
    status: str = "proposed"

    def __post_init__(self):
        for field in ("loan_id", "lender_id", "borrower_id", "item_id"):
            require_text(getattr(self, field), field, 200)
        for field in ("quantity", "repayment_quantity"):
            require_int(getattr(self, field), field, 1)
            if getattr(self, field) > 100:
                raise ValueError("loan quantity exceeds action capacity")
        require_int(self.deadline_tick, "deadline_tick")
        require_sources(self.source_refs)
        if self.lender_id == self.borrower_id:
            raise ValueError("loan requires distinct parties")
        if self.status not in {"proposed", "accepted", "rejected", "expired", "overdue", "repaid"}:
            raise ValueError("invalid loan status")


@dataclass(frozen=True)
class OrganizationRecord:
    record_id: str
    organization_id: str
    author_id: str
    claim: KnowledgeClaim
    tick: int

    def __post_init__(self):
        for field in ("record_id", "organization_id", "author_id"):
            require_text(getattr(self, field), field, 200)
        require_int(self.tick, "record tick")
        if not isinstance(self.claim, KnowledgeClaim) or self.claim.owner_id != self.author_id:
            raise ValueError("organization record requires its author's owned claim")


def decode_organization_record(raw):
    claim = raw["claim"]
    return OrganizationRecord(**{**raw, "claim": KnowledgeClaim(**{
        **claim, "source_refs": tuple(claim["source_refs"]),
        "contradicts": tuple(claim.get("contradicts", ())),
    })})


@dataclass(frozen=True)
class ResponsibilityHandoff:
    handoff_id: str
    sender_id: str
    recipient_id: str
    target_id: str
    source_refs: tuple[str, ...]
    deadline_tick: int
    status: str = "proposed"

    def __post_init__(self):
        for field in ("handoff_id", "sender_id", "recipient_id", "target_id"):
            require_text(getattr(self, field), field, 200)
        require_sources(self.source_refs)
        require_int(self.deadline_tick, "deadline_tick")
        if self.sender_id == self.recipient_id:
            raise ValueError("handoff requires distinct parties")
        if self.status not in {"proposed", "accepted", "rejected", "expired"}:
            raise ValueError("invalid responsibility handoff state")


@dataclass(frozen=True)
class MaterialRequest:
    request_id: str
    requester_id: str
    helper_id: str
    item_id: str
    quantity: int
    purpose_id: str
    source_refs: tuple[str, ...]
    deadline_tick: int
    status: str = "open"

    def __post_init__(self):
        for field in ("request_id", "requester_id", "helper_id", "item_id", "purpose_id"):
            require_text(getattr(self, field), field, 200)
        require_int(self.quantity, "quantity", 1)
        require_int(self.deadline_tick, "deadline_tick")
        require_sources(self.source_refs)
        if self.requester_id == self.helper_id or self.quantity > 100:
            raise ValueError("request requires distinct parties and bounded quantity")
        if self.status not in {"open", "fulfilled", "declined", "expired"}:
            raise ValueError("invalid material request state")


@dataclass(frozen=True)
class ExchangeOffer:
    offer_id: str
    sender_id: str
    recipient_id: str
    item_id: str
    quantity: int
    source_refs: tuple[str, ...]
    deadline_tick: int
    requested_item_id: str = ""
    requested_quantity: int = 0
    status: str = "proposed"

    def __post_init__(self) -> None:
        for field in ("offer_id", "sender_id", "recipient_id", "item_id"):
            require_text(getattr(self, field), field, 200)
        require_sources(self.source_refs)
        require_int(self.quantity, "quantity", 1)
        require_int(self.requested_quantity, "requested_quantity")
        require_int(self.deadline_tick, "deadline_tick")
        if self.sender_id == self.recipient_id or max(self.quantity, self.requested_quantity) > 100:
            raise ValueError("exchange requires distinct parties and bounded quantities")
        if bool(self.requested_item_id) != bool(self.requested_quantity):
            raise ValueError("requested item and positive quantity must be specified together")
        if self.item_id == self.requested_item_id:
            raise ValueError("exchange cannot request the same item")
        if self.status not in {"proposed", "accepted", "rejected", "expired"}:
            raise ValueError("invalid exchange lifecycle")
