#!/usr/bin/env python3
"""Rerender frozen narrative material through registered literary skills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from engine.application import rerender_frozen_presentations
from engine.bootstrap import build_application
from engine.narrative import style_profile_from_contract
from engine.world import compile_package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--presentations", type=Path, required=True)
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    compiled_result = compile_package(args.package)
    if not compiled_result.ok or compiled_result.compiled is None:
        raise ValueError("world package validation failed")
    config = json.loads(args.model_config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("--model-config must contain a JSON object")
    compiled = compiled_result.compiled
    application = build_application(compiled, model_config=config)
    report = rerender_frozen_presentations(
        args.presentations,
        args.output,
        renderer=application.renderer,
        style_profile=style_profile_from_contract(
            compiled.experience.editorial
        ),
        package_id=compiled.manifest.package_id,
        world_title=compiled.world.title,
        seed=args.seed,
        render_timeout=application.render_timeout,
        labels={
            compiled.world.world_id: compiled.world.title,
            **{
                item.id: item.name
                for item in compiled.world.characters
            },
            **{
                item.id: item.name
                for item in compiled.world.locations
            },
            **{
                f"scene:{item.id}": item.name
                for item in compiled.world.locations
            },
            **{
                item.id: item.name
                for item in compiled.world.resources
            },
        },
    )
    report["model_call_budget"] = application.model_budget
    (args.output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
