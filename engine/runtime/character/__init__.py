"""Public autonomous-character contracts and pure services."""

from engine.runtime.character.contracts import (
    ProposalStatus,
    Scheme,
    SchemeStatus,
    SoulEvolutionProposal,
)
from engine.runtime.character.service import (
    abandon_scheme,
    advance_scheme,
    approve_soul_evolution,
    invalidate_scheme,
    propose_soul_evolution,
    reject_soul_evolution,
)

__all__ = [
    "ProposalStatus",
    "Scheme",
    "SchemeStatus",
    "SoulEvolutionProposal",
    "abandon_scheme",
    "advance_scheme",
    "approve_soul_evolution",
    "invalidate_scheme",
    "propose_soul_evolution",
    "reject_soul_evolution",
]
from engine.runtime.character.memory import Memory, MemoryProjection, MemoryTier

__all__ += [
    "Memory",
    "MemoryProjection",
    "MemoryTier",
    "ActorDecisionContext",
    "ActorPolicy",
    "DeterministicActorPolicy",
    "ModelDialogueActorPolicy",
    "ModelActorPolicy",
    "SoulDecisionContext",
]


def __getattr__(name):
    if name in {
        "ActorDecisionContext",
        "ActorPolicy",
        "DeterministicActorPolicy",
        "ModelDialogueActorPolicy",
        "ModelActorPolicy",
        "SoulDecisionContext",
    }:
        from engine.runtime.character import policy

        return getattr(policy, name)
    raise AttributeError(name)
