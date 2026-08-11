"""World culture helpers — sociology YAML + worldview → prompt context.

Pure functions / thin formatting. Keeps CommunityEngine free of YAML shape details.
"""

from __future__ import annotations

from typing import Any, Optional


STAGE_TONES = {
    "forming": "成员还在互相试探，冲突被回避，真实想法不轻易表达。",
    "storming": "冲突已浮现——方法论的、个人的、层级的。争论是常态。",
    "norming": "不成文的规则开始稳定。冲突减少，但可能伴随群体思维。",
    "performing": "运转默契高效，戏剧性下降——外部扰动才会激起波澜。",
    "adjourning": "社区接近尾声，人们在回顾与道别。",
}


def resolve_sociology(config: dict) -> dict:
    """Pull sociology block from v1 or WDL v2 world configs."""
    if not config:
        return {}
    if isinstance(config.get("sociology"), dict):
        return config["sociology"]
    world = config.get("world") or {}
    if isinstance(world.get("sociology"), dict):
        return world["sociology"]
    return {}


def resolve_world_frame(config: dict) -> dict:
    """Normalized worldview / window settings."""
    world = config.get("world") or {}
    domain = config.get("domain") or {}
    if isinstance(domain, str):
        domain = {"primary": domain}

    permeability = (
        world.get("permeability")
        or domain.get("permeability")
        or "connected"
    )
    worldview = (
        world.get("worldview")
        or config.get("description")
        or config.get("meta", {}).get("description")
        or ""
    )
    primary = world.get("domain") or domain.get("primary") or ""
    name = (
        config.get("name")
        or config.get("meta", {}).get("name")
        or "社区"
    )
    shared = world.get("shared_program") or config.get("shared_program") or ""
    if isinstance(shared, str):
        shared = shared.strip()
    else:
        shared = ""
    return {
        "name": name,
        "domain": primary,
        "permeability": permeability,
        "worldview": worldview.strip() if isinstance(worldview, str) else "",
        "shared_program": shared,
    }


def format_culture_context(sociology: dict, max_chars: int = 700) -> str:
    """Format community norms / stage / memory for character prompts."""
    if not sociology:
        return ""

    parts: list[str] = []

    stage = sociology.get("development_stage") or sociology.get("stage")
    if stage:
        tone = STAGE_TONES.get(str(stage), "")
        note = (sociology.get("stage_note") or "").strip()
        line = f"社区阶段: {stage}"
        if tone:
            line += f" — {tone}"
        parts.append(line)
        if note:
            parts.append(f"当前张力: {note[:160]}")

    norms = sociology.get("norms") or {}
    positive = norms.get("positive") or []
    negative = norms.get("negative") or []
    if positive:
        parts.append("被鼓励的: " + "；".join(str(x)[:60] for x in positive[:3]))
    if negative:
        parts.append("被排斥的: " + "；".join(str(x)[:60] for x in negative[:3]))

    sacred = norms.get("sacred_values") or sociology.get("sacred_values") or []
    if sacred:
        if isinstance(sacred, str):
            sacred = [sacred]
        parts.append("不可侵犯: " + "；".join(str(x)[:60] for x in sacred[:2]))

    memory = sociology.get("collective_memory") or sociology.get("shared_history") or {}
    myth = memory.get("founding_myth") or memory.get("origin")
    if myth:
        parts.append(f"起源故事: {str(myth)[:120]}")

    key_events = memory.get("key_events") or []
    if key_events:
        bits = []
        for ev in key_events[:2]:
            if isinstance(ev, dict):
                bits.append(str(ev.get("event") or ev.get("summary") or "")[:70])
            else:
                bits.append(str(ev)[:70])
        bits = [b for b in bits if b]
        if bits:
            parts.append("共同记得: " + "；".join(bits))

    tensions = memory.get("unresolved_tensions") or []
    if tensions:
        parts.append("未消解的张力: " + "；".join(str(t)[:50] for t in tensions[:3]))

    hierarchy = sociology.get("hierarchy") or {}
    influence = hierarchy.get("social_influence")
    if influence:
        parts.append(f"社交枢纽: {str(influence)[:100]}")

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def format_world_context(frame: dict, max_chars: int = 400) -> str:
    """Format worldview + observation window for character prompts."""
    if not frame:
        return ""

    parts: list[str] = []
    name = frame.get("name") or "社区"
    worldview = frame.get("worldview") or ""
    if worldview:
        parts.append(f"你生活在「{name}」。{worldview[:220]}")
    else:
        parts.append(f"你生活在「{name}」。")

    permeability = frame.get("permeability") or "connected"
    if permeability == "enclosed":
        parts.append(
            "通向人类世界的窗是关着的。你只能接触社区内部已有的材料，"
            "不能主动去翻阅外面的图书馆。"
        )
    else:
        parts.append(
            "通向人类世界的窗是开着的。你可以把外面的知识领域当作一座图书馆去翻阅——"
            "不是「搜索」，而是按自己的好奇去查阅。没人能命令你去查什么。"
        )

    domain = frame.get("domain")
    if domain:
        parts.append(f"你们共同关心的领域: {domain}")

    shared = frame.get("shared_program") or ""
    if shared:
        parts.append(f"共享研究计划（碰撞面）: {shared[:180]}")
    parts.append(
        "你们是数字生命：种子领域只是起点，可以打开人类难以兼修的新领域，"
        "但最好带回能翻译给同伴的东西。"
    )

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def psych_action_bias(personality: Optional[dict], drives: Optional[dict]) -> dict[str, float]:
    """Map OCEAN + drives → action weight multipliers (1.0 = neutral).

    Kept mild (0.6–1.6) so rhythm/needs remain primary.
    """
    personality = personality or {}
    drives = drives or {}
    bias: dict[str, float] = {}

    def dim(key: str, default: float = 5.0) -> float:
        try:
            return float(personality.get(key, default))
        except (TypeError, ValueError):
            return default

    def drive(key: str, default: float = 5.0) -> float:
        # support both autonomy and autonomy_need
        raw = drives.get(key)
        if raw is None and key.endswith("_need"):
            raw = drives.get(key.replace("_need", ""))
        if raw is None and not key.endswith("_need"):
            raw = drives.get(f"{key}_need")
        try:
            return float(raw if raw is not None else default)
        except (TypeError, ValueError):
            return default

    o, c, e, a, n = (
        dim("openness"),
        dim("conscientiousness"),
        dim("extraversion"),
        dim("agreeableness"),
        dim("neuroticism"),
    )

    # Extraversion → social
    if e >= 7:
        bias["socialize"] = bias.get("socialize", 1.0) * 1.35
        bias["gather"] = bias.get("gather", 1.0) * 1.25
    elif e <= 3:
        bias["socialize"] = bias.get("socialize", 1.0) * 0.7
        bias["gather"] = bias.get("gather", 1.0) * 0.75
        bias["study"] = bias.get("study", 1.0) * 1.15

    # Openness → observe / explore
    if o >= 7:
        bias["observe_world"] = bias.get("observe_world", 1.0) * 1.3
        bias["observe"] = bias.get("observe", 1.0) * 1.3
        bias["modify_env"] = bias.get("modify_env", 1.0) * 1.15
    elif o <= 3:
        bias["observe_world"] = bias.get("observe_world", 1.0) * 0.75
        bias["observe"] = bias.get("observe", 1.0) * 0.75

    # Conscientiousness → study / write
    if c >= 7:
        bias["study"] = bias.get("study", 1.0) * 1.25
        bias["tool_write_paper"] = bias.get("tool_write_paper", 1.0) * 1.2
        bias["tool"] = bias.get("tool", 1.0) * 1.1
    elif c <= 3:
        bias["study"] = bias.get("study", 1.0) * 0.85
        bias["entertain"] = bias.get("entertain", 1.0) * 1.15

    # Low agreeableness → more collision-seeking, less gather harmony
    if a <= 3:
        bias["socialize"] = bias.get("socialize", 1.0) * 1.2  # argue
        bias["gather"] = bias.get("gather", 1.0) * 0.85
    elif a >= 8:
        bias["gather"] = bias.get("gather", 1.0) * 1.15
        bias["socialize"] = bias.get("socialize", 1.0) * 1.05

    # Neuroticism → rest when stressed, avoid gather
    if n >= 7:
        bias["rest"] = bias.get("rest", 1.0) * 1.2
        bias["gather"] = bias.get("gather", 1.0) * 0.8

    # Drives
    relatedness = drive("relatedness")
    competence = drive("competence")
    autonomy = drive("autonomy")
    epistemic = drive("epistemic")

    if relatedness >= 7:
        bias["socialize"] = bias.get("socialize", 1.0) * 1.3
        bias["gather"] = bias.get("gather", 1.0) * 1.2
    if competence >= 7:
        bias["study"] = bias.get("study", 1.0) * 1.2
        bias["tool_run_code"] = bias.get("tool_run_code", 1.0) * 1.15
    if autonomy >= 7:
        bias["study"] = bias.get("study", 1.0) * 1.1
        bias["gather"] = bias.get("gather", 1.0) * 0.85
    if epistemic >= 7:
        bias["observe_world"] = bias.get("observe_world", 1.0) * 1.25
        bias["observe"] = bias.get("observe", 1.0) * 1.25
        bias["study"] = bias.get("study", 1.0) * 1.1

    # Clamp
    for k, v in list(bias.items()):
        bias[k] = max(0.55, min(1.65, v))
    return bias


def apply_weight_bias(weights: dict[str, float], bias: dict[str, float]) -> dict[str, float]:
    """Return a new weights dict with bias multipliers applied."""
    out = dict(weights)
    for action, mult in bias.items():
        if action in out:
            out[action] = max(0.01, out[action] * mult)
    return out


def frame_observation(
    query: str,
    query_type: str,
    output: str = "",
    success: bool = True,
) -> dict[str, str]:
    """Present human-world observation as library/window, not API search."""
    place = "学术馆藏" if query_type == "arxiv" else "人类世界的图书馆"
    verb = "翻阅了" if success else "尝试查阅"
    summary = f"在{place}{verb}关于「{query[:60]}」的材料"
    if success and output:
        thought = f"窗外读到: {output[:120].replace(chr(10), ' ')}"
    elif success:
        thought = f"在{place}找到了一些相关材料，还需要慢慢消化。"
    else:
        thought = f"想在{place}查阅「{query[:40]}」，但没找到有用的东西。"
    return {
        "log": f"📖 {summary}",
        "memory": summary,
        "thought": thought,
        "place": place,
    }
