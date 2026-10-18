import json
import shutil
from pathlib import Path

import pytest

from scripts.world import main


ROOT = Path(__file__).parents[1]
PACKAGES = (
    ROOT / "worlds" / "echo-quay",
    ROOT / "worlds" / "black-pine-ridge",
)


@pytest.mark.parametrize("package", PACKAGES)
def test_compile_inspect_succeeds_with_structured_output(package, capsys):
    assert main(["compile-inspect", str(package)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["hash"]
    assert payload["locations"]
    assert payload["resources"]
    assert payload["capabilities"]["unknown"] == []


@pytest.mark.parametrize("package", PACKAGES)
def test_simulate_succeeds_with_runtime_summary_and_episode(package, capsys):
    assert main(
        [
            "simulate",
            str(package),
            "--ticks",
            "4",
            "--seed",
            "17",
            "--episode",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["tick"] == 4
    assert payload["event_count"] == sum(payload["event_counts"].values())
    assert payload["locations"]
    assert payload["resources"]
    assert payload["history_hash"]
    assert payload["episode"]["body"]
    assert payload["episode"]["source_ids"]


def test_simulate_writes_standalone_story_document(tmp_path, capsys):
    story_dir = tmp_path / "stories"
    summary_path = tmp_path / "summary.json"
    assert main(
        [
            "simulate",
            str(PACKAGES[0]),
            "--ticks",
            "4",
            "--seed",
            "17",
            "--output",
            str(summary_path),
            "--story-output-dir",
            str(story_dir),
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    story_path = Path(payload["story_document"])
    story_paths = [Path(item) for item in payload["story_documents"]]
    assert story_paths
    assert story_paths[0] == story_dir / "episode-0001.md"
    assert story_path == story_paths[-1]
    assert len(story_paths) == len(payload["episodes"])
    assert summary_path.is_file()
    assert story_path.is_file()
    assert story_path.stat().st_mode & 0o777 == 0o600
    assert not (story_dir / ".episode-0001.md.tmp").exists()
    story = story_path.read_text(encoding="utf-8")
    assert story.startswith("---\nschema_version: \"story-document.v1\"")
    assert 'package_id: "echo-quay"' in story
    assert "# " + payload["episode"]["title"] in story
    assert payload["episode"]["body"] in story


def test_long_simulation_writes_multiple_bounded_story_documents(
    tmp_path, capsys
):
    story_dir = tmp_path / "stories"
    assert main(
        [
            "simulate",
            str(PACKAGES[1]),
            "--ticks",
            "20",
            "--seed",
            "17",
                "--gate-choice",
                "bank-the-embers",
            "--story-output-dir",
            str(story_dir),
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert len(payload["episodes"]) >= 2
    assert len(payload["story_documents"]) == len(payload["episodes"])
    assert all(
        len(episode["source_ids"]) <= 36
        for episode in payload["episodes"]
    )
    for document in payload["story_documents"]:
        text = Path(document).read_text(encoding="utf-8")
        assert "action_rejected" not in text
        assert "action_replanned" not in text


def test_longform_resumes_without_republishing_existing_chapters(
    tmp_path, capsys
):
    run_path = tmp_path / "events.jsonl"
    presentation_path = tmp_path / "presentations.json"
    story_dir = tmp_path / "stories"
    summary_path = tmp_path / "summary.json"
    common = [
        "longform",
        str(PACKAGES[1]),
        "--seed",
        "17",
        "--chunk-ticks",
        "4",
        "--gate-choice",
        "bank-the-embers",
        "--output",
        str(summary_path),
        "--run-output",
        str(run_path),
        "--presentation-output",
        str(presentation_path),
        "--story-output-dir",
        str(story_dir),
    ]
    assert main(
        [
            *common,
            "--target-episodes",
            "1",
            "--max-ticks",
            "12",
        ]
    ) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["episode_count"] >= 1
    first_ids = [item["episode_id"] for item in first["episodes"]]

    assert main(
        [
            *common,
            "--target-episodes",
            "2",
            "--max-ticks",
            "24",
            "--resume",
        ]
    ) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["episode_count"] >= 2
    assert [
        item["episode_id"] for item in resumed["episodes"]
    ][: len(first_ids)] == first_ids
    assert resumed["requested_from_tick"] == first["executed_to_tick"]
    assert resumed["position_sync_violations"] == []
    validation = resumed["longrun_validation"]
    assert validation["gates"]["position_sync"]["passed"]
    assert validation["gates"]["replay_consistency"]["passed"]
    assert validation["gates"]["episode_continuity"]["passed"]
    assert len(list(story_dir.glob("episode-*.md"))) == (
        resumed["episode_count"]
    )


def test_package_validate_rejects_unknown_capability(tmp_path, capsys):
    package = tmp_path / "unknown-capability"
    shutil.copytree(PACKAGES[0], package)
    manifest_path = package / "manifest.yaml"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"].append("world.telepathy.v1")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    assert main(["validate", str(package)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"] == "PACKAGE_VALIDATION_FAILED"
    assert error["capabilities"]["unknown"] == ["world.telepathy.v1"]
    assert any(
        item["code"] == "UNKNOWN_CAPABILITY"
        for item in error["diagnostics"]
    )
