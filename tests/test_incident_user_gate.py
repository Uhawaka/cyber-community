import json
import shutil
from pathlib import Path

from engine.application import (
    apply_intervention,
    create_run,
    fork_run,
    get_pending_user_gate,
    run_ticks,
    run_until_user_gate,
)
from engine.runtime.kernel import EventType
from engine.world.package_compiler import compile_package


PACKAGE = Path(__file__).parents[1] / "worlds" / "echo-quay"


def _compiled(path=PACKAGE):
    result = compile_package(path)
    assert result.ok and result.compiled is not None
    return result.compiled


def test_incident_is_replayable_system_change_without_prescribed_response():
    run = create_run(_compiled(), seed=41)
    run_ticks(run, 2)

    event = next(
        item for item in run.events
        if item.event_type is EventType.INCIDENT_OCCURRED
    )
    assert event.actor_id is None
    assert event.data["rule_id"] == "returning-tide"
    assert "utterance" not in event.data
    assert "character_id" not in json.dumps(dict(event.data))
    assert run.replay() == run.state


def test_incident_scheduler_can_rest_when_budget_excludes_due_event():
    run = create_run(_compiled(), seed=41)
    run_ticks(run, 2, incident_budget=0)

    rested = next(
        item for item in run.events
        if item.event_type is EventType.INCIDENT_RESTED
    )
    assert rested.actor_id is None
    assert rested.data["candidate_rule_ids"] == ("returning-tide",)
    assert run.replay() == run.state


def test_gate_pauses_actions_and_choice_applies_effect_and_cost():
    run = create_run(_compiled(), seed=17)
    gate = run_until_user_gate(run, 20)
    assert gate is not None
    assert gate.gate_id == "quay-signal-choice"
    assert run.events[-1].event_type is EventType.GATE_OPENED

    paused_tick = run.state.tick
    paused_event_count = len(run.events)
    run_ticks(run, 2)
    assert run.state.tick == paused_tick + 2
    assert get_pending_user_gate(run) is not None
    assert all(
        event.event_type is EventType.GATE_WAITED
        for event in run.events[paused_event_count:]
    )

    oil_before = run.state.resources["signal-oil"]
    knowledge_before = {
        actor_id: character.needs["knowledge"]
        for actor_id, character in run.state.characters.items()
    }
    event = apply_intervention(run, gate.gate_id, "light-outer-quay")
    assert event.event_type is EventType.USER_INTERVENTION
    assert run.state.resources["signal-oil"] == oil_before - 1
    assert all(
        run.state.characters[actor_id].needs["knowledge"]
        == max(0, value - 8)
        for actor_id, value in knowledge_before.items()
    )
    assert get_pending_user_gate(run) is None
    assert run.replay() == run.state


def test_gate_defaults_to_abstain_and_fork_choices_diverge():
    source = create_run(_compiled(), seed=17)
    gate = run_until_user_gate(source, 20)
    assert gate is not None
    branch = fork_run(source)

    source_event = apply_intervention(source, gate.gate_id)
    branch_event = apply_intervention(
        branch, gate.gate_id, "light-outer-quay"
    )
    assert source_event.data["choice_id"] == "abstain"
    assert source_event.data["defaulted"] is True
    assert branch_event.data["choice_id"] == "light-outer-quay"
    assert source.history_hash() != branch.history_hash()
    assert source.state.resources["signal-oil"] == (
        branch.state.resources["signal-oil"] + 1
    )
    assert source.replay() == source.state
    assert branch.replay() == branch.state


def test_gate_deadline_defaults_to_abstain_without_character_actions():
    run = create_run(_compiled(), seed=17)
    gate = run_until_user_gate(run, 20)
    assert gate is not None
    start = len(run.events)

    run_ticks(run, gate.deadline_tick - gate.opened_tick)

    waited = run.events[start:]
    assert [event.event_type for event in waited[:-1]] == [
        EventType.GATE_WAITED,
        EventType.GATE_WAITED,
        EventType.GATE_WAITED,
    ]
    assert waited[-1].event_type is EventType.USER_INTERVENTION
    assert waited[-1].data["choice_id"] == "abstain"
    assert waited[-1].data["expired"] is True
    assert get_pending_user_gate(run) is None


def test_compiler_rejects_rule_dialogue_and_named_character_response(tmp_path):
    package = tmp_path / "probe"
    shutil.copytree(PACKAGE, package)
    path = package / "world.yaml"
    world = json.loads(path.read_text(encoding="utf-8"))
    world["rules"][1]["reaction"] = {
        "character_id": "lin",
        "dialogue": "我会照做。",
    }
    path.write_text(json.dumps(world, ensure_ascii=False), encoding="utf-8")

    result = compile_package(package)
    assert not result.ok
    assert any(
        item.code in {"PREARRANGED_FIELD", "PRESCRIBED_CHARACTER_RESPONSE"}
        and ("dialogue" in item.path or "reaction" in item.path)
        for item in result.diagnostics
    )
