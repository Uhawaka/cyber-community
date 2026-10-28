"""Read-only diagnostics for already completed model-managed community histories."""

import argparse
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from engine.adapters.community_policy import ModelCommunityPolicy
from engine.application.community_validation import evaluate_community
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.lifecycle import export_run, load_run
from engine.runtime.simulation.community_config import engine_fingerprint
from engine.runtime.simulation.community_events import open_tick
from engine.runtime.simulation.community_model_config import ModelCommunityRunConfig
from engine.world import compile_package
from scripts.community_probe import cognition_matches
from scripts.community_quality import private_json


def model_config(run):
    raw = run.events[0].data.get("community_config")
    if not isinstance(raw, dict) or raw.get("schema_version") != "community-model-config/v1":
        raise ValueError("model probe requires a model-managed history")
    config = ModelCommunityRunConfig(**raw)
    if config.engine_sha256 != engine_fingerprint() or config.policy_version != ModelCommunityPolicy.version:
        raise ValueError("model history source fingerprint differs from current engine")
    return dict(raw)


def model_sample_run(run):
    config = model_config(run)
    events = tuple(run.events)
    requests = [event for event in events if event.event_type.value == "model_decision_requested"]
    responses = [event for event in events if event.event_type.value == "model_decision_resolved"]
    request_sequences = {event.sequence for event in requests}
    response_sequences = [event.data["model_response"]["request_sequence"] for event in responses]
    requested_actors = {(event.tick, event.actor_id) for event in requests}
    decisions = [event for event in events if event.actor_id and (
        event.delta.actions or event.event_type.value in {"activity_started", "action_rejected"}
    )]
    unbacked = [event.sequence for event in decisions if (event.tick, event.actor_id) not in requested_actors]
    report = evaluate_community(run)
    with TemporaryDirectory(prefix="community-model-probe-") as temporary:
        restored = load_run(run.compiled, export_run(run, Path(temporary) / "restore.jsonl"))
        report["mechanism_gates"]["restore"] = (
            restored.history_hash() == run.history_hash() and restored.state == run.state
            and cognition_matches(community_projection(restored), community_projection(run))
        )
    report["mechanism_gates"]["recorded_model_calls"] = (
        bool(requests) and len(requests) == len(responses) and len(set(response_sequences)) == len(responses)
        and set(response_sequences) == request_sequences and not unbacked
    )
    report.update({
        "model_requests": len(requests),
        "model_errors": sum(event.data["model_response"]["error"] is not None for event in responses),
        "action_rejections": sum(event.event_type.value == "action_rejected" for event in events),
        "model_error_reasons": dict(sorted(Counter(
            event.data["model_response"]["error"] for event in responses
            if event.data["model_response"]["error"] is not None
        ).items())),
        "action_rejection_reasons": dict(sorted(Counter(
            event.data["reason"] for event in events if event.event_type.value == "action_rejected"
        ).items())),
        "unbacked_decisions": unbacked,
    })
    return config, report


def model_sample(world, path, ticks):
    run = load_run(world, path)
    if run.state.tick != ticks or open_tick(run):
        raise ValueError("model sample requires the requested complete Tick boundary")
    config, report = model_sample_run(run)
    report["log_path"] = str(Path(path).resolve())
    return config, report


def model_report(package, logs, ticks):
    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 1 or not logs:
        raise ValueError("model probe needs completed positive ticks and at least one history")
    compiled = compile_package(package)
    if not compiled.ok or compiled.compiled.community is None:
        raise ValueError("model probe requires a valid community package")
    world = compiled.compiled
    samples, provenance = [], None
    for path in logs:
        config, sample = model_sample(world, path, ticks)
        if provenance is not None and config != provenance:
            raise ValueError("model samples must share the exact managed configuration")
        provenance = config
        samples.append(sample)
    if len({sample["seed"] for sample in samples}) != len(samples):
        raise ValueError("duplicate model sample seed")
    return {
        "schema_version": "community-model-probe/v1",
        "policy": "ModelCommunityPolicy",
        "policy_provenance": provenance,
        "world_hash": world.content_hash,
        "model_decision_requests_recorded": sum(sample["model_requests"] for sample in samples),
        "samples": samples,
        "limitations": [
            "read-only history replay; no additional model calls",
            "recorded requests do not prove external transport or provider identity",
            "restore compares persisted state and cognition, not nondeterministic next model responses",
            "model errors and action rejections are reported, not human quality judgments",
            "raw histories contain private cognition",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--logs", type=Path, nargs="+", required=True)
    parser.add_argument("--ticks", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = model_report(args.package, args.logs, args.ticks)
        private_json(args.output, report)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"{exc}\n")
    return int(any(not all(sample["mechanism_gates"].values()) for sample in report["samples"]))


if __name__ == "__main__":
    raise SystemExit(main())
