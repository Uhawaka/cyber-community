"""Summarize human-attested blind reviews without rewriting history."""

import argparse
import json
from pathlib import Path
from statistics import median

from engine.application.community_blind_review import evaluate_blind_review
from engine.runtime.kernel.lifecycle import fork_run, load_run
from engine.runtime.simulation.community_events import open_tick
from engine.world import compile_package
from scripts.community_quality import private_json, unique_fields
from scripts.community_review_source import review_samples, validate_report, validate_sample


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("review input exceeds the 16 MiB budget")

    def reject_constant(value):
        raise ValueError(f"non-finite JSON value: {value}")

    return json.loads(path.read_text(), object_pairs_hook=unique_fields, parse_constant=reject_constant)


def summarize_reviews(package, report_path, reviews_dir):
    compiled = compile_package(package)
    if not compiled.ok or compiled.compiled.community is None:
        raise ValueError("review summary requires a valid community package")
    world = compiled.compiled
    report = read_json(report_path)
    kind = validate_report(report, world.content_hash)
    samples = review_samples(report)
    results = []
    for sample in sorted(samples, key=lambda item: item["seed"]):
        run = load_run(world, Path(sample["log_path"]))
        count = sample.get("event_count")
        if type(count) is not int or not 1 <= count <= len(run.events):
            raise ValueError("sample event count must identify a real history prefix")
        run = fork_run(run, event_count=count)
        if (run.state.seed != sample["seed"] or run.state.tick != 100 or open_tick(run)
                or run.history_hash() != sample.get("history_hash")):
            raise ValueError("sample seed, tick or history does not match the report")
        validate_sample(report, sample, run, kind)
        review = read_json(Path(reviews_dir) / f"seed-{sample['seed']}.json")
        result = evaluate_blind_review(run, review)
        results.append({"seed": sample["seed"], **result})
    complete = all(result["quality_gate"] != "not_evaluated" for result in results)
    names = ("character_distinctness", "action_reasonableness", "consequence_continuity", "story_interest")
    distribution = {
        name: {
            "samples": [{"seed": result["seed"],
                         "median": result["medians"][name] if result["medians"] is not None else None}
                        for result in results],
            "median": median(result["medians"][name] for result in results) if complete else None,
            "worst": min(result["medians"][name] for result in results) if complete else None,
        }
        for name in names
    }
    return {
        "schema_version": "community-blind-summary/v1",
        "world_hash": world.content_hash,
        "policy_provenance": report["policy_provenance"],
        "evidence_kind": kind,
        "samples": results,
        "score_distribution": distribution,
        "all_samples_attested": complete,
        "scope": "reported 100 Tick samples; human identity and independent blinding are not independently verified; no overall quality, model behavior or long-run gate",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = summarize_reviews(args.package, args.report, args.reviews)
        private_json(args.output, result)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, RecursionError) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
