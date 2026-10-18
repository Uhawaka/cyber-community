#!/usr/bin/env python3
"""Emit reproducible runtime scale observations as JSON.

Timing is diagnostic only. Correctness bounds belong to property tests.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
from time import perf_counter


ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.application import SimulationPolicy, create_run, run_ticks
from engine.world.package_compiler import compile_package
from engine.world.package_spec import PackageCharacter


def _scaled_world(character_count: int):
    result = compile_package(ROOT / "worlds" / "echo-quay")
    if result.compiled is None:
        raise RuntimeError("echo-quay did not compile")
    compiled = result.compiled
    template = compiled.world.characters[0]
    characters = tuple(
        PackageCharacter(
            id=f"benchmark-npc-{index:03d}",
            name=f"Benchmark NPC {index}",
            role=template.role,
            location_id=template.location_id,
            profile=template.profile,
            soul=template.soul,
            memory_seed=(),
        )
        for index in range(character_count)
    )
    return replace(
        compiled,
        world=replace(compiled.world, characters=characters),
        content_hash=f"{compiled.content_hash}-benchmark-{character_count}",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticks", type=int, default=3)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--action-budget", type=int, default=12)
    parser.add_argument("--opportunity-budget", type=int, default=32)
    args = parser.parse_args()
    policy = SimulationPolicy(
        action_budget=args.action_budget,
        opportunity_budget=args.opportunity_budget,
        incident_budget=1,
        memory_budget=1,
    )
    results = []
    for character_count in (10, 50, 100):
        run = create_run(_scaled_world(character_count), args.seed)
        started = perf_counter()
        report = run_ticks(run, args.ticks, policy=policy)
        elapsed_ms = (perf_counter() - started) * 1000
        results.append(
            {
                "characters": character_count,
                "ticks": args.ticks,
                "elapsed_ms": round(elapsed_ms, 3),
                "event_count": len(run.events),
                "final_tick": run.state.tick,
                "report": asdict(report),
            }
        )
    print(
        json.dumps(
            {
                "benchmark": "autonomous-runtime-budgets",
                "seed": args.seed,
                "policy": asdict(policy),
                "results": results,
                "timing_assertions": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
