"""Stable personality, separate from fallible beliefs and lived memories."""

from __future__ import annotations

from dataclasses import dataclass

from engine.contracts.community import require_text

SOUL_VERSION = "soul/v2"


@dataclass(frozen=True)
class Personhood:
    long_term_desire: str
    inner_conflict: str
    interests: tuple[str, ...]
    vulnerabilities: tuple[str, ...]
    capability_limits: tuple[str, ...]

    def __post_init__(self) -> None:
        require_text(self.long_term_desire, "long_term_desire")
        require_text(self.inner_conflict, "inner_conflict")
        for field in ("interests", "vulnerabilities", "capability_limits"):
            items = getattr(self, field)
            if not isinstance(items, tuple) or not 1 <= len(items) <= 8:
                raise ValueError(f"{field} requires one to eight entries")
            for item in items:
                require_text(item, field, 500)


def personhood_from_soul(soul):
    if soul.get("version") != SOUL_VERSION:
        raise ValueError("unsupported soul version")
    return Personhood(
        soul["long_term_desire"], soul["inner_conflict"],
        tuple(soul["interests"]), tuple(soul["vulnerabilities"]),
        tuple(soul["capability_limits"]),
    )
