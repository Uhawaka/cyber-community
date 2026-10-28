"""Create, compile, and compare community world packages."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from engine.world import build_community_package, compile_package


def _diagnostics(result) -> int:
    print(json.dumps({
        "ok": False,
        "error": "PACKAGE_VALIDATION_FAILED",
        "diagnostics": [asdict(issue) for issue in result.diagnostics],
        "capabilities": asdict(result.handshake),
    }, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
    return 1


def _summary(result) -> dict:
    compiled = result.compiled
    return {
        "ok": True,
        "package_id": compiled.manifest.package_id,
        "revision": compiled.manifest.revision,
        "hash": compiled.content_hash,
        "capabilities": asdict(result.handshake),
        "locations": [item.id for item in compiled.world.locations],
        "characters": [item.id for item in compiled.world.characters],
        "resources": {item.id: item.quantity for item in compiled.world.resources},
        "passages": [item.id for item in compiled.world.passages],
    }


def _community_required(result) -> bool:
    if result.compiled.community is not None:
        return True
    print(json.dumps({
        "ok": False, "error": "COMMUNITY_REQUIRED",
        "message": "only versioned community packages are supported",
    }, ensure_ascii=False), file=sys.stderr)
    return False


def command_compile_inspect(path: Path) -> int:
    result = compile_package(path)
    if not result.ok or result.compiled is None:
        return _diagnostics(result)
    if not _community_required(result):
        return 1
    print(json.dumps(_summary(result), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def command_compare(before_path: Path, after_path: Path, log_path: Path | None = None) -> int:
    before, after = compile_package(before_path), compile_package(after_path)
    for result in (before, after):
        if not result.ok or result.compiled is None:
            return _diagnostics(result)
        if not _community_required(result):
            return 1
    old, new = before.compiled, after.compiled
    changes = {}
    for field in ("characters", "locations", "resources", "passages"):
        left = {item.id: item for item in getattr(old.world, field)}
        right = {item.id: item for item in getattr(new.world, field)}
        changes[field] = {
            "added": sorted(right.keys() - left.keys()),
            "removed": sorted(left.keys() - right.keys()),
            "changed": sorted(key for key in left.keys() & right.keys() if left[key] != right[key]),
        }
    identical = old.content_hash == new.content_hash
    continuation = {"evaluated": False, "exact_continuation": "not_evaluated"}
    if log_path is not None:
        from engine.runtime.kernel.lifecycle import load_run
        from engine.runtime.simulation.community_config import validate_configuration_selection

        run = load_run(old, log_path)
        continuation = {"evaluated": True, "old_history_replay": run.replay() == run.state,
                        "history_hash": run.history_hash(), "exact_continuation": False}
        if not identical:
            continuation["reason"] = "world content differs; retain the old package/log and start a new run"
        elif "community_config" not in run.events[0].data:
            continuation["reason"] = "history has no persisted community configuration; read/replay only"
        else:
            try:
                validate_configuration_selection(run.events[0].data["community_config"])
                continuation.update(exact_continuation=True, reason="world and managed configuration match")
            except (ValueError, TypeError) as exc:
                continuation["reason"] = str(exc)
    print(json.dumps({
        "ok": True, "schema_version": "world-comparison/v1",
        "before": _summary(before), "after": _summary(after),
        "content_identical": identical, "restart_required": not identical,
        "changes": changes, "community_rules_changed": old.community != new.community,
        "relationships_changed": old.world.relationships != new.world.relationships,
        "history": continuation, "automatic_migration_available": False,
        "scope": "read-only package/history comparison; no rewriting, inferred claims or quality acceptance",
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="社区世界包工具")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="从统一作者 JSON 创建社区世界包")
    create.add_argument("source", type=Path)
    create.add_argument("--output", type=Path, required=True)
    inspect = commands.add_parser("compile-inspect", help="编译世界包并输出摘要")
    inspect.add_argument("package", type=Path)
    validate = commands.add_parser("validate", help="验证世界包的编译契约")
    validate.add_argument("package", type=Path)
    compare = commands.add_parser("compare", help="只读比较世界包和运行历史")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--log", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            return command_compile_inspect(build_community_package(args.source, args.output))
        if args.command in {"validate", "compile-inspect"}:
            return command_compile_inspect(args.package)
        return command_compare(args.before, args.after, args.log)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({
            "ok": False, "error": "INVALID_ARGUMENT_OR_RUNTIME_ERROR", "message": str(exc),
        }, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
