"""Public contracts for runtime-independent participation."""

from engine.participation.contracts import (
    AvatarPackage,
    AvatarProfile,
    AvatarSessionPolicy,
    AvatarSession,
    GateDecision,
    GateStatus,
    InterventionAttempt,
    Opportunity,
    OpportunityResolver,
    OfflinePolicy,
    ParticipantKind,
    UserGate,
)
from engine.participation.service import (
    answer_gate,
    expire_gate,
    resolve_intervention,
)

__all__ = [
    "AvatarPackage",
    "AvatarProfile",
    "AvatarSessionPolicy",
    "AvatarSession",
    "GateDecision",
    "GateStatus",
    "InterventionAttempt",
    "Opportunity",
    "OpportunityResolver",
    "OfflinePolicy",
    "ParticipantKind",
    "UserGate",
    "answer_gate",
    "expire_gate",
    "resolve_intervention",
]
