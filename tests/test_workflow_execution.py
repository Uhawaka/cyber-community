import json
import shutil
from pathlib import Path

from engine.application import create_run, publish_due_episode, run_ticks
from engine.narrative import PresentationStore
from engine.runtime.kernel.events import EventType
from engine.world import compile_package


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "worlds" / "echo-quay"


def copy_package(tmp_path: Path) -> Path:
    destination = tmp_path / "world"
    shutil.copytree(PACKAGE, destination)
    return destination


def rewrite(path: Path, mutate) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def compiled(path: Path):
    result = compile_package(path)
    assert result.ok and result.compiled is not None
    return result.compiled


def test_evolution_budget_and_need_decay_change_structured_runtime(tmp_path):
    package = copy_package(tmp_path)
    evolution = package / "workflows" / "evolution.yaml"
    rewrite(
        evolution,
        lambda value: (
            value["policy"].update(action_budget=0),
            value["policy"]["need_decay"].update(fatigue=7),
        ),
    )
    run = create_run(compiled(package), seed=17)

    report = run_ticks(run, 1)
    decay = next(
        event for event in run.events if event.event_type is EventType.ENVIRONMENT_DECAYED
    )

    assert report.action_budget == 0
    assert {
        delta.amount
        for delta in decay.delta.needs
        if delta.need == "fatigue"
    } == {7}


def test_presentation_threshold_changes_default_delivery(tmp_path):
    baseline = create_run(compiled(PACKAGE), seed=17)
    run_ticks(baseline, 3)
    assert publish_due_episode(baseline, PresentationStore()) is not None

    package = copy_package(tmp_path)
    rewrite(
        package / "workflows" / "presentation.yaml",
        lambda value: value["policy"].update(unpresented_event_threshold=999),
    )
    delayed = create_run(compiled(package), seed=17)
    run_ticks(delayed, 3)
    assert publish_due_episode(delayed, PresentationStore()) is None


def test_unknown_workflow_op_is_rejected_closed(tmp_path):
    package = copy_package(tmp_path)
    rewrite(
        package / "workflows" / "evolution.yaml",
        lambda value: value["steps"][0].update(op="exec_python"),
    )

    result = compile_package(package)

    assert not result.ok
    assert "UNKNOWN_WORKFLOW_OP" in {item.code for item in result.diagnostics}


def test_manifest_keeps_assets_and_workflows_as_distinct_namespaces():
    manifest = json.loads((PACKAGE / "manifest.yaml").read_text(encoding="utf-8"))

    assert set(manifest["assets"]) == {
        "world", "locations", "characters", "resources", "passages"
    }
    assert set(manifest["workflows"]) == {
        "genesis", "evolution", "intervention", "presentation"
    }
    assert not set(manifest["assets"]).intersection(manifest["workflows"])
