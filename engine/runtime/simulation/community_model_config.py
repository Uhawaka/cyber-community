"""Explicit model-managed configuration, separate from experimental fake policies."""

from dataclasses import asdict, dataclass
import re


@dataclass(frozen=True)
class ModelCommunityRunConfig:
    schema_version: str
    policy_version: str
    engine_sha256: str
    model_sha256: str
    timeout_seconds: float
    max_requests: int
    action_budget: int
    memory_budget: int

    def __post_init__(self):
        from engine.runtime.simulation.community_config import CommunityRunConfig
        CommunityRunConfig("community-run-config/v1", "life", self.policy_version,
                           self.engine_sha256, self.action_budget, self.memory_budget)
        if self.schema_version != "community-model-config/v1":
            raise ValueError("unsupported model-managed configuration")
        if not isinstance(self.model_sha256, str) or not re.fullmatch("[a-f0-9]{64}", self.model_sha256):
            raise ValueError("model-managed configuration requires an identity fingerprint")
        import math
        if (isinstance(self.max_requests, bool) or not isinstance(self.max_requests, int)
                or not 0 <= self.max_requests <= 100000
                or isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 600):
            raise ValueError("invalid model-managed request budget")


def model_identity(policy):
    identity = policy.managed_identity()
    if not isinstance(identity, str) or not re.fullmatch("[a-f0-9]{64}", identity):
        raise ValueError("model policy must provide a complete identity fingerprint")
    return identity


def make_model_config(compiled, policy, *, action_budget=None, memory_budget=1):
    from engine.runtime.simulation.community_config import engine_fingerprint
    if compiled.community is None:
        raise ValueError("model-managed configuration requires a community world")
    return asdict(ModelCommunityRunConfig(
        "community-model-config/v1", policy.version, engine_fingerprint(), model_identity(policy),
        policy.timeout_seconds, policy.max_requests,
        len(compiled.world.characters) if action_budget is None else action_budget, memory_budget,
    ))


def validate_model_selection(raw, policy, action_budget=None, memory_budget=None):
    from engine.runtime.simulation.community_config import engine_fingerprint
    config = ModelCommunityRunConfig(**raw)
    if (getattr(policy, "records_model_attempts", False) is not True
            or not callable(getattr(policy, "managed_identity", None))):
        raise ValueError("model-managed continuation requires the explicit configured model policy")
    if config.engine_sha256 != engine_fingerprint() or config.policy_version != policy.version:
        raise ValueError("persisted engine or model policy differs; refusing continuation")
    if config.model_sha256 != model_identity(policy):
        raise ValueError("persisted model identity differs; refusing continuation")
    if config.max_requests != policy.max_requests or config.timeout_seconds != policy.timeout_seconds:
        raise ValueError("persisted model request budget differs")
    for requested, stored in ((action_budget, config.action_budget), (memory_budget, config.memory_budget)):
        if requested is not None and (
            isinstance(requested, bool) or not isinstance(requested, int) or requested != stored
        ):
            raise ValueError("persisted model-managed action or memory budget differs")
    return policy, config.action_budget, config.memory_budget
