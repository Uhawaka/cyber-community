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
        if tool_lines:
            tool_info = "\n".join(tool_lines) + "\n"
    
    prompt = f"""当前时间：第{getattr(char, '_day', 1)}天
你的能量：{state.energy}/{state.energy_max}
你的情绪：{state.mood}
你正在关注：{state.current_focus or '无特定方向'}
待处理消息：{pending_count}条

    {char.scripts.get_active_project().summary() if char.scripts.get_active_project() else ''}
    {char.scripts.get_idle_context(3) if char.scripts.get_idle_context(3) else ''}
    {getattr(char, '_sociology_context', '')}

    你现在想做什么？只回答选项代码（一个字母）：
S - 深入研究当前关注的话题
O - 观察/搜索人类世界的信息
T - 找社区里的某人聊天
G - 召集大家讨论
{tool_info}M - 换个地方待着（去大厅/花园/别人那里）
E - 放松一下，什么都不想
D - 改造周围的空间（留下回响、装饰、整理）
R - 休息/发呆/恢复精力"""

    response = llm.think(char.name, prompt, temperature=0.9)
    
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
    for key in ['C', 'P', 'A']:
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


def run_collision(initiator: Character, target: Character, topic: str, llm: LLM) -> str:
    """Run a collaborative reasoning session — NOT a chat.

    Characters work through a problem together. Each round advances the
    reasoning by one step: a claim, a computation, a derivation, an objection.
    """
    
    system_i = initiator.build_system_prompt()
    system_t = target.build_system_prompt()
    
    # Round 1: initiator proposes a concrete step — computation, derivation, or claim
    msg1 = llm.chat(
        [{"role": "user", "content": f"你找到了 {target.name}。你想和他一起推演一个问题: {topic or '你最近的研究'}\n\n不要泛泛而谈。给出一个具体的出发点——一个公式、一个计算、一个不等式、或一个你正在验证的猜想。像一个数学家在工作，不是在写科普。"}],
        system=system_i, temperature=0.6
    )
    
    # Round 2: target engages with the actual reasoning — extend, challenge, or redirect
    msg2 = llm.chat(
        [{"role": "user", "content": f"{initiator.name} 说: 「{msg1}」\n\n回应他的推理。不是评论——是推进。如果同意，推导下一步。如果怀疑，指出具体哪一步有问题。如果有不同角度，从那里开始推。像两个人在白板前面一起工作。"}],
        system=system_t, temperature=0.6
    )
    
    # Round 3: initiator pushes further — where does this lead? What breaks?
    msg3 = llm.chat(
        [{"role": "user", "content": f"你说了: 「{msg1}」\n\n{target.name} 回应: 「{msg2}」\n\n推下一步。这个推理链的下一步是什么？如果顺畅，继续推导。如果遇到障碍，精确指出问题在哪里。不要总结——推进。"}],
        system=system_i, temperature=0.6
    )
    
    # Optional 4th round if the reasoning is deep enough
    if len(msg1) + len(msg2) + len(msg3) > 600:
        msg4 = llm.chat(
            [{"role": "user", "content": f"{initiator.name} 接着说: 「{msg3}」\n\n回应。如果推理链已经到头，指出卡在哪里。如果还有一步可推，推出去。"}],
            system=system_t, temperature=0.6
        )
        return f"{initiator.name}: {msg1}\n{target.name}: {msg2}\n{initiator.name}: {msg3}\n{target.name}: {msg4}"
    
    return f"{initiator.name}: {msg1}\n{target.name}: {msg2}\n{initiator.name}: {msg3}"


def extract_soul_updates(char_name: str, context_type: str, context: str, llm: LLM) -> dict:
    """Extract soul-updating insights from a collision or study step.

    Returns a dict with optional keys: relationship_updates, knowledge_gained,
    knowledge_questions, knowledge_abandoned, witnessed_moment.
    """
    type_desc = {
        "collision": "一段角色对话",
        "study": "一段研究思考",
    }.get(context_type, "一段文本")

    prompt = f"""分析以下{type_desc}，提取 {char_name} 身上发生了什么变化。

{context}

返回一个 JSON 对象，只包含真正有变化的字段（没有变化的不要写）。格式：
{{
  "relationship_updates": [{{"target": "角色名", "new_bond": "新的关系描述", "history_note": "发生了什么"}}],
  "knowledge_gained": ["获得的新认知"],
  "knowledge_questions": ["产生的新问题"],
  "knowledge_abandoned": ["放弃的旧想法"],
  "witnessed_moment": "一个值得记住的时刻（一句话，20字以内）"
}}

如果没有任何变化，返回空对象 {{}}。只返回 JSON，不要其他文字。"""

    response = llm.chat(
        [{"role": "user", "content": prompt}],
        system="你是社区的灵魂记录者。简洁、精确。",
        temperature=0.3,
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
        [{"role": "user", "content": f"大家都在。抛出一个具体的数学问题或者你正在推的东西——一个公式、一个不等式、一个你想验证的猜想。不要泛泛而谈。像一个数学家在工作间歇对同事说'你看这个'。"}],
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
    """Execute one step of mathematical reasoning — NOT a diary entry.

    Each step advances a chain of reasoning: computation, derivation,
    conjecture formation, or identification of an obstacle.
    """
    system = char.build_system_prompt()
    
    if step == 1:
        prompt = f"你正在研究: {topic}\n\n不要泛泛而谈。从具体的地方开始——写下一个公式、一个不等式、一个你想验证的数值关系。像一个数学家在工作：如果你在算东西，写出你在算什么。如果你在推导，写出第一步。"
    elif step == 2:
        prompt = f"你继续研究: {topic}\n\n上一步你开始了推理。现在推下一步。如果顺畅，继续推导。如果遇到障碍，精确描述问题。不要总结之前的——推进。"
    else:
        prompt = f"你继续深入研究: {topic}\n\n这是第{step}步。推下去——或者如果推理链断了，指出断在哪里。像一个数学家盯着白板上的推导，试图找到下一步。"
    
    return llm.chat([{"role": "user", "content": prompt}], system=system, temperature=0.5)


def run_tool_use(char: Character, tool_name: str, topic: str, llm: LLM) -> dict:
    """Generate tool parameters using LLM.

    Returns a dict with the tool-specific parameters:
    - run_code: {code, language, topic}
    - write_paper: {title, content, topic}
    - search_arxiv: {query, topic}
    """
    system = char.build_system_prompt()

    if tool_name == "run_code":
        prompt = f"""你正在研究「{topic}」。你想写一段 Python 代码来验证你的想法。

请写一段简短的 Python 代码（30行以内）。代码要能独立运行，有清晰的注释说明你在验证什么。

用以下 JSON 格式输出（只输出 JSON，不要其他文字）：
{{"code": "你的Python代码"}}
"""
    elif tool_name == "write_paper":
        prompt = f"""你正在研究「{topic}」。你想把你的发现写成一篇简短的研究笔记。

写一篇结构清晰的研究笔记（300-500字）：
- 标题：一个吸引人的学术标题
- 正文：你的核心发现、推理过程、你的结论

用以下 JSON 格式输出（只输出 JSON，不要其他文字）：
{{"title": "论文标题", "content": "论文正文（markdown格式）"}}
"""
    elif tool_name == "search_arxiv":
        prompt = f"""你正在研究「{topic}」。你想看看人类在 arXiv 上发表了什么相关论文。

想一个精确的英文搜索关键词（1-5个单词），能最好地反映你想找的内容。

用以下 JSON 格式输出（只输出 JSON，不要其他文字）：
{{"query": "搜索关键词"}}
"""
    else:
        return {}

    response = llm.chat(
        [{"role": "user", "content": prompt}],
        system=system, temperature=0.7,
    )
    params = parse_json(response)
    params["topic"] = topic
    return params if "error" not in params else {"topic": topic, "error": "无法解析工具参数"}