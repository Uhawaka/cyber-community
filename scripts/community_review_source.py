"""Validate offline or model-managed report provenance for review artifacts."""

from engine.adapters.community_policy import ModelCommunityPolicy
from engine.runtime.simulation.community_config import engine_fingerprint
from engine.runtime.simulation.community_model_config import ModelCommunityRunConfig
from scripts.community_model_probe import model_sample_run
from scripts.community_probe import policy_provenance


def review_samples(report):
    samples = report.get("samples")
    if not isinstance(samples, list) or any(
        not isinstance(sample, dict) or type(sample.get("ticks")) is not int
        for sample in samples
    ):
        raise ValueError("review input requires a valid sample list")
    selected = [sample for sample in samples if sample["ticks"] == 100]
    if (not 1 <= len(selected) <= 64
            or any(type(sample.get("seed")) is not int for sample in selected)
            or len({sample["seed"] for sample in selected}) != len(selected)):
        raise ValueError("review requires one to 64 distinct 100 Tick samples")
    return selected


def validate_report(report, world_hash):
    if not isinstance(report, dict) or report.get("world_hash") != world_hash:
        raise ValueError("review input must match the exact world")
    schema, provenance = report.get("schema_version"), report.get("policy_provenance")
    if schema == "community-probe/v1":
        if provenance != policy_provenance():
            raise ValueError("review input policy provenance differs from current source")
        return "offline"
    if schema != "community-model-probe/v1" or report.get("policy") != "ModelCommunityPolicy":
        raise ValueError("unsupported review input provenance")
    if not isinstance(provenance, dict):
        raise ValueError("model review requires a managed configuration")
    try:
        config = ModelCommunityRunConfig(**provenance)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid model-managed review provenance") from exc
    if config.engine_sha256 != engine_fingerprint() or config.policy_version != ModelCommunityPolicy.version:
        raise ValueError("model review provenance differs from current engine")
    samples = report.get("samples")
    if (not isinstance(samples, list) or any(not isinstance(sample, dict)
            or type(sample.get("model_requests")) is not int or sample["model_requests"] < 0
            for sample in samples)
            or type(report.get("model_decision_requests_recorded")) is not int
            or report["model_decision_requests_recorded"] != sum(sample["model_requests"] for sample in samples)):
        raise ValueError("model report request counts are inconsistent")
    return "model"


def validate_sample(report, sample, run, kind):
    gates = sample.get("mechanism_gates")
    required = {"replay", "nonnegative_inventory", "action_sources", "past_event_references", "restore"}
    required.add("resume_next_tick" if kind == "offline" else "recorded_model_calls")
    if (sample.get("error") or not isinstance(gates, dict) or not required <= set(gates)
            or any(value is not True for value in gates.values())):
        raise ValueError("failed mechanism sample cannot be used for review")
    if kind == "model":
        config, actual = model_sample_run(run)
        if config != report["policy_provenance"]:
            raise ValueError("sample managed model identity or budget differs from report")
        for key in ("mechanism_gates", "model_requests", "model_errors", "action_rejections",
                    "model_error_reasons", "action_rejection_reasons", "unbacked_decisions"):
            if actual[key] != sample.get(key):
                raise ValueError(f"model sample {key} differs from its history")
