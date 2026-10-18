import json
import shutil
from pathlib import Path

from engine.application import (
    create_run,
    publish_due_episode,
    rerender_episode,
    run_ticks,
)
from engine.narrative import (
    DeliveryPolicy,
    NarrativeStyleProfile,
    PresentationStore,
)
from engine.world.package_compiler import compile_package


ROOT = Path(__file__).parents[1]
BLACK_PINE = ROOT / "worlds" / "black-pine-ridge"
ECHO_QUAY = ROOT / "worlds" / "echo-quay"


def _copy(source: Path, tmp_path: Path) -> Path:
    target = tmp_path / source.name
    shutil.copytree(source, target)
    return target


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_explicit_profiles_resolve_distinct_editorial_contracts():
    dark = compile_package(BLACK_PINE)
    mystery = compile_package(ECHO_QUAY)

    assert dark.ok and dark.compiled is not None
    assert mystery.ok and mystery.compiled is not None
    assert not dark.compiled.experience.legacy
    assert not mystery.compiled.experience.legacy
    assert dark.compiled.experience.runtime == mystery.compiled.experience.runtime
    assert dark.compiled.experience.editorial != (
        mystery.compiled.experience.editorial
    )
    assert dark.compiled.experience.editorial.pipeline[0] == (
        "mythic-intrigue-editor-v1"
    )


def test_missing_profile_synthesizes_legacy_contract(tmp_path):
    package = _copy(ECHO_QUAY, tmp_path)
    world_path = package / "world.yaml"
    world = _json(world_path)
    del world["experience_profile"]
    _write(world_path, world)

    result = compile_package(package)

    assert result.ok and result.compiled is not None
    assert result.compiled.experience.legacy
    assert result.compiled.experience.editorial.voice_id == (
        "clear-observer-v1"
    )


def test_experience_profile_changes_compiled_hash(tmp_path):
    package = _copy(ECHO_QUAY, tmp_path)
    first = compile_package(package)
    world_path = package / "world.yaml"
    world = _json(world_path)
    world["experience_profile"]["editorial"]["style_overrides"][
        "rhythm"
    ] = "brisk"
    _write(world_path, world)
    second = compile_package(package)

    assert first.ok and first.compiled is not None
    assert second.ok and second.compiled is not None
    assert first.compiled.content_hash != second.compiled.content_hash


def test_unknown_catalog_ids_and_character_reference_fail_closed(tmp_path):
    package = _copy(ECHO_QUAY, tmp_path)
    world_path = package / "world.yaml"
    world = _json(world_path)
    profile = world["experience_profile"]
    profile["runtime"]["mode_id"] = "author-runtime-v9"
    profile["editorial"]["bundle_id"] = "author-bundle-v9"
    profile["editorial"]["character_voice_registers"] = {
        "missing-character": {
            "first_attentions": ["不存在的证据"],
            "diction": "简短",
            "syntax": "短句",
            "withheld": [],
        }
    }
    _write(world_path, world)

    result = compile_package(package)
    codes = {item.code for item in result.diagnostics}

    assert not result.ok
    assert {
        "UNKNOWN_RUNTIME_MODE",
        "UNKNOWN_EDITORIAL_BUNDLE",
        "UNSAFE_EXPERIENCE_REFERENCE",
    }.issubset(codes)


def test_explicit_profile_rejects_conflicting_presentation_style(tmp_path):
    package = _copy(ECHO_QUAY, tmp_path)
    compiled = compile_package(package)
    assert compiled.ok and compiled.compiled is not None
    path = package / "workflows" / "presentation.yaml"
    workflow = _json(path)
    style = dict(compiled.compiled.experience.editorial.style)
    style["rhythm"] = "brisk"
    workflow["policy"]["style"] = style
    _write(path, workflow)

    result = compile_package(package)

    assert not result.ok
    assert any(
        item.code == "EXPERIENCE_POLICY_CONFLICT"
        and item.path.endswith(".policy.style")
        for item in result.diagnostics
    )


def test_scene_pressure_requires_complete_world_material(tmp_path):
    package = _copy(ECHO_QUAY, tmp_path)
    locations_path = package / "locations.yaml"
    locations = _json(locations_path)
    del locations["locations"][0]["scene_seeds"]
    _write(locations_path, locations)

    result = compile_package(package)

    assert not result.ok
    assert any(
        item.code == "INCOMPLETE_RUNTIME_CONTRACT_INPUT"
        and "scene_seeds" in item.path
        for item in result.diagnostics
    )


def test_third_world_selects_registered_experience_by_configuration(
    tmp_path,
):
    package = _copy(ECHO_QUAY, tmp_path)
    manifest_path = package / "manifest.yaml"
    manifest = _json(manifest_path)
    manifest["package_id"] = "third-world-probe"
    _write(manifest_path, manifest)
    world_path = package / "world.yaml"
    world = _json(world_path)
    world["world_id"] = "third-world-probe"
    world["title"] = "第三世界探针"
    world["experience_profile"]["genre_id"] = "neutral"
    world["experience_profile"]["editorial"] = {
        "bundle_id": "neutral-observer-v1",
        "style_overrides": {
            "point_of_view": "observer",
            "imagery_domains": ["石阶"],
            "forbidden_phrases": ["任务完成"],
        },
    }
    _write(world_path, world)

    result = compile_package(package)

    assert result.ok and result.compiled is not None
    editorial = result.compiled.experience.editorial
    assert editorial.genre_id == "neutral"
    assert editorial.bundle_id == "neutral-observer-v1"
    assert editorial.voice_id == "clear-observer-v1"


def test_both_worlds_publish_and_rerender_from_compiled_editorial_contract():
    for package in (BLACK_PINE, ECHO_QUAY):
        result = compile_package(package)
        assert result.ok and result.compiled is not None
        run = create_run(result.compiled, seed=17)
        run_ticks(run, 4)
        assert run.replay() == run.state
        store = PresentationStore()
        published = publish_due_episode(
            run,
            store,
            DeliveryPolicy(unpresented_event_threshold=1),
        )
        assert published is not None
        editorial = result.compiled.experience.editorial
        style = dict(editorial.style)
        style["editorial_pipeline"] = editorial.pipeline
        style["character_voice_registers"] = (
            editorial.character_voice_registers
        )
        style["narrative_functions"] = editorial.narrative_functions
        style["quality_dimensions"] = editorial.quality_dimensions
        rerendered = rerender_episode(
            store,
            published.presentation_id,
            style_profile=NarrativeStyleProfile.from_mapping(style),
        )
        assert rerendered.source_event_ids == published.source_event_ids
        assert rerendered.render_version == 2
        assert rerendered.rendered.body


def test_engine_contains_no_example_world_or_character_names():
    forbidden = (
        "black-pine",
        "echo-quay",
        "wukong",
        "bailing",
    )
    offenders = {
        path.relative_to(ROOT): token
        for path in (ROOT / "engine").rglob("*")
        if path.is_file()
        for token in forbidden
        if token in path.read_text(encoding="utf-8", errors="ignore")
    }
    assert not offenders
