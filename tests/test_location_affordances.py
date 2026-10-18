from dataclasses import replace
from pathlib import Path

from engine.runtime.simulation import create_run, opportunities_for
from engine.runtime.space import ActionKind
from engine.world import compile_package


ROOT = Path(__file__).parents[1]


def test_authored_location_switches_limit_opportunities():
    result = compile_package(ROOT / "worlds" / "echo-quay")
    assert result.ok and result.compiled is not None
    compiled = result.compiled
    run = create_run(compiled, seed=7)

    lin = opportunities_for(compiled.world, run.state, "lin")
    assert ActionKind.GATHER in {item.affordance.kind for item in lin}

    locations = tuple(
        replace(
            item,
            affordances=tuple(
                (name, False if name == "gather" else enabled)
                for name, enabled in item.affordances
            ),
        )
        if item.id == "tide-workshop"
        else item
        for item in compiled.world.locations
    )
    changed = replace(compiled.world, locations=locations)
    restricted = opportunities_for(changed, run.state, "lin")
    assert ActionKind.GATHER not in {
        item.affordance.kind for item in restricted
    }


def test_location_change_controls_colocated_social_opportunity():
    result = compile_package(ROOT / "worlds" / "echo-quay")
    assert result.ok and result.compiled is not None
    run = create_run(result.compiled, seed=2)
    assert not any(
        item.affordance.kind is ActionKind.TALK
        for item in opportunities_for(result.compiled.world, run.state, "lin")
    )
    moved = replace(
        run.state,
        characters={
            **run.state.characters,
            "wei": replace(
                run.state.characters["wei"],
                location_id=run.state.characters["lin"].location_id,
            ),
        },
    )
    assert any(
        item.affordance.kind is ActionKind.TALK
        for item in opportunities_for(result.compiled.world, moved, "lin")
    )
