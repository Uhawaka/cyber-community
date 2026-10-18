"""Public command: run a world package and print the resulting text."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from engine.application import publish_due_episodes
from engine.bootstrap import build_application
from engine.narrative.artifacts import render_story_markdown
from engine.world import compile_package


EXIT_SUCCESS = 0
EXIT_FAILURE = 1
_DEFAULT_SEED = 17
_DEFAULT_TICKS = 8


def main(argv: list[str] | None = None) -> int:
    parser, topics = _parser()
    args = parser.parse_args(argv)
    if args.command == "help":
        (topics[args.topic] if args.topic else parser).print_help()
        return EXIT_SUCCESS
    try:
        return run_package(args.package)
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAILURE


def _parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    parser = argparse.ArgumentParser(
        prog="cyber-community",
        description="运行一个目录世界包，并打印这一次写成的文字。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  cyber-community run worlds/echo-quay\n"
            "  cyber-community run worlds/black-pine-ridge\n"
            "  cyber-community help"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="运行世界并打印章节")
    run.add_argument(
        "package",
        type=Path,
        help="世界包目录，例如 worlds/echo-quay",
    )
    help_command = subparsers.add_parser("help", help="显示使用说明")
    help_command.add_argument(
        "topic",
        nargs="?",
        choices=("run",),
        help="要查看的命令",
    )
    return parser, {"run": run}


def run_package(package: Path) -> int:
    result = compile_package(package)
    if not result.ok or result.compiled is None:
        for issue in getattr(result, "diagnostics", ()):
            print(f"{issue.path}: {issue.message}", file=sys.stderr)
        if not getattr(result, "diagnostics", ()):
            print("世界包无法运行。", file=sys.stderr)
        return EXIT_FAILURE

    compiled = result.compiled
    application = build_application(compiled)
    run = application.create_run(_DEFAULT_SEED)
    application.run_ticks(run, _DEFAULT_TICKS)
    presentations = publish_due_episodes(
        run,
        application.presentation_storage,
        renderer=application.renderer,
        render_timeout=application.render_timeout,
    )
    if not presentations:
        print("这次运行还没有形成可读章节。", file=sys.stderr)
        return EXIT_FAILURE

    print(compiled.world.title)
    print()
    for index, presentation in enumerate(presentations):
        if index:
            print()
        print(
            _reader_text(
                render_story_markdown(
                    presentation,
                    package_id=compiled.manifest.package_id,
                    world_title=compiled.world.title,
                    seed=_DEFAULT_SEED,
                )
            )
        )
    return EXIT_SUCCESS


def _reader_text(document: str) -> str:
    marker = "\n---\n\n"
    start = document.find(marker)
    if start == -1:
        return document.strip()
    return document[start + len(marker):].strip()
