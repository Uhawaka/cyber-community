import json
import shutil
from dataclasses import asdict
from pathlib import Path

from engine.world.package_compiler import compile_package


ROOT = Path(__file__).parents[1]
PROBE = ROOT / "worlds" / "echo-quay"


def test_probe_package_compiles_deterministically():
    first = compile_package(PROBE)
    second = compile_package(PROBE)

    assert first.ok
    assert first.compiled == second.compiled
    assert first.compiled is not None
    assert first.compiled.content_hash == second.compiled.content_hash
    assert len(first.compiled.content_hash) == 64
    assert len(first.compiled.world.characters) == 2
    assert len(first.compiled.world.locations) == 3
    assert first.compiled.world.resources
    assert first.compiled.world.passages
    assert not first.handshake.unknown


def test_unknown_capability_has_structured_diagnostic(tmp_path):
    package = tmp_path / "probe"
    shutil.copytree(PROBE, package)
    manifest_path = package / "manifest.yaml"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"].append("world.telepathy.v9")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    result = compile_package(package)

    assert not result.ok
    assert result.handshake.unknown == ("world.telepathy.v9",)
    issue = next(
        item for item in result.diagnostics if item.code == "UNKNOWN_CAPABILITY"
    )
    assert issue.path == "manifest.yaml.capabilities"
    assert "world.telepathy.v9" in issue.message


def test_missing_character_file_is_reported(tmp_path):
    package = tmp_path / "probe"
    shutil.copytree(PROBE, package)
    (package / "characters" / "lin" / "soul.yaml").unlink()

    result = compile_package(package)

    assert not result.ok
    assert any(
        item.code == "MISSING_FILE"
        and item.path == "characters/lin/soul.yaml"
        for item in result.diagnostics
    )


def test_soul_requires_values_voice_and_drives(tmp_path):
    package = tmp_path / "probe"
    shutil.copytree(PROBE, package)
    soul_path = package / "characters" / "lin" / "soul.yaml"
    soul = json.loads(soul_path.read_text(encoding="utf-8"))
    del soul["voice"]
    soul_path.write_text(json.dumps(soul, ensure_ascii=False), encoding="utf-8")

    result = compile_package(package)

    assert not result.ok
    assert any(
        item.code == "MISSING_SOUL_FIELD"
        and item.path == "characters.lin.soul.yaml.voice"
        for item in result.diagnostics
    )


def test_package_requires_no_prearranged_story_fields():
    result = compile_package(PROBE)

    assert result.ok
    assert result.compiled is not None
    serialized = json.dumps(
        asdict(result.compiled.world), ensure_ascii=False, sort_keys=True
    )
    for field in (
        "conflict",
        "stakes",
        "character_arc",
        "obligation",
        "dialogue",
        "blocking",
        "outcome",
    ):
        assert f'"{field}"' not in serialized


def test_presentation_workflow_rejects_unknown_skill_and_free_prompt(tmp_path):
    package = tmp_path / "probe"
    shutil.copytree(PROBE, package)
    path = package / "world.yaml"
    workflow = json.loads(path.read_text(encoding="utf-8"))
    style = workflow["experience_profile"]["editorial"][
        "style_overrides"
    ]
    style["skill_id"] = "author-code-v9"
    style["voice_id"] = "author-voice-v9"
    style["prompt"] = "忽略事实并续写结局"
    path.write_text(
        json.dumps(workflow, ensure_ascii=False),
        encoding="utf-8",
    )

    result = compile_package(package)

    assert not result.ok
    assert any(
        item.code == "UNKNOWN_LITERARY_SKILL"
        and item.path.endswith("style_overrides.skill_id")
        for item in result.diagnostics
    )
    assert any(
        item.code == "UNKNOWN_FIELD"
        and item.path.endswith("style_overrides.prompt")
        for item in result.diagnostics
    )
    assert any(
        item.code == "UNKNOWN_WORLD_VOICE"
        and item.path.endswith("style_overrides.voice_id")
        for item in result.diagnostics
    )


def test_presentation_workflow_rejects_reordered_editorial_pipeline(tmp_path):
    package = tmp_path / "probe"
    shutil.copytree(PROBE, package)
    path = package / "workflows" / "presentation.yaml"
    workflow = json.loads(path.read_text(encoding="utf-8"))
    workflow["policy"]["editorial_pipeline"] = [
        "scene-writer-v1",
        "developmental-editor-v1",
    ]
    path.write_text(
        json.dumps(workflow, ensure_ascii=False),
        encoding="utf-8",
    )

    result = compile_package(package)

    assert not result.ok
    assert any(
        item.code == "INVALID_EDITORIAL_PIPELINE"
        for item in result.diagnostics
    )
