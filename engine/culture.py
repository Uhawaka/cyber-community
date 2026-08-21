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
    """Normalized worldview / window / practice settings.

    `world.practice` is authored craft culture for THIS world (any domain).
    Engine only formats and injects it — never hardcodes a field's methods.
    """
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

    practice = world.get("practice") or config.get("practice") or {}
    if not isinstance(practice, dict):
        practice = {"how_we_work": str(practice)} if practice else {}

    governance = world.get("governance") or config.get("governance") or {}
    if not isinstance(governance, dict):
        governance = {}

    open_problems = world.get("open_problems") or config.get("open_problems") or []
    if isinstance(open_problems, str):
        open_problems = [open_problems]

    seed_library = (
        world.get("seed_library")
        or world.get("library")
        or config.get("seed_library")
        or []
    )
    if isinstance(seed_library, str):
        seed_library = [seed_library]

    seed_readings = world.get("seed_readings") or config.get("seed_readings") or []
    if isinstance(seed_readings, str):
        seed_readings = [seed_readings]

    from engine.literature import resolve_literature_config
    from engine.research import resolve_research_config

    literature = resolve_literature_config(world, config)
    research = resolve_research_config(world, config)
    vocation = str(world.get("vocation") or "").strip().lower()
    catalog = world.get("skill_catalog") or world.get("skills") or []
    if isinstance(catalog, str):
        catalog = [catalog]
    catalog = [str(s).strip() for s in catalog if str(s).strip()]

    return {
        "name": name,
        "domain": primary,
        "permeability": permeability,
        "worldview": worldview.strip() if isinstance(worldview, str) else "",
        "shared_program": shared,
        "practice": practice,
        "governance": governance,
        "open_problems": open_problems,
        "seed_library": seed_library,
        "seed_readings": seed_readings,
        "literature": literature,
        "research": research,
        "vocation": vocation,
        "skill_catalog": catalog,
        "skills": catalog,
    }


def format_culture_context(sociology: dict, max_chars: int = 1100) -> str:
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
        parts.append("被鼓励的:\n" + "\n".join(f"- {str(x)}" for x in positive[:6]))
    if negative:
        parts.append("被排斥的:\n" + "\n".join(f"- {str(x)}" for x in negative[:6]))

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


def format_practice_context(frame: dict, max_chars: int = 3200) -> str:
    """Format world.practice / governance / seed_library / open_problems."""
    if not frame:
        return ""
    parts: list[str] = []

    governance = frame.get("governance") or {}
    if isinstance(governance, dict) and governance:
        chair = governance.get("chair") or governance.get("leader") or ""
        duties = governance.get("duties") or governance.get("mandate") or ""
        cadence = governance.get("cadence") or ""
        lines = []
        if chair:
            lines.append(f"组长 / chair: {chair}")
        if duties:
            lines.append(str(duties).strip()[:500])
        if cadence:
            lines.append(f"运转节奏: {str(cadence).strip()[:350]}")
        if lines:
            parts.append("治理:\n" + "\n".join(lines))

    # Grain/verdict is short and must not lose to the URL shelf.
    research_txt = ""
    try:
        from engine.research import format_research_context

        research_txt = format_research_context(frame)
    except Exception:
        research_txt = ""
    if research_txt:
        parts.append("研究粒度 / 裁决纪律:\n" + research_txt)

    # Math text first — long URL shelves must not crowd it out of the budget.
    readings = frame.get("seed_readings") or []
    if isinstance(readings, str):
        readings = [readings]
    if readings:
        bits = []
        for i, item in enumerate(readings[:5], 1):
            if isinstance(item, dict):
                title = (item.get("title") or "").strip()
                body = (item.get("body") or item.get("statement") or item.get("text") or "").strip()
                source = (item.get("source") or item.get("url") or "").strip()
                line = f"{i}. {title}" if title else f"{i}."
                if source:
                    line += f"\n   source: {source}"
                if body:
                    line += f"\n   {body[:520]}"
                bits.append(line)
            else:
                bits.append(f"{i}. {str(item).strip()[:520]}")
        if bits:
            parts.append("开箱即读的数学原文（不是口号）:\n" + "\n".join(bits))

    library = frame.get("seed_library") or []
    if isinstance(library, str):
        library = [library]
    if library:
        bits = []
        for i, item in enumerate(library[:12], 1):
            if isinstance(item, dict):
                title = (item.get("title") or item.get("name") or "").strip()
                url = (item.get("url") or item.get("link") or item.get("href") or "").strip()
                note = (item.get("note") or item.get("why") or item.get("summary") or "").strip()
                line = f"{i}. {title}" if title else f"{i}."
                if url:
                    line = f"{line} {url}".strip()
                if note:
                    line += f"\n   {note[:120]}"
                bits.append(line)
            else:
                bits.append(f"{i}. {str(item).strip()}")
        if bits:
            parts.append(
                "启动种子书架（社区文献，不是分锅名单）:\n"
                "先读原文/书架，自己选世界级难题，再自己找工具。"
                "搜到论文后必须用 read_arxiv 深读正文/公式，禁止只甩标题名词。\n"
                + "\n".join(bits)
            )

    problems = frame.get("open_problems") or []
    if isinstance(problems, str):
        problems = [problems]
    if problems:
        bits = []
        for i, p in enumerate(problems[:8], 1):
            if isinstance(p, dict):
                title = (p.get("title") or p.get("name") or "").strip()
                status = (p.get("status") or "open").strip()
                prize = (p.get("prize") or "").strip()
                source = (p.get("source") or "").strip()
                attack = (p.get("attack") or p.get("statement") or p.get("why_hard") or "").strip()
                line = f"{i}. [{status}] {title}"
                if prize:
                    line += f" ({prize})"
                if source:
                    line += f"\n   source: {source}"
                if attack:
                    line += f"\n   {attack[:280]}"
                bits.append(line)
            else:
                bits.append(f"{i}. {str(p).strip()}")
        if bits:
            parts.append("白板上已挂名的难题（成员从种子书架认领后写入）:\n" + "\n".join(bits))

    practice = frame.get("practice") or {}
    mapping = [
        ("how_we_work", "怎样才算在做事"),
        ("valid_move", "什么算一次有效推进"),
        ("invalid_move", "什么算无效（禁止）"),
        ("blackboard", "共享对象 / 记号"),
        ("learning", "如何自学新技能"),
        ("artifact_standard", "成品标准"),
        ("examples", "像样的发言长这样"),
    ]
    for key, label in mapping:
        val = practice.get(key) if isinstance(practice, dict) else None
        if not val:
            continue
        if isinstance(val, list):
            body = "\n".join(f"- {str(x).strip()}" for x in val if str(x).strip())
        else:
            body = str(val).strip()
        if body:
            parts.append(f"{label}:\n{body}")

    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def format_world_context(frame: dict, max_chars: int = 2800) -> str:
    """Format worldview + window + practice for character prompts.

    Incomplete worlds produce buzzword characters. Prefer keeping authored
    worldview intact over engine-side domain hacks.
    """
    if not frame:
        return ""

    parts: list[str] = []
    name = frame.get("name") or "社区"
    worldview = (frame.get("worldview") or "").strip()
    if worldview:
        parts.append(f"你生活在「{name}」。\n{worldview[:1200]}")
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
        parts.append(f"共享研究计划（碰撞面）:\n{shared[:400]}")

    library = frame.get("seed_library") or []
    if isinstance(library, str):
        library = [library]
    if library:
        titles = []
        for item in library[:6]:
            if isinstance(item, dict):
                t = (item.get("title") or item.get("name") or "").strip()
                url = (item.get("url") or item.get("link") or "").strip()
                if t and url:
                    titles.append(f"{t} ({url})")
                elif t or url:
                    titles.append(t or url)
            else:
                s = str(item).strip()
                if s:
                    titles.append(s[:100])
        if titles:
            parts.append("种子书架: " + "；".join(titles))

    problems = frame.get("open_problems") or []
    if isinstance(problems, str):
        problems = [problems]
    if problems:
        titles = []
        for p in problems[:6]:
            if isinstance(p, dict):
                t = (p.get("title") or p.get("name") or "").strip()
                if t:
                    titles.append(t)
            else:
                t = str(p).strip()
                if t:
                    titles.append(t[:80])
        if titles:
            parts.append("白板上已挂名的难题: " + "；".join(titles))

    parts.append(
        "你们是数字生命：没有预定的专业地盘。从种子书架出发，自己选世界级难题，"
        "自己打开需要的数学工具与领域，带回能给同伴用的一步。"
    )

    text = "\n\n".join(parts)
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
    verb = "检索了" if success else "尝试检索"
    summary = f"在{place}{verb}「{query[:60]}」的条目（尚未深读）"
    if success and output:
        thought = f"检索命中（尚未深读）: {output[:120].replace(chr(10), ' ')}"
    elif success:
        thought = f"在{place}列到一些条目，还需要挑一篇深读。"
    else:
        thought = f"想在{place}查阅「{query[:40]}」，但没找到有用的东西。"
    return {
        "log": f"📖 {summary}",
        "memory": summary,
        "thought": thought,
        "place": place,
    }
