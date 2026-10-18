import json
import shutil
from pathlib import Path

import pytest

from engine.application import (
    apply_fate_intervention,
    create_run,
    explain_event,
    fork_run,
    run_ticks,
)
from engine.runtime.kernel import EventType
from engine.world.package_compiler import compile_package


ROOT = Path(__file__).parents[1]
ECHO = ROOT / "worlds" / "echo-quay"
PINE = ROOT / "worlds" / "black-pine-ridge"


def _compiled(path: Path):
    result = compile_package(path)
    assert result.ok and result.compiled is not None
    return result.compiled


def test_fate_intervention_is_independent_replayable_and_forkable():
    run = create_run(_compiled(ECHO), seed=51)
    run_ticks(run, 1)
    branch = fork_run(run)
    before = {
        actor_id: character.needs["knowledge"]
        for actor_id, character in branch.state.characters.items()
    }

    event = apply_fate_intervention(branch, "turn-glass-buoy")

    assert event.event_type is EventType.FATE_INTERVENTION
    assert event.event_type is not EventType.USER_INTERVENTION
    assert event.actor_id is None
    assert "utterance" not in event.data
    assert "outcome" not in event.data
    assert branch.state.resources["signal-oil"] == run.state.resources["signal-oil"] - 1
    assert all(
        branch.state.characters[actor_id].needs["knowledge"] == max(0, value - 5)
        for actor_id, value in before.items()
    )
    assert branch.replay() == branch.state
    assert run.history_hash() != branch.history_hash()
    trace = explain_event(branch, event.sequence)
    assert trace.event_type is EventType.FATE_INTERVENTION
    assert trace.target_entity_id == "turn-glass-buoy"


def test_fate_conditions_once_cooldown_and_cost_fail_atomically(tmp_path):
    run = create_run(_compiled(ECHO), seed=52)
    with pytest.raises(ValueError, match="conditions"):
        apply_fate_intervention(run, "turn-glass-buoy")
    run_ticks(run, 1)
    apply_fate_intervention(run, "turn-glass-buoy")
    with pytest.raises(ValueError, match="already"):
        apply_fate_intervention(run, "turn-glass-buoy")

    pine = create_run(_compiled(PINE), seed=53)
    apply_fate_intervention(pine, "bank-temple-embers")
    with pytest.raises(ValueError, match="cooling"):
        apply_fate_intervention(pine, "bank-temple-embers")

    package = tmp_path / "echo"
    shutil.copytree(ECHO, package)
    world_path = package / "world.yaml"
    world = json.loads(world_path.read_text(encoding="utf-8"))
    fate = next(
        rule for rule in world["rules"]
        if rule.get("type") == "fate_intervention"
    )
    fate["costs"][0]["amount"] = 999
    world_path.write_text(json.dumps(world, ensure_ascii=False), encoding="utf-8")
    insufficient = create_run(_compiled(package), seed=54)
    run_ticks(insufficient, 1)
    state_before = insufficient.state
    events_before = insufficient.events
    with pytest.raises(ValueError, match="cost or effect"):
        apply_fate_intervention(insufficient, "turn-glass-buoy")
    assert insufficient.state == state_before
    assert insufficient.events == events_before


def test_both_worlds_compile_non_prearranged_fate_rules():
    for package in (ECHO, PINE):
        compiled = _compiled(package)
        rules = [
            rule for rule in compiled.world.rules
            if rule.get("type") == "fate_intervention"
        ]
        assert len(rules) == 1
        serialized = json.dumps(rules[0], ensure_ascii=False)
        assert "dialogue" not in serialized
        assert "outcome" not in serialized
