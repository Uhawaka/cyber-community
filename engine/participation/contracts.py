"""Runtime-independent contracts for autonomous participation.

The contracts deliberately describe attempts rather than state mutations.  A
host runtime can adapt its own perception and consequence types to the generic
``OpportunityResolver`` port.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Mapping, Protocol, TypeVar


ContextT = TypeVar("ContextT")
AttemptT = TypeVar("AttemptT")
ResultT = TypeVar("ResultT")


class ParticipantKind(str, Enum):
    AVATAR = "avatar"
    NPC = "npc"


class GateDecision(str, Enum):
    ACCEPT = "accept"
    DECLINE = "decline"
    ABSTAIN = "abstain"


class GateStatus(str, Enum):
    PENDING = "pending"
    ANSWERED = "answered"
    EXPIRED = "expired"


class OfflinePolicy(str, Enum):
    """Avatar absence policy.  M5 intentionally supports pause only."""

    PAUSE = "pause"


class AvatarSessionPolicy(str, Enum):
    PRESERVE = "preserve"


MAX_AVATAR_ID_LENGTH = 64
MAX_AVATAR_TEXT_LENGTH = 2_000
MAX_AVATAR_NEEDS = 16
MAX_AVATAR_SKILLS = 32
MAX_AVATAR_MEMORY_SEEDS = 64
MAX_AVATAR_COLLECTION_ITEMS = 64
_FORBIDDEN_AVATAR_FIELDS = frozenset(
    {
        "tool",
        "tools",
        "file",
        "files",
        "filesystem",
        "network",
        "permissions",
        "permission",
        "delta",
        "deltas",
        "state_delta",
        "state_deltas",
    }
)


@dataclass(frozen=True)
class AvatarPackage:
    """Typed, data-only package accepted at the Avatar trust boundary."""

    avatar_id: str
    display_name: str
    profile: Mapping[str, Any] = field(default_factory=dict)
    soul: Mapping[str, Any] = field(default_factory=dict)
    memory_seed: tuple[Mapping[str, Any], ...] = ()
    offline_policy: OfflinePolicy = OfflinePolicy.PAUSE
    session_policy: AvatarSessionPolicy = AvatarSessionPolicy.PRESERVE

    def __post_init__(self) -> None:
        if (
            not _valid_id(self.avatar_id)
            or not _valid_text(self.display_name, maximum=128)
        ):
            raise ValueError("avatar package requires a valid id and display name")
        if not isinstance(self.profile, Mapping) or not isinstance(self.soul, Mapping):
            raise ValueError("avatar profile and soul must be objects")
        _reject_forbidden_avatar_fields(self.profile)
        _reject_forbidden_avatar_fields(self.soul)
        _validate_avatar_profile(self.profile)
        _validate_avatar_soul(self.soul)
        if (
            not isinstance(self.memory_seed, tuple)
            or len(self.memory_seed) > MAX_AVATAR_MEMORY_SEEDS
        ):
            raise ValueError("avatar memory seed exceeds its limit")
        for item in self.memory_seed:
            if not isinstance(item, Mapping):
                raise ValueError("avatar memory seeds must be objects")
            _reject_forbidden_avatar_fields(item)
            unknown = set(item) - {
                "kind", "summary", "confidence", "visibility", "source"
            }
            if unknown:
                raise ValueError(f"unknown avatar memory fields: {sorted(unknown)}")
            if not _valid_text(item.get("summary"), maximum=MAX_AVATAR_TEXT_LENGTH):
                raise ValueError("avatar memory summary is invalid")
            if item.get("visibility", "private") != "private":
                raise ValueError("avatar memory seed must be private")
            for field_name in ("kind", "source"):
                value = item.get(field_name)
                if value is not None and not _valid_text(value, maximum=128):
                    raise ValueError(f"avatar memory {field_name} is invalid")
            confidence = item.get("confidence", 0.5)
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0 <= confidence <= 1
            ):
                raise ValueError("avatar memory confidence must be between 0 and 1")
        if self.offline_policy is not OfflinePolicy.PAUSE:
            raise ValueError("pause is the only supported avatar offline policy")
        if self.session_policy is not AvatarSessionPolicy.PRESERVE:
            raise ValueError("preserve is the only supported avatar session policy")

    @property
    def goals(self) -> tuple[str, ...]:
        value = self.profile.get("goals", ())
        return tuple(value) if isinstance(value, (tuple, list)) else ()

    @property
    def needs(self) -> Mapping[str, int]:
        value = self.profile.get("needs", {})
        return value if isinstance(value, Mapping) else {}

    @property
    def skills(self) -> tuple[str, ...]:
        value = self.profile.get("skills", ())
        return tuple(value) if isinstance(value, (tuple, list)) else ()


@dataclass(frozen=True)
class AvatarProfile:
    avatar_id: str
    display_name: str
    preferences: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.avatar_id.strip() or not self.display_name.strip():
            raise ValueError("avatar profile requires an id and display name")


@dataclass(frozen=True)
class AvatarSession:
    session_id: str
    profile: AvatarProfile
    started_at: float
    last_active_at: float

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("avatar session requires an id")
        if self.last_active_at < self.started_at:
            raise ValueError("last activity cannot precede session start")


@dataclass(frozen=True)
class Opportunity(Generic[ContextT]):
    """A decision point presented identically to an Avatar or NPC."""

    opportunity_id: str
    participant_id: str
    participant_kind: ParticipantKind
    context: ContextT

    def __post_init__(self) -> None:
        if not self.opportunity_id.strip() or not self.participant_id.strip():
            raise ValueError("opportunity requires ids")


@dataclass(frozen=True)
class InterventionAttempt:
    """User or autonomous intent; authoritative deltas are forbidden."""

    attempt_id: str
    opportunity_id: str
    participant_id: str
    action: str
    arguments: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.attempt_id,
                self.opportunity_id,
                self.participant_id,
                self.action,
            )
        ):
            raise ValueError("attempt requires ids and an action")
        _reject_delta_fields(self.arguments)


@dataclass(frozen=True)
class UserGate:
    gate_id: str
    opportunity_id: str
    trigger: str
    deadline: float
    default: GateDecision = GateDecision.ABSTAIN
    status: GateStatus = GateStatus.PENDING
    decision: GateDecision | None = None

    def __post_init__(self) -> None:
        if not self.gate_id.strip() or not self.opportunity_id.strip():
            raise ValueError("gate requires ids")
        if not self.trigger.strip():
            raise ValueError("gate requires a trigger")
        if self.default is not GateDecision.ABSTAIN:
            raise ValueError("a user gate must default to abstain")
        if self.status is GateStatus.PENDING and self.decision is not None:
            raise ValueError("a pending gate cannot already have a decision")
        if self.status is not GateStatus.PENDING and self.decision is None:
            raise ValueError("a closed gate requires a decision")


class OpportunityResolver(Protocol[ContextT, AttemptT, ResultT]):
    """Shared resolution boundary for both Avatar and NPC opportunities."""

    def resolve(
        self,
        opportunity: Opportunity[ContextT],
        attempt: AttemptT,
    ) -> ResultT:
        """Resolve an attempt without granting the participant write access."""


def _reject_delta_fields(value: object) -> None:
    forbidden = {"delta", "deltas", "state_delta", "state_deltas"}
    if isinstance(value, Mapping):
        keys = {str(key).lower() for key in value}
        overlap = keys & forbidden
        if overlap:
            raise ValueError(
                f"attempt cannot provide state deltas: {sorted(overlap)}"
            )
        for nested in value.values():
            _reject_delta_fields(nested)
    elif isinstance(value, (tuple, list)):
        for nested in value:
            _reject_delta_fields(nested)


def _valid_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_AVATAR_ID_LENGTH
        and value.strip() == value
        and all(character.isalnum() or character in "-_" for character in value)
    )


def _valid_text(value: object, *, maximum: int = MAX_AVATAR_TEXT_LENGTH) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= maximum
        and not any(character in value for character in "\0")
    )


def _reject_forbidden_avatar_fields(value: object) -> None:
    if isinstance(value, Mapping):
        overlap = {str(key).lower() for key in value} & _FORBIDDEN_AVATAR_FIELDS
        if overlap:
            raise ValueError(
                f"avatar package cannot request capabilities or deltas: {sorted(overlap)}"
            )
        for child in value.values():
            _reject_forbidden_avatar_fields(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            _reject_forbidden_avatar_fields(child)


def _validate_text_tree(value: object) -> None:
    if isinstance(value, str) and len(value) > MAX_AVATAR_TEXT_LENGTH:
        raise ValueError("avatar text exceeds its limit")
    if isinstance(value, Mapping):
        if len(value) > MAX_AVATAR_COLLECTION_ITEMS:
            raise ValueError("avatar object exceeds its item limit")
        for child in value.values():
            _validate_text_tree(child)
    elif isinstance(value, (tuple, list)):
        if len(value) > MAX_AVATAR_COLLECTION_ITEMS:
            raise ValueError("avatar collection exceeds its item limit")
        for child in value:
            _validate_text_tree(child)


def _validate_avatar_profile(profile: Mapping[str, Any]) -> None:
    unknown = set(profile) - {"identity", "goals", "needs", "skills", "preferences"}
    if unknown:
        raise ValueError(f"unknown avatar profile fields: {sorted(unknown)}")
    for field_name in ("goals", "skills"):
        values = profile.get(field_name, ())
        limit = MAX_AVATAR_SKILLS if field_name == "skills" else 16
        if (
            not isinstance(values, (tuple, list))
            or len(values) > limit
            or any(not _valid_text(item) for item in values)
        ):
            raise ValueError(f"avatar {field_name} are invalid")
    preferences = profile.get("preferences", ())
    if (
        not isinstance(preferences, (tuple, list))
        or len(preferences) > MAX_AVATAR_COLLECTION_ITEMS
        or any(not _valid_text(item) for item in preferences)
    ):
        raise ValueError("avatar preferences are invalid")
    needs = profile.get("needs", {})
    if (
        not isinstance(needs, Mapping)
        or len(needs) > MAX_AVATAR_NEEDS
        or any(
            not _valid_id(key)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 100
            for key, value in needs.items()
        )
    ):
        raise ValueError("avatar needs are invalid")
    _validate_text_tree(profile)


def _validate_avatar_soul(soul: Mapping[str, Any]) -> None:
    unknown = set(soul) - {"values", "temperament", "preferences", "beliefs"}
    if unknown:
        raise ValueError(f"unknown avatar soul fields: {sorted(unknown)}")
    temperament = soul.get("temperament")
    if temperament is not None and not _valid_text(temperament):
        raise ValueError("avatar temperament is invalid")
    for field_name in ("values", "preferences", "beliefs"):
        values = soul.get(field_name, ())
        if (
            not isinstance(values, (tuple, list))
            or len(values) > MAX_AVATAR_COLLECTION_ITEMS
            or any(not _valid_text(item) for item in values)
        ):
            raise ValueError(f"avatar soul {field_name} is invalid")
    _validate_text_tree(soul)
