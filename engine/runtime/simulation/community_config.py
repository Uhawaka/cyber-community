"""Immutable configuration for managed deterministic community runs."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import json
import re


@dataclass(frozen=True)
class CommunityRunConfig:
    schema_version: str
    policy: str
    policy_version: str
    engine_sha256: str
    action_budget: int
    memory_budget: int

    def __post_init__(self):
        if self.schema_version != "community-run-config/v1" or self.policy not in {"life", "rest-wait"}:
            raise ValueError("unsupported managed community configuration")
        if not isinstance(self.policy_version, str) or not self.policy_version:
            raise ValueError("configuration requires a policy version")
        if not isinstance(self.engine_sha256, str) or not re.fullmatch("[a-f0-9]{64}", self.engine_sha256):
            raise ValueError("configuration requires a complete engine source fingerprint")
        for value in (self.action_budget, self.memory_budget):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10000:
                raise ValueError("managed budgets must be integers between 0 and 10000")


def engine_fingerprint():
    root = Path(__file__).resolve().parents[2]
    digest = sha256()
    for path in sorted(root.rglob("*.py")):
        name = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def configured_policy(name):
    if name == "life":
        from engine.runtime.character.community_policy import CommunityLifePolicy
        return CommunityLifePolicy(), CommunityLifePolicy.version
    if name == "rest-wait":
        from engine.runtime.simulation.community import RestOrWaitPolicy
        return RestOrWaitPolicy(), "rest-or-wait/v1"
    raise ValueError("unsupported managed community policy")


def make_community_config(compiled, *, policy="life", action_budget=None, memory_budget=1):
    if compiled.community is None:
        raise ValueError("managed configuration requires a community package")
    _, version = configured_policy(policy)
    return asdict(CommunityRunConfig(
        "community-run-config/v1", policy, version, engine_fingerprint(),
        len(compiled.world.characters) if action_budget is None else action_budget, memory_budget,
    ))


def resolve_community_config(run, policy, action_budget, memory_budget):
    try:
        raw = run.log.event_at(0).data.get("community_config")
    except IndexError:
        raw = None
    if raw is None:
        return policy, action_budget, 1 if memory_budget is None else memory_budget
    if raw.get("schema_version") == "community-model-config/v1":
        from engine.runtime.simulation.community_model_config import validate_model_selection
        return validate_model_selection(raw, policy, action_budget, memory_budget)
    return validate_configuration_selection(raw, policy, action_budget, memory_budget)


def decode_community_config(raw):
    if not isinstance(raw, dict):
        raise ValueError("community configuration requires an object")
    if raw.get("schema_version") == "community-model-config/v1":
        from engine.runtime.simulation.community_model_config import ModelCommunityRunConfig
        return ModelCommunityRunConfig(**raw)
    return CommunityRunConfig(**raw)


def validate_configuration_selection(raw, policy=None, action_budget=None, memory_budget=None):
    if raw.get("schema_version") == "community-model-config/v1":
        from engine.runtime.simulation.community_model_config import validate_model_selection
        return validate_model_selection(raw, policy, action_budget, memory_budget)
    config = CommunityRunConfig(**raw)
    for value in (action_budget, memory_budget):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10000):
            raise ValueError("requested managed budgets must be integers between 0 and 10000")
    expected, version = configured_policy(config.policy)
    if config.engine_sha256 != engine_fingerprint() or config.policy_version != version:
        raise ValueError("persisted engine or policy differs; refusing to continue this history")
    if policy is not None and type(policy) is not type(expected):
        raise ValueError("requested policy differs from persisted community configuration")
    if policy is not None and vars(policy):
        raise ValueError("managed built-in policies cannot carry mutable instance configuration")
    if action_budget is not None and action_budget != config.action_budget:
        raise ValueError("requested action budget differs from persisted community configuration")
    if memory_budget is not None and memory_budget != config.memory_budget:
        raise ValueError("requested memory budget differs from persisted community configuration")
    return expected, config.action_budget, config.memory_budget


def preflight_community_resume(compiled, path, *, policy=None, action_budget=None, memory_budget=None, seed=None):
    # Check selection before explicit tail recovery is allowed to alter the file.
    try:
        with Path(path).open("rb") as handle:
            line = handle.readline(1_000_001)
    except OSError as exc:
        raise ValueError(f"cannot read persisted community log: {exc}") from exc
    if len(line) > 1_000_000:
        raise ValueError("community creation record exceeds preflight budget")
    try:
        event = json.loads(line)["event"]
        data = event["data"]
        if event["event_type"] != "run_created" or data["world_hash"] != compiled.content_hash:
            raise ValueError("persisted creation record belongs to another world")
        if seed is not None and seed != data["seed"]:
            raise ValueError("requested seed differs from the persisted run")
        if "community_config" not in data:
            raise ValueError("log has no persisted community configuration; read/replay only, not safe to resume")
        validate_configuration_selection(data["community_config"],
                                         configured_policy(policy)[0] if isinstance(policy, str) else policy,
                                         action_budget, memory_budget)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid persisted community creation record") from exc
