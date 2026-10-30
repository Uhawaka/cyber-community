"""Run and inspect a persisted community."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from engine.application.community_observation import observe_community
from engine.bootstrap import build_application
from engine.runtime.kernel.lifecycle import create_run, load_run
from engine.world import compile_package


EXIT_SUCCESS = 0
EXIT_FAILURE = 1
_DEFAULT_SEED = 17


def main(argv: list[str] | None = None) -> int:
    parser, topics = _parser()
    args = parser.parse_args(argv)
    if args.command == "help":
        (topics[args.topic] if args.topic else parser).print_help()
        return EXIT_SUCCESS
    try:
        if args.command == "community":
            return run_community_package(args)
        if args.command == "community-observe":
            return observe_community_package(args)
        if args.command == "community-diagnose":
            return diagnose_community_package(args)
        raise ValueError("unknown community command")
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAILURE


def _parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    parser = argparse.ArgumentParser(
        prog="cyber-community",
        description="运行、恢复或观察自主社区。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  cyber-community community worlds/echo-quay --log outputs/experiments/community.jsonl\n"
            "  cyber-community community worlds/echo-quay --log outputs/experiments/community.jsonl --model-config config/model.json\n"
            "  cyber-community community-observe worlds/echo-quay --log outputs/experiments/community.jsonl\n"
            "  cyber-community help"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    community = subparsers.add_parser("community", help="运行或恢复社区，打印只读观察")
    community.add_argument("package", type=Path, help="社区世界包目录")
    community.add_argument("--log", type=Path, required=True, help="持久化事件日志，含私有认知")
    community.add_argument("--ticks", type=_bounded_ticks, default=24, help="本次追加的 Tick 数，0 到 10000")
    community.add_argument("--seed", type=int, default=None, help="新建默认 17；续跑时必须与日志相同")
    community.add_argument("--resume", action="store_true", help="从已有日志恢复，不新建")
    community.add_argument("--recover-tail", action="store_true", help="续跑时显式恢复不完整末行")
    community.add_argument("--json", action="store_true", help="打印公共只读观察 JSON")
    community.add_argument("--policy", choices=("life", "rest-wait"), default=None, help="新建默认 life，续跑继承日志")
    community.add_argument("--action-budget", type=_bounded_ticks, default=None, help="固定每 Tick 行动预算，续跑不可更改")
    community.add_argument("--memory-budget", type=_bounded_ticks, default=None, help="固定每 Tick 记忆预算，续跑不可更改")
    community.add_argument("--model-config", type=Path, help="显式启用 .env 中的模型；文件只写预算和采样，不写供应商、地址或密钥")
    observe = subparsers.add_parser("community-observe", help="只读校验历史并打印公共观察，不续跑")
    observe.add_argument("package", type=Path, help="与历史匹配的社区世界包目录")
    observe.add_argument("--log", type=Path, required=True, help="只读事件日志，含私有认知")
    observe.add_argument("--json", action="store_true", help="打印公共只读观察 JSON")
    diagnose = subparsers.add_parser("community-diagnose", help="只读机制诊断；输出包含私有统计")
    diagnose.add_argument("package", type=Path, help="与历史匹配的社区世界包目录")
    diagnose.add_argument("--log", type=Path, required=True, help="只读事件日志，含私有认知")
    diagnose.add_argument("--include-private", action="store_true", help="确认输出管理者视角的私有统计")
    help_command = subparsers.add_parser("help", help="显示使用说明")
    help_command.add_argument(
        "topic",
        nargs="?",
        choices=("community", "community-observe", "community-diagnose"),
        help="要查看的命令",
    )
    return parser, {"community": community, "community-observe": observe,
                    "community-diagnose": diagnose}


def _bounded_ticks(value):
    count = int(value)
    if not 0 <= count <= 10000:
        raise argparse.ArgumentTypeError("ticks must be between 0 and 10000")
    return count


def _unique_settings(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate model configuration key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("model configuration requires finite JSON values")


def _finite_settings_float(value):
    import math
    number = float(value)
    if not math.isfinite(number):
        _invalid_constant(value)
    return number


def observe_community_package(args):
    result = compile_package(args.package)
    if not result.ok or result.compiled is None:
        raise ValueError("; ".join(f"{d.path}: {d.message}" for d in result.diagnostics))
    if result.compiled.community is None:
        raise ValueError("community observation requires a versioned community package")
    run = load_run(result.compiled, args.log)
    _print_community(run, json_output=args.json)
    return EXIT_SUCCESS


def diagnose_community_package(args):
    if not args.include_private:
        raise ValueError("community diagnostics contain private statistics; use --include-private")
    result = compile_package(args.package)
    if not result.ok or result.compiled is None:
        raise ValueError("; ".join(f"{d.path}: {d.message}" for d in result.diagnostics))
    if result.compiled.community is None:
        raise ValueError("community diagnostics require a versioned community package")
    from engine.application.community_validation import evaluate_community
    run = load_run(result.compiled, args.log)
    report = {"audience": "administrator", **evaluate_community(run)}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return EXIT_SUCCESS


def run_community_package(args):
    result = compile_package(args.package)
    if not result.ok or result.compiled is None:
        raise ValueError("; ".join(f"{d.path}: {d.message}" for d in result.diagnostics))
    compiled = result.compiled
    if compiled.community is None:
        raise ValueError("community requires a new community package; legacy logs are not migrated implicitly")
    if args.recover_tail and not args.resume:
        raise ValueError("--recover-tail requires --resume")
    from engine.runtime.simulation.community import run_managed_community_ticks
    from engine.runtime.simulation.community_config import configured_policy, make_community_config, preflight_community_resume
    model_app = None
    if args.model_config:
        if args.policy:
            raise ValueError("--model-config cannot be combined with a deterministic --policy")
        with args.model_config.open("rb") as handle:
            payload = handle.read(64001)
        if len(payload) > 64000:
            raise ValueError("model configuration exceeds input budget")
        try:
            settings = json.loads(payload, object_pairs_hook=_unique_settings,
                                  parse_constant=_invalid_constant, parse_float=_finite_settings_float)
        except RecursionError as exc:
            raise ValueError("model configuration nesting exceeds budget") from exc
        from engine.adapters.openai_compatible import settings_without_connection
        settings = settings_without_connection(settings)
        settings["community_managed"] = True
        if args.action_budget is not None:
            settings["community_action_budget"] = args.action_budget
        if args.memory_budget is not None:
            settings["community_memory_budget"] = args.memory_budget
        if args.resume:
            with args.log.open("rb") as handle:
                creation = handle.readline(1_000_001)
            if len(creation) > 1_000_000:
                raise ValueError("community creation record exceeds preflight budget")
            try:
                stored = json.loads(creation)["event"]["data"].get("community_config", {})
                if not isinstance(stored, dict):
                    raise ValueError("invalid persisted community configuration")
            except (KeyError, TypeError) as exc:
                raise ValueError("invalid persisted community creation record") from exc
            for key in ("action_budget", "memory_budget"):
                if f"community_{key}" not in settings and key in stored:
                    settings[f"community_{key}"] = stored[key]
        model_app = build_application(compiled, model_config=settings, run_path=args.log)
        model_budgets = {key: model_app.community_config[key] for key in ("action_budget", "memory_budget")}
    else:
        model_budgets = {"action_budget": args.action_budget, "memory_budget": args.memory_budget}
    if args.resume:
        preflight_community_resume(compiled, args.log,
                                   policy=model_app.community_policy if model_app else args.policy,
                                   **model_budgets, seed=args.seed)
        run = load_run(compiled, args.log, recover_tail=args.recover_tail)
        if args.seed is not None and args.seed != run.state.seed:
            raise ValueError("requested seed differs from the persisted run")
        if "community_config" not in run.events[0].data:
            raise ValueError("log has no persisted community configuration; read/replay only, not safe to resume")
    else:
        if model_app:
            run = model_app.create_run(_DEFAULT_SEED if args.seed is None else args.seed)
        else:
            config = make_community_config(
                compiled, policy=args.policy or "life", action_budget=args.action_budget,
                memory_budget=1 if args.memory_budget is None else args.memory_budget,
            )
            run = create_run(compiled, _DEFAULT_SEED if args.seed is None else args.seed,
                             args.log, community_config=config)
    run_managed_community_ticks(run, args.ticks,
                                decision_policy=model_app.community_policy if model_app else
                                configured_policy(args.policy)[0] if args.policy else None,
                                **model_budgets)
    _print_community(run, json_output=args.json)
    return EXIT_SUCCESS


def _print_community(run, *, json_output=False):
    observation = observe_community(run)
    if json_output:
        print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
        return
    print(f"{observation['world_title']}\nTick {observation['tick']}")
    reading = observation.get("reading")
    if reading:
        print(f"\n{reading['title']}")
        for paragraph in reading["paragraphs"]:
            print(f"\n{paragraph}")
        return
    if observation["recent_events"]:
        print("\n最近的公开事件：")
        for event in observation["recent_events"][-5:]:
            actor = event["actor_id"] or "世界"
            detail = f"：{event['utterance']}" if event["utterance"] else ""
            print(f"[Tick {event['tick']}, event:{event['sequence']}] {actor} {event['kind']}{detail}")
    for thread in observation["threads"]:
        if thread["text"]:
            print(f"\n{thread['text']}")
