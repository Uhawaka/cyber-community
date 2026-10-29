"""Grow a world from its own material: secrets, beliefs, and location danger.

Reads an authoring source, asks the configured model for one candidate extension per
character, writes a *candidate* source under outputs/candidates/ and validates it by
building a package. The shipped world is never touched.

    python -m scripts.grow_world worlds/sources/stone-step.json --model-config /tmp/cc-model.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.adapters.openai_compatible import OpenAICompatibleTextModel
from engine.world import build_community_package

ROOT = Path(__file__).resolve().parents[1]

PROMPT = """你在为一个虚构的中国北方小镇世界补写人物的私事。只依据给定材料，不要发明新材料。

人物：{name}（{identity}）
在意的：{values}
不能碰的：{taboos}
长期想要的：{desire}
与谁有什么牵扯：{edges}
已经公开的信息：{public}

请写：
1. secrets：2 条他没说出口的具体的事。要能被别人在对话里撞破——涉及某个具体的东西、某次具体的动作、或某个具体的人；不要抽象性格。
2. beliefs：2 条他相信但没核实过的事，必须关于上面出现的某个具体的人（可能是错的）。

在场的人：{roster}。文中只能用名字指人，不要写编号。

只输出 JSON：{{"secrets": ["…", "…"], "beliefs": ["…", "…"]}}
每条 20–45 字，中文，不要解释，不要编号。"""


def _flat(value) -> str:
    if isinstance(value, (list, tuple)):
        return "；".join(str(item) for item in value) or "（未写）"
    return str(value or "（未写）")


def _name_of(entry, fallback="") -> str:
    return str((entry.get("profile") or {}).get("name") or entry.get("name") or fallback)


def _edges(world, character_id) -> str:
    rows = []
    for edge in world.get("relationships", []) if isinstance(world.get("relationships"), list) else []:
        if edge.get("source_id") == character_id:
            rows.append(f"{edge.get('target_id')}：{_flat(edge.get('stance') or edge.get('description'))}")
    return "；".join(rows) or "（没有写明的牵扯）"


def _repair(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model did not return JSON")
    body = raw[start:end + 1]
    body = __import__("re").sub(r",\s*([}\]])", r"\1", body)
    return json.loads(body)


def _ask(model, world, character) -> dict:
    soul = character.get("soul") or {}
    prompt = PROMPT.format(
        name=_name_of(character, str(character.get("id"))),
        identity=_flat(soul.get("identity")),
        values=_flat(soul.get("values")),
        taboos=_flat(soul.get("taboos")),
        desire=_flat(soul.get("long_term_desire") or soul.get("drives")),
        edges=_edges(world, character.get("id")),
        public=_flat(world.get("public_knowledge")),
        roster="、".join(
            name for name in (_name_of(item) for item in world["characters"].values()) if name
        ),
    )
    raw = model.complete(prompt, timeout_seconds=120)
    try:
        data = _repair(raw)
    except ValueError:
        data = _repair(model.complete(prompt + "\n只输出一行 JSON，结尾不要多余逗号。", timeout_seconds=120))

    names = {key: _name_of(value, key) for key, value in world["characters"].items()}

    def clean(item):
        text = str(item).strip()
        for key, name in names.items():
            text = text.replace(key, name)
        return text

    return {
        "secrets": [clean(item) for item in data.get("secrets", []) if str(item).strip()][:2],
        "beliefs": [clean(item) for item in data.get("beliefs", []) if str(item).strip()][:2],
    }


DANGER_PROMPT = """判断一个地点的危险度，只依据给定材料。

地点：{name}
描述：{description}
能做的事：{affordances}
可容人数：{capacity}

危险度 0–5：0 是日常安全，3 是需要当心，5 是可能受伤。依据必须是描述里已有的东西
（火、水、高处、重物、湿滑、无人看管），不要凭空加。

只输出 JSON：{{"danger": 0, "reason": "…"}}"""


def _rate_danger(model, location) -> tuple[int, str]:
    prompt = DANGER_PROMPT.format(
        name=location.get("name"), description=location.get("description") or "（未写）",
        affordances="、".join(key for key, on in (location.get("affordances") or {}).items() if on) or "（未写）",
        capacity=location.get("capacity", "（未写）"),
    )
    data = _repair(model.complete(prompt, timeout_seconds=90))
    return max(0, min(5, int(data.get("danger", 0)))), str(data.get("reason") or "")


ERRAND_PROMPT = """为一个人物写一件「必须去别处办的事」，只依据给定材料。

人物：{name}（{identity}）
他所在的地方：{here}
他在意的：{values}
他长期想要的：{desire}

可以动用、但都不在他手边的物件（只能从这里选，不能发明）：
{candidates}

请写 1 件事：他必须亲自去某个地方、接触上面某一件东西才能办成；要有一个人或一条规矩挡着，
不能顺顺利利就办完。句子里必须原样出现那件东西的名字和它所在地点名字。

只输出 JSON：{{"object_id": "…", "goal": "…"}}
goal 25–45 字，中文一句话，不要解释。"""


def _graph(world):
    edges = {}
    for passage in world.get("passages", []):
        edges.setdefault(passage["origin_id"], set()).add(passage["destination_id"])
        edges.setdefault(passage["destination_id"], set()).add(passage["origin_id"])
    return edges


def _reachable(edges, start):
    seen, queue = {start}, [start]
    while queue:
        current = queue.pop()
        for nxt in edges.get(current, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _errand(model, world, character):
    profile = character.get("profile") or {}
    soul = character.get("soul") or {}
    here = profile.get("location_id") or ""
    places = {item["id"]: item.get("name", item["id"])
              for item in (world["locations"].values() if isinstance(world["locations"], dict) else world["locations"])}
    reachable = _reachable(_graph(world), here)
    options = [
        item for item in world["resources"]
        if item.get("location_id") != here and item.get("location_id") in reachable
    ][:8]
    if not options:
        return None
    lines = [f"- {item['id']}｜{item.get('name')}｜在{places.get(item.get('location_id'), item.get('location_id'))}"
             for item in options]
    prompt = ERRAND_PROMPT.format(
        name=profile.get("name") or character.get("id"), identity=_flat(soul.get("identity")),
        here=places.get(here, here), values=_flat(soul.get("values")),
        desire=_flat(soul.get("long_term_desire") or soul.get("drives")),
        candidates="\n".join(lines),
    )
    data = _repair(model.complete(prompt, timeout_seconds=120))
    chosen = next((item for item in options if item["id"] == str(data.get("object_id")).strip()), None)
    goal = str(data.get("goal") or "").strip()
    if chosen is None or not goal:
        return None
    place_name = places.get(chosen.get("location_id"), "")
    if chosen.get("name") not in goal or place_name not in goal:
        return None  # 名字没原样落到目标里，模型就是在自由发挥
    return {"goal": goal, "object_id": chosen["id"], "place_id": chosen["location_id"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--model-config", required=True)
    parser.add_argument("--only", default="", help="comma separated character ids")
    parser.add_argument("--with-danger", action="store_true", help="也给每个地点评一个危险度")
    parser.add_argument("--with-errands", action="store_true", help="给每人写一件必须去别处办的事")
    args = parser.parse_args()

    source_path = Path(args.source)
    world = json.loads(source_path.read_text(encoding="utf-8"))
    config = json.loads(Path(args.model_config).read_text(encoding="utf-8"))
    config.setdefault("llm", {})["temperature"] = 0.8
    model = OpenAICompatibleTextModel(config)

    wanted = {item.strip() for item in args.only.split(",") if item.strip()}
    grown, failures = {}, {}
    for character_id, character in world["characters"].items():
        if wanted and character_id not in wanted:
            continue
        try:
            grown[character_id] = _ask(model, world, {**character, "id": character_id})
        except Exception as error:  # noqa: BLE001 - 一份失败不该拖垮整次生成
            failures[character_id] = str(error)[:160]

    candidate = json.loads(json.dumps(world))
    for character_id, extra in grown.items():
        soul = candidate["characters"][character_id].setdefault("soul", {})
        for field in ("secrets", "beliefs"):
            merged = list(soul.get(field) or [])
            merged.extend(item for item in extra[field] if item not in merged)
            soul[field] = merged

    errands = {}
    if args.with_errands:
        for character_id, character in world["characters"].items():
            if wanted and character_id not in wanted:
                continue
            try:
                errand = _errand(model, world, {**character, "id": character_id})
            except Exception as error:  # noqa: BLE001
                failures[f"errand:{character_id}"] = str(error)[:160]
                continue
            if errand is None:
                failures[f"errand:{character_id}"] = "没有可用的异地物件或输出不合规"
                continue
            errands[character_id] = errand
            goals = list(candidate["characters"][character_id].setdefault("profile", {}).get("goals") or [])
            if errand["goal"] not in goals:
                goals.append(errand["goal"])
            candidate["characters"][character_id]["profile"]["goals"] = goals
            errands_list = list(candidate["characters"][character_id]["profile"].get("errands") or [])
            entry = {"goal": errand["goal"], "object_id": errand["object_id"], "place_id": errand["place_id"]}
            if entry not in errands_list:
                errands_list.append(entry)
            candidate["characters"][character_id]["profile"]["errands"] = errands_list

    def _loc_map(entries):
        return entries if isinstance(entries, dict) else {item["id"]: item for item in entries}

    dangers = {}
    if args.with_danger:
        for location_id, location in _loc_map(world["locations"]).items():
            try:
                dangers[location_id] = _rate_danger(model, location)
            except Exception as error:  # noqa: BLE001
                failures[f"location:{location_id}"] = str(error)[:160]

    stamp = __import__("time").strftime("%Y%m%d-%H%M%S")
    candidates = ROOT / "outputs" / "candidates"
    candidates.mkdir(parents=True, exist_ok=True)
    for location_id, (rating, reason) in dangers.items():
        _loc_map(candidate["locations"])[location_id]["danger"] = rating
    out = candidates / f"{source_path.stem}-grown-{stamp}.json"
    out.write_text(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"候选源：{out.relative_to(ROOT)}")
    for character_id, extra in grown.items():
        print(f"\n[{character_id}]")
        for item in extra["secrets"]:
            print("  秘密:", item)
        for item in extra["beliefs"]:
            print("  信念:", item)
    for location_id, (rating, reason) in dangers.items():
        print(f"  危险度 {rating} {location_id}：{reason[:60]}")
    for character_id, error in failures.items():
        print(f"\n[{character_id}] 生成失败：{error}")

    package = candidates / f"{source_path.stem}-pkg-{stamp}"
    try:
        build_community_package(out, package)
    except Exception as error:  # noqa: BLE001 - 编译失败要把原因原样交出来
        print(f"\n编译：失败 {error}")
        return 1
    print(f"\n编译：通过 {package.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
