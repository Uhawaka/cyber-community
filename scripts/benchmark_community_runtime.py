"""Measure real bounded histories and backlog, without evaluating narrative quality."""

import argparse
from collections import Counter
import json
from pathlib import Path
import platform
from statistics import median
from time import perf_counter

from engine.runtime.character.community_context import decision_context
from engine.runtime.character.community_policy import CommunityLifePolicy
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.lifecycle import fork_run, load_run
from engine.runtime.simulation.community import run_community_ticks
from engine.runtime.simulation.community_events import open_tick
from engine.world import compile_package
from scripts.community_probe import policy_provenance
from scripts.community_quality import private_json, unique_fields


def measure(operation, repeats):
    timings = []
    for _ in range(repeats):
        start = perf_counter()
        result = operation()
        timings.append(perf_counter() - start)
    return result, median(timings)


def backlog(run):
    projection = community_projection(run)
    social = {}
    for field in ("offers", "requests", "commitments", "handoffs", "loans", "leases"):
        records = getattr(projection, field)
        social[field] = {
            "total": len(records), "pending": len(records.pending_ids),
            "statuses": dict(sorted(Counter(r.status for r in records.values()).items())),
        }
    overdue = [
        activity.activity_id for activity in projection.activities.values()
        if activity.due_tick <= run.state.tick
    ]
    return {
        "activities": len(projection.activities), "overdue_activities": len(overdue),
        "active_goals": sum(g.status == "active" for g in projection.goals.values()),
        "plans": len(projection.plans), "social": social,
        "memories_by_owner": dict(sorted(Counter(m.owner_id for m in projection.memories.values()).items())),
        "claims_by_owner": dict(sorted(Counter(c.owner_id for c in projection.claims.values()).items())),
        "organization_records": len(projection.organization_records),
        "censures": len(projection.censures),
        "scope": "terminal and overdue obligations are retained; zero pending is not a quality goal",
    }


def profile_sample(world, sample, repeats):
    count = sample["event_count"]
    if (isinstance(count, bool) or not isinstance(count, int) or count < 1
            or isinstance(sample["ticks"], bool) or not 1 <= sample["ticks"] <= 100):
        raise ValueError("runtime benchmark requires real 1..100 Tick histories")

    def restore():
        full = load_run(world, sample["log_path"])
        if count > len(full.events):
            raise ValueError("sample prefix exceeds its actual log")
        run = fork_run(full, event_count=count)
        if (run.state.tick != sample["ticks"] or run.state.seed != sample["seed"]
                or open_tick(run) or run.history_hash() != sample["history_hash"]):
            raise ValueError("runtime benchmark sample does not match its history")
        if any(e.event_type.value.startswith("model_decision_") for e in run.events):
            raise ValueError("runtime benchmark only accepts offline deterministic histories")
        return run

    run, restore_seconds = measure(restore, repeats)
    replayed, replay_seconds = measure(run.replay, repeats)
    if replayed != run.state:
        raise ValueError("runtime benchmark history does not replay")
    summary = backlog(run)
    actors = tuple(c.id for c in world.world.characters)
    contexts, context_seconds = measure(
        lambda: tuple(decision_context(run, actor) for actor in actors), repeats,
    )
    durations, hashes = [], []
    for _ in range(repeats):
        branch = fork_run(run, event_count=len(run.events))
        community_projection(branch)
        start = perf_counter()
        run_community_ticks(branch, 1, decision_policy=CommunityLifePolicy())
        durations.append(perf_counter() - start)
        hashes.append(branch.history_hash())
    if len(set(hashes)) != 1:
        raise ValueError("runtime benchmark next Tick is not repeatable")
    return {
        "seed": run.state.seed, "ticks": run.state.tick, "events": count,
        "history_hash": run.history_hash(), "log_bytes": Path(sample["log_path"]).stat().st_size,
        "restore_and_prefix_seconds": restore_seconds, "replay_seconds": replay_seconds,
        "warm_all_contexts_seconds": context_seconds, "warm_next_tick_seconds": median(durations),
        "next_tick_repeatable": True, "backlog": summary,
        "retrieved_memories_by_owner": {c.actor_id: len(c.memories) for c in contexts},
    }


def build_benchmark(package, report_path, output, *, repeats=3):
    if isinstance(repeats, bool) or not isinstance(repeats, int) or not 1 <= repeats <= 10:
        raise ValueError("runtime benchmark repeats must be 1..10")
    result = compile_package(package)
    if not result.ok or result.compiled.community is None:
        raise ValueError("runtime benchmark requires a community package")
    with Path(report_path).open("rb") as stream:
        payload = stream.read(16 * 1024 * 1024 + 1)
    if len(payload) > 16 * 1024 * 1024:
        raise ValueError("runtime benchmark report exceeds input budget")
    report = json.loads(payload, object_pairs_hook=unique_fields)
    if (report.get("schema_version") != "community-probe/v1"
            or report.get("world_hash") != result.compiled.content_hash
            or report.get("policy_provenance") != policy_provenance()):
        raise ValueError("runtime benchmark requires exact world and current policy provenance")
    rows = []
    identities = set()
    for sample in report["samples"]:
        identity = sample["seed"], sample["ticks"]
        if identity in identities:
            raise ValueError("runtime benchmark report contains duplicate samples")
        identities.add(identity)
        if sample.get("error") or not sample["mechanism_gates"] or not all(sample["mechanism_gates"].values()):
            raise ValueError("runtime benchmark requires successful mechanism samples")
        rows.append(profile_sample(result.compiled, sample, repeats))
    if not rows:
        raise ValueError("runtime benchmark requires samples")
    private_json(output, {
        "schema_version": "community-runtime-benchmark/v1",
        "world_hash": result.compiled.content_hash, "policy_provenance": policy_provenance(),
        "python": platform.python_version(), "platform": platform.platform(),
        "repeats": repeats, "samples": rows, "external_model_requests": 0,
        "scope": "real <=100 Tick prefix costs and backlog; no 1000 Tick or narrative acceptance",
        "timing_boundaries": "restore includes disk load, full-log validation, prefix fork and hash; "
                             "warm contexts exclude projection construction; next Tick excludes fork and hash; "
                             "in-memory commit only, not durable next-Tick fsync latency",
    })
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        build_benchmark(args.package, args.report, args.output, repeats=args.repeats)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
