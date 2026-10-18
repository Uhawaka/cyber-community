from dataclasses import replace
from pathlib import Path

import pytest

from engine.application import create_run, publish_due_episode, run_ticks
from engine.narrative import PresentationStore
from engine.runtime.autonomous_director import run_incident_scheduler
from engine.runtime.simulation.observability import explain_event
from engine.runtime.workflow import STEP_HANDLERS, StepResult, TickContext, execute_workflow
from engine.world import compile_package
from engine.world.package_spec import WorkflowStep


PACKAGE = Path(__file__).parents[1] / "worlds" / "echo-quay"


def _compiled():
    result = compile_package(PACKAGE)
    assert result.ok and result.compiled is not None
    return result.compiled


def _spy(monkeypatch, kind, steps, trace):
    for name in steps:
        key = (kind, name)
        original = STEP_HANDLERS[key]

        def handler(context, step, original=original):
            trace.append((kind, step.op))
            return original(context, step)

        monkeypatch.setitem(STEP_HANDLERS, key, handler)


def test_four_workflow_kinds_dispatch_through_compiled_steps(monkeypatch):
    compiled = _compiled()
    trace = []
    for definition in (
        compiled.workflow.genesis,
        compiled.workflow.evolution,
        compiled.workflow.intervention,
        compiled.workflow.presentation,
    ):
        _spy(monkeypatch, definition.kind, (step.op for step in definition.steps), trace)

    run = create_run(compiled, seed=41)
    report = run_ticks(run, 1)
    run_incident_scheduler(run, 0)
    publish_due_episode(run, PresentationStore())

    assert report.executed_workflow_steps == tuple(
        step.op for step in compiled.workflow.evolution.steps
    )
    for kind, called_step in (
        ("genesis", "load_world"),
        ("evolution", "environment_update"),
        ("intervention", "incident"),
        ("presentation", "source_filter"),
        ("presentation", "curate"),
        ("presentation", "plan"),
        ("presentation", "render"),
        ("presentation", "validate"),
        ("presentation", "publish"),
    ):
        assert (kind, called_step) in trace


def test_replacing_registered_handler_changes_runtime_behavior(monkeypatch):
    compiled = _compiled()
    monkeypatch.setitem(
        STEP_HANDLERS,
        ("evolution", "environment_update"),
        lambda _context, _step: StepResult(),
    )
    run = create_run(compiled, seed=5)

    report = run_ticks(run, 1)

    assert run.state.tick == 0
    assert report.executed_ticks == 0


def test_missing_and_unknown_runtime_handlers_fail_closed(monkeypatch):
    compiled = _compiled()
    monkeypatch.delitem(STEP_HANDLERS, ("evolution", "phase_check"))
    run = create_run(compiled, seed=7)
    with pytest.raises(ValueError, match="unknown runtime workflow handler"):
        run_ticks(run, 1)

    unknown = replace(
        compiled.workflow.evolution,
        steps=(WorkflowStep("not_registered"),),
    )
    with pytest.raises(ValueError, match="unknown runtime workflow handler"):
        execute_workflow(unknown, TickContext({}))


def test_event_explanation_exposes_workflow_provenance():
    run = create_run(_compiled(), seed=11)
    run_ticks(run, 1)
    event = run.events[1]

    trace = explain_event(run, event.sequence)

    assert event.data["workflow_kind"] == "evolution"
    assert event.data["workflow_step"] == "environment_update"
    assert trace.workflow_kind == "evolution"
    assert trace.workflow_step == "environment_update"
