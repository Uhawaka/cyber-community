from dataclasses import replace
from pathlib import Path

import pytest

from engine.application import SimulationPolicy, create_run, run_ticks
from engine.runtime import EventType
from engine.world.package_compiler import compile_package
from engine.world.package_spec import PackageCharacter


ROOT = Path(__file__).parents[1]


def _scaled_world(character_count: int):
    result = compile_package(ROOT / "worlds" / "echo-quay")
    assert result.compiled is not None
    compiled = result.compiled
    template = compiled.world.characters[0]
    characters = tuple(
        PackageCharacter(
            id=f"npc-{index:03d}",
            name=f"NPC {index}",
            role=template.role,
            location_id=template.location_id,
            profile=template.profile,
            soul=template.soul,
            memory_seed=(),
        )
        for index in range(character_count)
    )
    world = replace(compiled.world, characters=characters)
    return replace(
        compiled,
        world=world,
        content_hash=f"{compiled.content_hash}-scale-{character_count}",
    )


def test_zero_budgets_defer_as_wait_and_report_each_exhaustion():
    run = create_run(_scaled_world(10), seed=5)
    policy = SimulationPolicy(
        action_budget=0,
        opportunity_budget=0,
        incident_budget=0,
        memory_budget=0,
    )
    report = run_ticks(run, 1, policy=policy)

    assert report.actions_used == 0
    assert report.opportunities_evaluated == 0
    assert report.action_budget_exhausted
    assert report.opportunity_budget_exhausted
    assert report.memory_budget_exhausted
    assert report.budget_exhausted
    assert sum(
        event.event_type is EventType.WAITED for event in run.events
    ) == 10


@pytest.mark.parametrize("character_count", (10, 50, 100))
def test_scale_never_exceeds_opportunity_or_action_budget(character_count):
    run = create_run(_scaled_world(character_count), seed=13)
    policy = SimulationPolicy(
        action_budget=3,
        opportunity_budget=7,
        incident_budget=1,
        memory_budget=1,
    )
    report = run_ticks(run, 1, policy=policy)

    assert report.opportunities_evaluated <= 7
    assert report.actions_used <= 3
    assert report.character_action_count == character_count
    assert report.opportunity_budget_exhausted
