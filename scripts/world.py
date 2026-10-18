#!/usr/bin/env python3
"""Directory world-package CLI."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from engine.application import (
    apply_intervention,
    get_pending_user_gate,
    publish_due_episodes,
    validate_package,
)
from engine.bootstrap import build_application
from engine.narrative import story_document_name, write_story_markdown
from engine.world import compile_package
from scripts.longform import run_longform


EXIT_SUCCESS = 0
EXIT_VALIDATION = 1
EXIT_USAGE_OR_RUNTIME = 2


def _print_diagnostics(result: object) -> None:
    payload = {
        "ok": False,
        "error": "PACKAGE_VALIDATION_FAILED",
        "diagnostics": [
            asdict(issue) for issue in getattr(result, "diagnostics")
        ],
        "capabilities": asdict(getattr(result, "handshake")),
    }
    print(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        file=sys.stderr,
    )


def _compiled_summary(result: object) -> dict[str, object]:
    compiled = getattr(result, "compiled")
    return {
        "ok": True,
        "package_id": compiled.manifest.package_id,
        "revision": compiled.manifest.revision,
        "hash": compiled.content_hash,
        "capabilities": asdict(getattr(result, "handshake")),
        "locations": [location.id for location in compiled.world.locations],
        "characters": [
            character.id for character in compiled.world.characters
        ],
        "resources": {
            resource.id: resource.quantity
            for resource in compiled.world.resources
        },
        "passages": [passage.id for passage in compiled.world.passages],
    }


def command_validate(path: Path) -> int:
    result = validate_package(path)
    if not result.ok or result.compiled is None:
        _print_diagnostics(result)
        return EXIT_VALIDATION
    print(
        json.dumps(
            {
                "ok": True,
                "package_id": result.compiled.manifest.package_id,
                "revision": result.compiled.manifest.revision,
                "hash": result.compiled.content_hash,
                "capabilities": asdict(result.handshake),
                "probe": {
                    "seed_count": len(result.seed_results),
                    "unique_history_count": result.unique_history_count,
                    "minimum_unique_histories": result.minimum_unique_histories,
                    "seeds": [asdict(item) for item in result.seed_results],
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return EXIT_SUCCESS


def command_compile_inspect(path: Path) -> int:
    result = compile_package(path)
    if not result.ok or result.compiled is None:
        _print_diagnostics(result)
        return EXIT_VALIDATION
    print(
        json.dumps(
            _compiled_summary(result),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return EXIT_SUCCESS


def command_simulate(
    path: Path,
    ticks: int,
    seed: int,
    include_episode: bool,
    model_config_path: Path | None = None,
    output: Path | None = None,
    run_output: Path | None = None,
    presentation_output: Path | None = None,
    story_output_dir: Path | None = None,
    gate_choice: str | None = None,
) -> int:
    if ticks < 0:
        raise ValueError("--ticks 必须大于或等于 0")
    result = compile_package(path)
    if not result.ok or result.compiled is None:
        _print_diagnostics(result)
        return EXIT_VALIDATION

    model_config = _read_model_config(model_config_path)
    application = build_application(
        result.compiled,
        model_config=model_config,
        run_path=run_output,
        presentation_path=presentation_output,
    )
    run = application.create_run(seed)
    application.run_ticks(run, ticks)
    pending_gate = get_pending_user_gate(run)
    if gate_choice is not None:
        if pending_gate is None:
            raise ValueError("--gate-choice 已提供，但模拟没有停在用户选择点")
        apply_intervention(run, pending_gate.gate_id, gate_choice)
        remaining_ticks = max(0, ticks - run.state.tick)
        application.run_ticks(run, remaining_ticks)
    event_counts = Counter(event.event_type.value for event in run.events)
    payload: dict[str, object] = {
        "ok": True,
        "package_id": result.compiled.manifest.package_id,
        "hash": result.compiled.content_hash,
        "seed": seed,
        "tick": run.state.tick,
        "event_count": len(run.events),
        "event_counts": dict(sorted(event_counts.items())),
        "locations": {
            character_id: state.location_id
            for character_id, state in sorted(run.state.characters.items())
        },
        "resources": dict(sorted(run.state.resources.items())),
        "history_hash": run.history_hash(),
        "diagnostics": list(application.diagnostics),
        "model_call_budget": application.model_budget,
    }
    pending_gate = get_pending_user_gate(run)
    payload["pending_user_gate"] = (
        None
        if pending_gate is None
        else {
            "gate_id": pending_gate.gate_id,
            "prompt": pending_gate.prompt,
            "choice_ids": list(pending_gate.choice_ids),
            "opened_tick": pending_gate.opened_tick,
            "deadline_tick": pending_gate.deadline_tick,
        }
    )
    if include_episode or story_output_dir is not None:
        presentations = publish_due_episodes(
            run,
            application.presentation_storage,
            renderer=application.renderer,
            render_timeout=application.render_timeout,
        )
        payload["episodes"] = [
            {
                "episode_id": presentation.episode_id,
                "title": presentation.rendered.title,
                "body": presentation.rendered.body,
                "source_ids": list(presentation.source_event_ids),
                "render_diagnostics": [
                    asdict(item) for item in presentation.render_diagnostics
                ],
            }
            for presentation in presentations
        ]
        payload["episode"] = (
            payload["episodes"][-1] if presentations else None
        )
        story_documents: list[str] = []
        if story_output_dir is not None:
            story_output_dir.mkdir(parents=True, exist_ok=True)
            for presentation in presentations:
                story_path = (
                    story_output_dir / story_document_name(presentation)
                )
                write_story_markdown(
                    story_path,
                    presentation,
                    package_id=result.compiled.manifest.package_id,
                    world_title=result.compiled.world.title,
                    seed=seed,
                )
                story_documents.append(str(story_path))
            payload["story_documents"] = story_documents
            payload["story_document"] = (
                story_documents[-1] if story_documents else None
            )
    rendered_payload = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered_payload + "\n", encoding="utf-8")
    print(rendered_payload)
    return EXIT_SUCCESS


def _read_model_config(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 --model-config: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("--model-config 必须包含 JSON 对象")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="赛博社区目录世界包工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="校验目录世界包")
    validate.add_argument("package", type=Path)

    inspect = subparsers.add_parser(
        "compile-inspect",
        help="编译目录世界包并输出规范化摘要",
    )
    inspect.add_argument("package", type=Path)

    simulate = subparsers.add_parser(
        "simulate",
        help="确定性运行目录世界包",
    )
    simulate.add_argument("package", type=Path)
    simulate.add_argument("--ticks", type=int, required=True)
    simulate.add_argument("--seed", type=int, required=True)
    simulate.add_argument("--episode", action="store_true")
    simulate.add_argument(
        "--model-config",
        type=Path,
        help="显式启用模型 Actor/Renderer 的 JSON 配置；默认完全确定性",
    )
    simulate.add_argument("--output", type=Path, help="保存结构化模拟摘要")
    simulate.add_argument("--run-output", type=Path, help="保存 JSONL 事件日志")
    simulate.add_argument(
        "--presentation-output",
        type=Path,
        help="保存独立剧情产物与呈现游标",
    )
    simulate.add_argument(
        "--story-output-dir",
        type=Path,
        help="将已发布 Episode 保存为可直接阅读的独立 Markdown 剧情文档",
    )
    simulate.add_argument(
        "--gate-choice",
        help="模拟停在 UserGate 时应用该 choice id，并继续运行剩余 tick",
    )
    longform = subparsers.add_parser(
        "longform",
        help="按章节目标分段运行、发布并可从持久化日志续跑",
    )
    longform.add_argument("package", type=Path)
    longform.add_argument("--target-episodes", type=int, required=True)
    longform.add_argument("--max-ticks", type=int, required=True)
    longform.add_argument("--chunk-ticks", type=int, default=5)
    longform.add_argument("--seed", type=int, required=True)
    longform.add_argument("--model-config", type=Path)
    longform.add_argument("--output", type=Path, required=True)
    longform.add_argument("--run-output", type=Path, required=True)
    longform.add_argument(
        "--presentation-output", type=Path, required=True
    )
    longform.add_argument(
        "--story-output-dir", type=Path, required=True
    )
    longform.add_argument("--gate-choice")
    longform.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            return command_validate(args.package)
        if args.command == "compile-inspect":
            return command_compile_inspect(args.package)
        if args.command == "simulate":
            return command_simulate(
                args.package,
                args.ticks,
                args.seed,
                args.episode,
                args.model_config,
                args.output,
                args.run_output,
                args.presentation_output,
                args.story_output_dir,
                args.gate_choice,
            )
        if args.command == "longform":
            payload = run_longform(
                args.package,
                target_episodes=args.target_episodes,
                max_ticks=args.max_ticks,
                chunk_ticks=args.chunk_ticks,
                seed=args.seed,
                model_config=_read_model_config(args.model_config),
                output=args.output,
                run_output=args.run_output,
                presentation_output=args.presentation_output,
                story_output_dir=args.story_output_dir,
                gate_choice=args.gate_choice,
                resume=args.resume,
            )
            print(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return EXIT_SUCCESS
    except (RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "INVALID_ARGUMENT_OR_RUNTIME_ERROR",
                    "message": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return EXIT_USAGE_OR_RUNTIME
    return EXIT_USAGE_OR_RUNTIME


if __name__ == "__main__":
    raise SystemExit(main())
