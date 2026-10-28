"""Run deterministic community samples and retain failed logs for inspection."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from engine.application.community_validation import evaluate_community
from engine.runtime.character import (
    community_context, community_exchange_choices, community_handoff_policy, community_labor_policy,
    community_operations, community_policy, community_knowledge,
    community_loan_policy, community_lease_policy, community_role_policy, community_membership_policy,
)
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.lifecycle import create_run, export_run, load_run
from engine.runtime.simulation.community import run_community_ticks
from engine.world import compile_package

SEEDS = (3, 7, 11, 17, 29, 41, 61, 83)


def policy_provenance():
    sources = {
        module.__name__: sha256(Path(module.__file__).read_bytes()).hexdigest()
        for module in (community_policy, community_exchange_choices, community_labor_policy,
                       community_context, community_operations, community_handoff_policy, community_knowledge,
                       community_loan_policy, community_lease_policy, community_role_policy, community_membership_policy)
    }
    return {"version": community_policy.CommunityLifePolicy.version,
            "source_sha256": sources,
            "scope": "decision policy and context modules, not a full engine revision"}


def cognition_matches(left, right):
    fields = ("cursor", "activities", "goals", "plans", "intent_plans", "intent_plan_sequences", "goal_evidence", "commitments", "offers", "requests", "loans", "leases",
              "handoffs", "responsibilities", "responsibility_sources",
              "organization_records", "read_organization_records", "memberships", "membership_invitations", "sent_membership_invitations",
              "role_holders", "censures", "censures_by_issuer",
              "records_by_group", "records_by_author", "record_sequences", "reported_claims", "read_records_by_owner",
              "social_origins", "social_latest", "loan_proposal_sources", "last_decisions", "last_wakeups", "outcomes",
              "subjective_trust", "trust_sources", "memories", "claims", "learned_skills")
    indexes = ("records", "by_owner", "by_entity", "by_person", "by_topic")
    pending = ("goals", "plans", "intent_plans", "commitments", "offers", "requests", "handoffs", "loans", "leases")
    return all(
        getattr(left, name).pending_ids == getattr(right, name).pending_ids
        and getattr(left, name).by_owner == getattr(right, name).by_owner for name in pending
    ) and (
        left.claims.by_owner == right.claims.by_owner
    ) and all(
        getattr(left, field) == getattr(right, field) for field in fields
    ) and all(
        getattr(left.index, field) == getattr(right.index, field) for field in indexes
    )


def sample(compiled, seed, ticks, directory, *, chunk_ticks=20):
    path = directory / f"seed-{seed}-ticks-{ticks}.jsonl"
    started = perf_counter()
    run = create_run(compiled, seed, path)
    timings = []
    while run.state.tick < ticks:
        before = perf_counter()
        count = min(chunk_ticks, ticks - run.state.tick)
        run_community_ticks(run, count)
        timings.append({"to_tick": run.state.tick, "seconds": perf_counter() - before,
                        "events": len(run.events)})
    evaluation = evaluate_community(run)
    restore_path = directory / f"seed-{seed}-ticks-{ticks}-restored.jsonl"
    restored = load_run(compiled, export_run(run, restore_path))
    before_projection = community_projection(run)
    after_projection = community_projection(restored)
    evaluation["mechanism_gates"]["restore"] = (
        restored.history_hash() == run.history_hash() and restored.state == run.state
        and cognition_matches(before_projection, after_projection)
    )
    # A restored state alone does not prove the next decision is identical.
    run_community_ticks(run, 1)
    run_community_ticks(restored, 1)
    evaluation["mechanism_gates"]["resume_next_tick"] = (
        restored.history_hash() == run.history_hash()
        and restored.state == run.state
        and cognition_matches(community_projection(restored), community_projection(run))
    )
    evaluation.update(log_path=str(path), restored_log_path=str(restore_path),
                      seconds=perf_counter() - started, chunk_timings=timings,
                      log_includes_resume_probe_tick=True)
    return evaluation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--ticks", type=int, nargs="+", default=[20])
    parser.add_argument("--seeds", type=int, nargs="+", default=[17])
    parser.add_argument("--logs", type=Path, required=True,
                        help="Raw log directory, e.g. outputs/experiments/run-01/logs")
    parser.add_argument("--output", type=Path, required=True,
                        help="Report path, e.g. outputs/experiments/run-01/report.json")
    parser.add_argument("--chunk-ticks", type=int, default=20)
    args = parser.parse_args(argv)
    if args.chunk_ticks < 1 or any(tick < 1 for tick in args.ticks):
        parser.error("ticks and chunk-ticks must be positive")
    if len(set(args.ticks)) != len(args.ticks) or len(set(args.seeds)) != len(args.seeds):
        parser.error("duplicate seeds/ticks would overwrite sample logs")
    compiled = compile_package(args.package)
    if not compiled.ok or compiled.compiled.community is None:
        parser.error(f"requires a valid community package: {compiled.diagnostics}")
    args.logs.mkdir(parents=True, exist_ok=True)
    samples = []
    for ticks in args.ticks:
        for seed in args.seeds:
            try:
                result = sample(compiled.compiled, seed, ticks, args.logs, chunk_ticks=args.chunk_ticks)
            except (OSError, RuntimeError, ValueError) as exc:
                result = {"seed": seed, "ticks": ticks, "error": str(exc),
                          "log_path": str(args.logs / f"seed-{seed}-ticks-{ticks}.jsonl")}
            samples.append(result)
            print(f"seed={seed} ticks={ticks} "
                  f"passed={not result.get('error') and all(result['mechanism_gates'].values())}", flush=True)
    report = {"schema_version": "community-probe/v1", "policy": "CommunityLifePolicy",
              "policy_provenance": policy_provenance(),
              "external_model_requests": 0, "world_hash": compiled.compiled.content_hash,
              "samples": samples,
              "limitations": ["offline mechanism probe, not real model or human quality evidence",
                              "repetition and causal candidates are conservative diagnostics, not quality acceptance",
                              "raw logs contain private cognition and are not public story documents"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return int(any(item.get("error") or not all(item["mechanism_gates"].values()) for item in samples))


if __name__ == "__main__":
    raise SystemExit(main())
