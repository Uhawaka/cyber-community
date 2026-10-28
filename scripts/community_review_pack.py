"""Freeze selected 100 Tick private evidence without supplying human verdicts."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from engine.application.community_blind_review import blind_review_materials
from engine.application.community_quality_review import quality_review_bundle, quality_review_template
from engine.runtime.kernel.lifecycle import fork_run, load_run
from engine.runtime.simulation.community_events import open_tick
from engine.world import compile_package
from engine.world.package_publish import publish_directory
from scripts.community_quality import private_json, unique_fields
from scripts.community_review_source import review_samples, validate_report, validate_sample


def build_review_pack(package, report_path, destination):
    destination = Path(destination)
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError("review destination must be new and its parent must exist")
    compiled = compile_package(package)
    if not compiled.ok or compiled.compiled.community is None:
        raise ValueError("review pack requires a valid community package")
    report_path = Path(report_path)
    if report_path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("probe report exceeds the 16 MiB input budget")
    report = json.loads(report_path.read_text(), object_pairs_hook=unique_fields)
    kind = validate_report(report, compiled.compiled.content_hash)
    samples = review_samples(report)
    with TemporaryDirectory(prefix="community-review-") as scratch:
        stage = Path(scratch) / "pack"
        stage.mkdir(mode=0o700)
        for name in ("blind", "keys", "evidence", "annotations"):
            (stage / name).mkdir(mode=0o700)
        index = []
        for sample in sorted(samples, key=lambda s: s["seed"]):
            run = load_run(compiled.compiled, sample["log_path"])
            count = sample["event_count"]
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= len(run.events):
                raise ValueError("sample event count must identify a real history prefix")
            run = fork_run(run, event_count=count)
            if (run.state.seed != sample["seed"] or run.state.tick != 100 or open_tick(run)
                    or run.history_hash() != sample["history_hash"]):
                raise ValueError("sample world, seed, tick or history binding does not match its log")
            validate_sample(report, sample, run, kind)
            name = f"seed-{run.state.seed}.json"
            blind, key = blind_review_materials(run)
            private_json(stage / "blind" / name, blind)
            private_json(stage / "keys" / name, key)
            private_json(stage / "evidence" / name, quality_review_bundle(run))
            private_json(stage / "annotations" / name, quality_review_template(run))
            index.append({"seed": run.state.seed, "ticks": 100, "events": count,
                          "history_hash": run.history_hash(), "file": name})
        private_json(stage / "index.json", {
            "schema_version": "community-review-pack/v1", "world_hash": compiled.compiled.content_hash,
            "policy_provenance": report["policy_provenance"], "samples": index,
            "evidence_kind": kind,
            "quality_gates": "not_evaluated", "human_reviews_completed": 0,
            "privacy": "private; isolate keys and evidence from blind reviewers until independent scoring",
            "scope": "reported 100 Tick samples; original probe continuation tick excluded; no supplied ratings",
        })
        publish_directory(stage, destination)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        build_review_pack(args.package, args.report, args.output)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
