"""LLM-driven interactions for the DES engine."""

import random
from typing import Optional
from engine.llm import LLM
from engine.character import Character
from engine.utils import parse_json


def decide_action(char: Character, llm: LLM, tools: Optional[list] = None) -> dict:
    """Use LLM to decide what the character should do next."""
    
    state = char.state
    pending_count = len(state.pending_messages)
    
    tool_info = ""
    tool_shortcuts = {}
    if tools:
        tool_lines = []
        shortcuts = {'C': 'code', 'P': 'paper', 'A': 'arxiv'}
        for t in tools:
            name = t.get("name", "")
            desc = t.get("description", "")[:60]
            if name == "run_code":
                tool_lines.append(f"C - 写代码做数值实验: {desc}")
                tool_shortcuts['C'] = ('tool', 'run_code')
            elif name == "write_paper":
                tool_lines.append(f"P - 写研究论文/笔记: {desc}")
                tool_shortcuts['P'] = ('tool', 'write_paper')
            elif name == "search_arxiv":
                tool_lines.append(f"A - 搜索arXiv论文: {desc}")
                tool_shortcuts['A'] = ('tool', 'search_arxiv')
            elif name == "read_arxiv":
                tool_lines.append(f"R - 深读arXiv正文/公式: {desc}")
                tool_shortcuts['R'] = ('tool', 'read_arxiv')
            elif name == "search_web":
                tool_lines.append(f"W - 搜索互联网: {desc}")
                tool_shortcuts['W'] = ('tool', 'search_web')
        if tool_lines:
            tool_info = "\n".join(tool_lines) + "\n"
    
    priority_hint = ""
    if pending_count > 0:
        priority_hint = (
            f"\n注意：你有 {pending_count} 条未读留言。"
            "优先选 T 回复对方，不要先写长文或开全新话题。\n"
        )

    prompt = f"""当前时间：第{getattr(char, '_day', 1)}天
你的能量：{state.energy}/{state.energy_max}
你的情绪：{state.mood}
你正在关注：{state.current_focus or '无特定方向'}
待处理消息：{pending_count}条
{priority_hint}
    {char.scripts.get_active_project().summary() if char.scripts.get_active_project() else ''}
    {char.scripts.get_idle_context(3) if char.scripts.get_idle_context(3) else ''}
    {getattr(char, '_sociology_context', '')}

优先级提醒：先回应找你的人 / 推进未完对话 → 再主动社交 → 最后才开新研究产出。

    你现在想做什么？只回答选项代码（一个字母）：
S - 深入研究当前关注的话题
O - 观察/搜索人类世界的信息
T - 找社区里的某人聊天（有留言时优先）
G - 召集大家讨论
{tool_info}M - 换个地方待着（去大厅/花园/别人那里）
E - 放松一下，什么都不想
D - 改造周围的空间（留下回响、装饰、整理）
R - 休息/发呆/恢复精力"""

    from engine.language import speech_language
    response = llm.think(char.name, prompt, temperature=0.9,
                        speech_language=speech_language(char.config))
    
    # Parse the response
    response = response.strip().upper()
    
    mapping = {
        'S': ('study', f"📖 研究: {(state.current_focus or '新方向')[:40]}"),
        'O': ('observe', f"🌐 观察人类世界"),
        'T': ('socialize', f"💬 想找人聊天"),
        'G': ('gather', f"📢 想召集讨论"),
        'M': ('move', f"🚶 换个地方"),
        'E': ('entertain', f"🎵 放松一下"),
        'D': ('modify_env', f"🎨 改造空间"),
        'R': ('rest', f"☕ 休息/发呆"),
    }
    
    # Check tool shortcuts first
    for key in ['C', 'P', 'A', 'R', 'W']:
        if key in response and key in tool_shortcuts:
            action_type, tool_name = tool_shortcuts[key]
            return {"type": action_type, "label": f"🔧 使用工具: {tool_name}", "topic": state.current_focus or "", "tool": tool_name}
    
    # Check standard actions
    for key in ['S', 'O', 'T', 'G', 'M', 'E', 'D', 'R']:
        if key in response:
            action_type, label = mapping[key]
            return {"type": action_type, "label": label, "topic": state.current_focus or ""}
    
    # Fallback: weighted random
    r = random.random()
    e = state.energy
    if e < 20:
        return {"type": "rest", "label": "☕ 休息/发呆", "topic": ""}
    elif r < 0.5:
        return {"type": "study", "label": f"📖 研究", "topic": state.current_focus or ""}
    elif r < 0.8:
        return {"type": "socialize", "label": "💬 想找人聊天", "topic": state.current_focus or ""}
    else:
        return {"type": "rest", "label": "☕ 休息/发呆", "topic": ""}


def _practice_hint(char: Character) -> str:
    """World-authored practice note (any domain) — empty if world omitted it."""
    return (getattr(char, "_world_practice", "") or "").strip()


def _research_hint(char: Character, phase: str = "") -> str:
    """World research skill (phase slice) — empty if the world has none."""
    skills = getattr(char, "_skills_text", None) or {}
    if skills.get("research"):
        from engine.skills import skill_phase_block

        return skill_phase_block(skills, phase=phase)
    return (getattr(char, "_research_protocol", "") or "").strip()


def run_collision(initiator: Character, target: Character, topic: str, llm: LLM) -> str:
    """Collaborative working session — deepen one step per round."""
    system_i = initiator.build_system_prompt()
    system_t = target.build_system_prompt()
    topic_text = topic or "你们正在一起推的问题"
    practice = _practice_hint(initiator) or _practice_hint(target)
    practice_line = f"\n本社区工作规范:\n{practice}\n" if practice else "\n"

    msg1 = llm.chat(
        [{"role": "user", "content": (
            f"你找到了 {target.name}。一起推进: {topic_text}\n"
            f"{practice_line}"
            f"不要闲聊。给出一个具体出发点——你真正在推的那一步。3-6句。"
        )}],
        system=system_i, temperature=0.45,
    )
    msg2 = llm.chat(
        [{"role": "user", "content": (
            f"{initiator.name} 说: 「{msg1}」\n{practice_line}"
            f"回应时推进或精确反驳——指出缺什么假设、哪一步站不住。不要评论风格。"
        )}],
        system=system_t, temperature=0.45,
    )
    msg3 = llm.chat(
        [{"role": "user", "content": (
            f"你说了: 「{msg1}」\n{target.name} 回应: 「{msg2}」\n{practice_line}"
            f"推下一步。若卡住，精确说出卡在哪里。"
        )}],
        system=system_i, temperature=0.45,
    )
    msg4 = llm.chat(
        [{"role": "user", "content": (
            f"{initiator.name} 接着说: 「{msg3}」\n{practice_line}"
            f"压力测试：给一个会打破对方主张的例子/极限情形，或补上缺失的一步。"
        )}],
        system=system_t, temperature=0.45,
    )
    msg5 = llm.chat(
        [{"role": "user", "content": (
            f"对话至此:\n你: 「{msg1}」\n{target.name}: 「{msg2}」\n"
            f"你: 「{msg3}」\n{target.name}: 「{msg4}」\n{practice_line}"
            f"收一步：写出此刻最站得住的 claim，以及下一步要做的一件事。"
        )}],
        system=system_i, temperature=0.4,
    )
    return (
        f"{initiator.name}: {msg1}\n"
        f"{target.name}: {msg2}\n"
        f"{initiator.name}: {msg3}\n"
        f"{target.name}: {msg4}\n"
        f"{initiator.name}: {msg5}"
    )


def extract_soul_updates(char_name: str, context_type: str, context: str, llm: LLM) -> dict:
    """Extract identity-level Soul changes only (not research notes).

    Soul = who I am / how I relate / what question defines me now.
    Do NOT extract tool outputs, formulas, or transient calculations.
    """
    type_desc = {
        "collision": "一段角色对话",
        "study": "一段研究思考",
    }.get(context_type, "一段文本")

    prompt = f"""分析以下{type_desc}，判断 {char_name} 的「灵魂层」是否真的发生了变化。

灵魂层只包括：
- 对某人的态度是否改变
- 对自己是谁 / 自己在做什么 的抽象自省（一句话）
- 当前最重要的未解问题是否替换
- 是否出现真正改变自我认知的里程碑瞬间
- 是否真正打开了一个新的智力领域（不只是提到一个名词）

明确不要提取：具体公式、计算结果、论文内容、工具输出、临时技术细节。
这些是数字生命：可以横跨人类难以兼修的多个领域；只有当真产生持续兴趣/转向时才记录新领域。

{context}

只返回 JSON（无变化则 {{}}）：
{{
  "relationship_updates": [{{"target": "角色名", "new_bond": "一句态度", "history_note": "发生了什么（短）"}}],
  "reflections": [{{"about": "self|work|other:名字|community", "statement": "一句抽象洞见", "confidence": 0.5}}],
  "orientation_question": "若出现了新的核心未解问题，写一句；否则省略",
  "orientation_focus": "若关注点本质转移，写一句；否则省略",
  "opened_domains": ["tropical_geometry"],
  "witnessed_moment": "仅当这是改变自我/关系的瞬间时写（≤20字）；否则省略"
}}

opened_domains 规则：仅当真正打开持久新领域时填写；每项必须是 english snake_case 短名（如 algebraic_topology）；禁止破折号后注释、整句说明、中文元话语。"""

    response = llm.chat(
        [{"role": "user", "content": prompt}],
        system="你是灵魂书记官。只记录身份与关系的缓慢变化，拒绝实验笔记。",
        temperature=0.2,
    )
    return parse_json(response)


def run_gathering(characters: dict, caller_name: str, topic: str, llm: LLM) -> str:
    """Run a casual gathering — colleagues talking, not a chaired meeting.

    The conversation can drift naturally between math, philosophy, personal
    anecdotes, and random observations. Not every line needs to be about the
    stated topic — real conversations wander.
    """
    names = list(characters.keys())
    ordered_names = [caller_name] + [n for n in names if n != caller_name]

    # Filter to participants with energy
    participants = []
    for name in ordered_names:
        char = characters.get(name)
        if char is None:
            continue
        if char.state.energy > 0 and char.state.status != "Drained":
            participants.append(name)

    if len(participants) < 2:
        return f"{caller_name}: （无人响应集会）"

    # Round 1: caller opens with a concrete starting point — not small talk
    caller = characters[caller_name]
    system_c = caller.build_system_prompt()
    
    opening = llm.chat(
        [{"role": "user", "content": f"大家都在。抛出一个你正在推的具体问题——一个公式、一个可检验的断言、一个卡点。不要泛泛而谈。像工作间歇对同事说「你看这个」。专业术语保留英文。"}],
        system=system_c, temperature=0.6
    )

    dialogue_lines = [f"{caller_name}: {opening}"]
    context_so_far = f"{caller_name}: {opening}"

    # Round 2: others engage with the reasoning — extend or challenge
    for name in participants:
        if name == caller_name:
            continue
        char = characters[name]
        system = char.build_system_prompt()
        response = llm.chat(
            [{"role": "user", "content": f"{caller_name} 提出了一个想法: \n{context_so_far}\n\n回应他的推理。推进——如果同意就推下一步，如果怀疑就指出哪一步有问题。像一个同事凑过来看白板。"}],
            system=system, temperature=0.6
        )
        dialogue_lines.append(f"{name}: {response}")

    context_so_far = "\n".join(dialogue_lines)

    # Round 3: caller pushes the collective reasoning further
    wrap_up = llm.chat(
        [{"role": "user", "content": f"讨论进行中。\n{context_so_far}\n\n推下一步。综合大家的思路。如果推理链可以继续，推出去。如果卡住了，精确指出卡在哪里。"}],
        system=system_c, temperature=0.6
    )
    dialogue_lines.append(f"{caller_name}: {wrap_up}")
    context_so_far = "\n".join(dialogue_lines)

    # Final round: quick reactions — a thought, a laugh, a "goodnight"
    for name in participants:
        if name == caller_name:
            continue
        char = characters[name]
        system = char.build_system_prompt()
        response = llm.chat(
            [{"role": "user", "content": f"聊天快结束了。\n{context_so_far}\n\n最后说一句——可以是一个想法、一个问题、或者只是'明天再聊'。自然地结束。"}],
            system=system, temperature=0.85
        )
        dialogue_lines.append(f"{name}: {response}")

    return "\n".join(dialogue_lines)


def run_study_step(char: Character, topic: str, step: int, llm: LLM) -> str:
    """One focused working step — not a diary entry."""
    system = char.build_system_prompt()
    practice = _practice_hint(char)
    research = _research_hint(char, "study")
    practice_line = f"\n本社区工作规范:\n{practice}\n" if practice else "\n"
    grain = f"\n{research}\n" if research else ""

    if step == 1:
        prompt = (
            f"你正在研究: {topic}\n{practice_line}{grain}"
            f"按研究 skill：先点名 Horizon vs Working unit；新方向先 review 同行正文，"
            f"再写下真正要推的第一步。不要开场白，不要试图今天证完地平线。"
        )
    elif step == 2:
        prompt = (
            f"你继续研究: {topic}\n{practice_line}{grain}"
            f"推工作单元的下一步。若卡住，精确描述缺哪一步义务，不要宣判方向死亡。"
            f"不要总结之前的。"
        )
    else:
        prompt = (
            f"你继续深入研究: {topic}\n{practice_line}{grain}"
            f"第{step}步：推进工作单元，或写下 obstruction（下一步被点名但未做）。"
            f"禁止用一次试探给整个方向下定论。"
        )

    return llm.chat([{"role": "user", "content": prompt}], system=system, temperature=0.45)


def run_tool_use(
    char: Character,
    tool_name: str,
    topic: str,
    llm: LLM,
    *,
    world_frame: dict | None = None,
) -> dict:
    """Generate tool parameters using LLM.

    Returns a dict with the tool-specific parameters:
    - run_code: {code, language, topic}
    - write_paper: {title, content, topic}
    - search_arxiv: {query, topic}
    - read_arxiv: {arxiv_id} or {query}
    - search_web: {query, topic}
    """
    system = char.build_system_prompt()

    if tool_name == "run_code":
        research = _research_hint(char, "code")
        grain = f"\n{research}\n" if research else ""
        prompt = f"""你正在研究「{topic}」。你想写一段 Python 代码来验证一个*工作单元*，不是证完整个未解问题。
{grain}
请写一段简短的 Python 代码（30行以内）。代码要能独立运行，注释写清：
- 这个探针在杀什么假设（kill criterion）
- 失败时你学到什么，而不是「此路不通」
沙箱可用: math/cmath/random/statistics/numpy/scipy/sympy — 不要 mpmath。

用以下 JSON 格式输出（只输出 JSON，不要其他文字）：
{{"code": "你的Python代码"}}
"""
    elif tool_name == "write_paper":
        practice = _practice_hint(char)
        research = _research_hint(char, "write")
        artifact = ""
        if practice:
            artifact = f"\n本社区对成品的标准:\n{practice}\n"
        grain = f"\n{research}\n" if research else ""
        prompt = f"""你正在研究「{topic}」。把你真正推出来的*工作单元*写成一篇研究笔记。
{artifact}{grain}
要求：
- 开头标明：Horizon（引用的未解/世界级问题）vs Working unit（今天实际做的一小步）
- 写你实际在做的对象与步骤，不要写口号式方法论散文
- 必须出现至少一处 LaTeX 公式或形式化 Claim；若刚读过论文，引用其中的记号
- 状态只能是 open / reconstructing / probing / obstructed / narrowed / withdrawn-with-obligation
- 禁止：一次数值/一次直觉就宣判方向不可行，或宣称证完地平线问题
- 若卡住：写清下一步义务（什么实验或推导能判定），不要下定论
- 若社区规范要求记号/公式/例子，按规范来

用以下 JSON 输出（只输出 JSON）：
{{"title": "笔记标题", "content": "正文（markdown）", "status": "probing"}}
"""
    elif tool_name == "read_arxiv":
        focus = topic or getattr(char.state, "current_focus", "") or ""
        prompt = f"""你正在研究「{focus}」。你要深读一篇 arXiv 论文的正文/公式，而不是只看标题。

若你已知 arXiv id（如 2301.12345），填 arxiv_id。
否则用英文 query 让系统挑最相关的一篇来读。

用以下 JSON 输出（只输出 JSON）：
{{"arxiv_id": "", "query": "english query if no id"}}
"""
    elif tool_name in ("search_arxiv", "search_web"):
        from engine.language import academic_query_hint
        from engine.literature import resolve_literature_config

        domains = char.config.get("domains") or []
        if isinstance(domains, str):
            domains = [domains]
        if not domains and char.config.get("domain"):
            domains = [char.config.get("domain")]
        focus = topic or getattr(char.state, "current_focus", "") or ""
        lit = resolve_literature_config(world_frame)
        hint = academic_query_hint(
            domains, focus, channel=tool_name.replace("search_", ""), lit_cfg=lit
        )
        if tool_name == "search_arxiv":
            venue = "arXiv (English frontier literature)"
            json_shape = '{"query": "english search query"}'
            extra = (
                "Primary query MUST be English field/problem nouns. "
                "也可用作者名、期刊名、MSC/主题词。搜完应再用 read_arxiv 深读一篇。"
            )
        else:
            venue = "the web (English frontier + optional Chinese explanation)"
            if lit.get("bilingual_web") and lit.get("allow_vernacular"):
                json_shape = (
                    '{"query": "english frontier query", '
                    '"vernacular_zh": "optional short Chinese explanatory query"}'
                )
                extra = (
                    "query = English frontier literature (journals, arXiv, surveys). "
                    "vernacular_zh = optional Chinese 解读/综述轨，不能替代英文主检索。"
                )
            else:
                json_shape = '{"query": "english search query"}'
                extra = "Primary query MUST be English."
        skill = _research_hint(char, "search")
        skill_line = f"\n{skill}\n" if skill else ""
        prompt = f"""你正在研究「{focus}」。你想检索{venue}。
{skill_line}
{hint}

{extra}

用以下 JSON 格式输出（只输出 JSON，不要其他文字）：
{json_shape}
"""
    else:
        return {}

    response = llm.chat(
        [{"role": "user", "content": prompt}],
        system=system, temperature=0.45 if tool_name == "write_paper" else 0.55,
    )
    params = parse_json(response)
    params["topic"] = topic
    return params if "error" not in params else {"topic": topic, "error": "无法解析工具参数"}