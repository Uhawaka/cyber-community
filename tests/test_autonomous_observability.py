from pathlib import Path

from engine.application import (
    create_run,
    explain_event,
    run_catchup,
    run_ticks,
)
from engine.runtime import EventType
from engine.world.package_compiler import compile_package


ROOT = Path(__file__).parents[1]


def _compiled():
    result = compile_package(ROOT / "worlds" / "echo-quay")
    assert result.compiled is not None
    return result.compiled


def test_tick_reports_cover_work_budget_and_catchup_truncation():
    run = create_run(_compiled(), 17)
    report = run_ticks(run, 3, action_budget=0)
    assert (report.from_tick, report.to_tick) == (0, 3)
    assert report.requested_ticks == report.executed_ticks == 3
    assert report.character_action_count == 6
    assert report.detailed_event_count == len(run.events) - 1
    assert report.coarse_event_count == 0
    assert report.budget_exhausted is True

    catchup = run_catchup(run, 100, max_ticks=4)
    assert catchup.executed_ticks == 7
    assert catchup.truncated_ticks == catchup.coarse_ticks == 93
    assert catchup.coarse_event_count == 2
    assert run.events[-1].event_type is EventType.COARSE_TICK_SUMMARY


def test_same_seed_reports_and_history_match():
    first = create_run(_compiled(), 29)
    second = create_run(_compiled(), 29)
    assert run_ticks(first, 8) == run_ticks(second, 8)
    assert first.events == second.events
    assert first.history_hash() == second.history_hash()


def test_dialogue_trace_names_prior_movement_and_colocation_basis():
    run = create_run(_compiled(), 17)
    run_ticks(run, 6)
    dialogue = next(
        event for event in run.events if event.event_type is EventType.DIALOGUE
    )

    trace = explain_event(run, dialogue.opportunity_id)
    assert trace.sequence == dialogue.sequence
    assert trace.opportunity_id == dialogue.opportunity_id
    assert trace.pre_state_hash == dialogue.pre_state_hash
    assert trace.rule_basis == dialogue.rule_basis
    assert trace.target_entity_id == dialogue.target_entity_id
    assert trace.seed == 17
    assert trace.deterministic_cursor == dialogue.deterministic_cursor
    assert trace.prior_movement_sequences
    assert len(trace.colocation_basis) == 2
    assert all(dialogue.data["location_id"] in item for item in trace.colocation_basis)
