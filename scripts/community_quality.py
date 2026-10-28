"""Export private review evidence or score supplied annotations without changing history."""

import argparse
import json
import os
from pathlib import Path

from engine.application.community_quality_review import (
    evaluate_quality_review, quality_review_bundle, quality_review_template,
)
from engine.runtime.kernel.lifecycle import fork_run, load_run
from engine.world import compile_package


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate review field: {key}")
        result[key] = value
    return result


def private_json(path, data):
    payload = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
    except BaseException:
        path.unlink()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("bundle", "template", "evaluate", "blind", "blind-key", "blind-evaluate"))
    parser.add_argument("package", type=Path)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--event-count", type=int, help="Exclude a probe's appended continuation tick")
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path, required=True,
                        help="New private file under outputs/; existing files are never overwritten")
    args = parser.parse_args(argv)
    if (args.operation in {"evaluate", "blind-evaluate"}) != (args.review is not None):
        parser.error("--review is required only for evaluate or blind-evaluate")
    compiled = compile_package(args.package)
    if not compiled.ok or compiled.compiled.community is None:
        parser.error("requires a valid community package")
    try:
        run = load_run(compiled.compiled, args.log)
        if args.event_count is not None:
            if not 1 <= args.event_count <= len(run.events):
                raise ValueError("event-count must select a nonempty existing history prefix")
            run = fork_run(run, event_count=args.event_count)
        if args.operation in {"evaluate", "blind-evaluate"}:
            if args.review.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("review exceeds the 16 MiB input budget")
            def reject_constant(value):
                raise ValueError(f"non-finite JSON value: {value}")
            review = json.loads(args.review.read_text(), object_pairs_hook=unique_fields,
                                parse_constant=reject_constant)
            if args.operation == "evaluate":
                data = evaluate_quality_review(run, review)
            else:
                from engine.application.community_blind_review import evaluate_blind_review
                data = evaluate_blind_review(run, review)
        elif args.operation in {"blind", "blind-key"}:
            from engine.application.community_blind_review import blind_review_materials
            material, key = blind_review_materials(run)
            data = material if args.operation == "blind" else key
        else:
            data = quality_review_bundle(run) if args.operation == "bundle" else quality_review_template(run)
        private_json(args.output, data)
    except (OSError, RuntimeError, ValueError, RecursionError) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
