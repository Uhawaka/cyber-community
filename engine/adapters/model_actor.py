"""Model-backed actor adapter, enabled only by explicit composition."""

from __future__ import annotations

from engine.contracts import TextModel
from engine.runtime.character.policy import (
    ActorPolicy,
    DeterministicActorPolicy,
    ModelActorPolicy as _ModelActorPolicy,
)


class ModelActorPolicy(_ModelActorPolicy):
    """Typed adapter around the constrained actor-policy implementation."""

    def __init__(
        self,
        model: TextModel,
        *,
        timeout_seconds: float = 5.0,
        fallback: ActorPolicy | None = None,
    ) -> None:
        super().__init__(
            model,
            timeout_seconds=timeout_seconds,
            fallback=fallback or DeterministicActorPolicy(),
        )
