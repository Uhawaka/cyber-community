import json
import shutil
from pathlib import Path

import pytest

from engine.application import validate_package
from engine.application.package_validation import PackageValidationReport
from engine.runtime.simulation import create_run, run_ticks
from engine.world import compile_package


ROOT = Path(__file__).parents[1]
PACKAGES = (
    ROOT / "worlds" / "echo-quay",
    ROOT / "worlds" / "black-pine-ridge",
)


@pytest.mark.parametrize("package", PACKAGES)
def test_package_validation_runs_eight_isolated_replayable_seeds(package):
    before = {path: path.read_bytes() for path in package.rglob("*") if path.is_file()}

    report = validate_package(package)

    assert isinstance(report, PackageValidationReport)
    assert report.ok, report.diagnostics
    assert len(report.seed_results) >= 8
    assert all(result.ok and result.ticks == 20 for result in report.seed_results)
    assert all(dict(result.checks).values() for result in report.seed_results)
    assert report.unique_history_count >= report.minimum_unique_histories >= 2
    after = {path: path.read_bytes() for path in package.rglob("*") if path.is_file()}
    assert after == before


def test_resource_and_passage_perturbations_change_structured_event_chain(tmp_path):
    baseline_result = compile_package(PACKAGES[0])
    assert baseline_result.ok and baseline_result.compiled is not None

    def signature(compiled):
        run = create_run(compiled, seed=11)
        run_ticks(run, 7)
        return tuple(
            (
                event.event_type.value,
                event.actor_id,
                event.target_entity_id,
                tuple(
                    sorted(
                        (key, repr(value))
                        for key, value in event.data.items()
                        if key
                        in {
                            "resource_id",
                            "passage_id",
                            "origin_id",
                            "destination_id",
                            "travel_time",
                        }
                    )
                ),
            )
            for event in run.events
        )

    baseline = signature(baseline_result.compiled)
    for filename, mutate in (
        (
            "resources.yaml",
            lambda value: value["resources"][0].update(quantity=0),
        ),
        (
            "passages.yaml",
            lambda value: [
                item.update(travel_time=item["travel_time"] + 7)
                for item in value["passages"]
            ],
        ),
    ):
        package = tmp_path / filename.replace(".", "-")
        shutil.copytree(PACKAGES[0], package)
        path = package / filename
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        changed = compile_package(package)
        assert changed.ok and changed.compiled is not None
        assert signature(changed.compiled) != baseline


def test_probe_definition_must_have_eight_seeds(tmp_path):
    package = tmp_path / "world"
    shutil.copytree(PACKAGES[1], package)
    path = package / "tests" / "invariants.yaml"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["seeds"] = [1, 2]
    path.write_text(json.dumps(value), encoding="utf-8")

    report = validate_package(package)

    assert not report.ok
    assert any(item.code == "INVALID_PROBE_SEEDS" for item in report.diagnostics)
