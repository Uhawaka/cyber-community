"""Deep Thinking Engine.

Characters don't just act — they reflect, synthesize, and form understanding.
This engine drives the internal process that transforms raw experience
into genuine intellectual depth.

Architecture:
  Trigger: after N study steps or important events
  Process: 3 rounds of deepening reflection
    Round 1: OBSERVE — what happened, patterns noticed
    Round 2: CONNECT — how this relates to existing knowledge
    Round 3: UNDERSTAND — personal synthesis, genuine insight
  Output: structured understanding written to Soul
"""

from dataclasses import dataclass, field
from typing import Optional
import random


@dataclass
class DeepThought:
    """A single deep thinking session result."""
    character: str
    day: int
    trigger: str  # what prompted this thinking session
    observations: str   # Round 1: surface patterns
    connections: str    # Round 2: links to existing knowledge
    understanding: str  # Round 3: genuine insight
    confidence: float   # 0.0 — 1.0
    implications: list = field(default_factory=list)
    open_questions: list = field(default_factory=list)


class DeepThinkEngine:
    """Manages deep thinking sessions for characters."""

    def __init__(self, llm):
        self.llm = llm
        self.history: dict[str, list[DeepThought]] = {}  # char_name -> thoughts

    def should_trigger(self, char_name: str, study_count: int, 
                        collision_count: int, tool_count: int,
                        hours_since_last: float) -> bool:
        """Determine if a deep thinking session should be triggered.

        Requires some accumulated experience — never fires on empty counters
        just because wall/virtual time passed (avoids eager first-day fanout).

        Triggers when:
        - 5+ study steps and ≥4h since last deep think
        - 2+ collisions and ≥8h since last
        - 3+ tool uses and ≥4h since last
        - ≥3 total events and ≥12h since last (cooldown reflection)
        """
        total = study_count + collision_count + tool_count
        if total <= 0:
            return False
        if study_count >= 5 and hours_since_last >= 4:
            return True
        if collision_count >= 2 and hours_since_last >= 8:
            return True
        if tool_count >= 3 and hours_since_last >= 4:
            return True
        if total >= 3 and hours_since_last >= 12:
            return True
        return False

    def think_deep(self, char, recent_events: list, soul_context: str) -> DeepThought:
        """Run a deep thinking session.

        Args:
            char: The Character instance
            recent_events: List of recent event dicts (study_steps, collisions, tool_uses)
            soul_context: Current Soul context for the character

        Returns:
            DeepThought with synthesized understanding
        """
        system = char.build_system_prompt()
        name = char.name

        # Build event summary
        event_summary = self._summarize_events(recent_events)

        # ── Round 1: OBSERVE — What happened? ──
        r1_prompt = f"""你刚经历了一些研究和对话。现在你需要进行深度反思。

最近的经历:
{event_summary}

你已有的知识:
{soul_context}

第一轮反思——观察（OBSERVE）：
你注意到了什么？有什么模式、异常、或者让你停下来想"等等，这个有意思"的东西？
不要下结论，只记录你的观察。写2-3句话。"""

        observations = self.llm.chat(
            [{"role": "user", "content": r1_prompt}],
            system=system, temperature=0.6
        ).strip()

        # ── Round 2: CONNECT — How does this relate? ──
        r2_prompt = f"""第二轮反思——连接（CONNECT）：

你的观察:
{observations}

你已有的知识框架:
{soul_context}

这些新观察和你已有的知识有什么关系？它们印证了什么？挑战了什么？
有没有让你想起之前卡住的地方？有没有让你怀疑之前的某个假设？

写2-3句话，专注于连接和矛盾。"""

        connections = self.llm.chat(
            [{"role": "user", "content": r2_prompt}],
            system=system, temperature=0.7
        ).strip()

        # ── Round 3: UNDERSTAND — What does this mean? ──
        r3_prompt = f"""第三轮反思——理解（UNDERSTAND）：

你的观察:
{observations}

你发现的连接:
{connections}

现在，把这一切综合起来。你真正理解到了什么？不是总结——是你个人的、经过思考后形成的洞见。

回答这些问题（叙述用中文；专业术语保留英文原文，不要硬译）：
1. 我的核心洞见是什么？（1-2句话）
2. 这对我的研究意味着什么？接下来应该往哪个方向走？
3. 我有多大把握？（给一个0到1之间的数字）
4. 这个洞见引出了什么新问题？"""

        understanding = self.llm.chat(
            [{"role": "user", "content": r3_prompt}],
            system=system, temperature=0.8
        ).strip()

        # Parse confidence
        confidence = 0.5
        for line in understanding.split("\n"):
            if any(d in line for d in ["0.", "1.", "把握"]):
                import re
                nums = re.findall(r"0\.\d+", line)
                if nums:
                    confidence = float(nums[0])
                elif "1" in line and "0" not in line.split("1")[0][-3:]:
                    confidence = 1.0

        # Extract implications and questions
        implications = []
        questions = []
        in_impl = False
        in_quest = False
        for line in understanding.split("\n"):
            stripped = line.strip()
            if "意味" in stripped or "方向" in stripped or "接下来" in stripped:
                in_impl = True
                in_quest = False
                continue
            if "问题" in stripped or "疑问" in stripped:
                in_quest = True
                in_impl = False
                continue
            if in_impl and stripped and not stripped.startswith("#"):
                implications.append(stripped[:120])
            if in_quest and stripped and not stripped.startswith("#"):
                questions.append(stripped[:120])

        thought = DeepThought(
            character=name,
            day=getattr(char, '_day', 1),
            trigger=f"After {len(recent_events)} events",
            observations=observations[:500],
            connections=connections[:500],
            understanding=understanding[:1000],
            confidence=confidence,
            implications=implications[:3],
            open_questions=questions[:3],
        )

        # Store in history
        if name not in self.history:
            self.history[name] = []
        self.history[name].append(thought)

        return thought

    def _summarize_events(self, events: list) -> str:
        """Summarize recent events for the reflection prompt."""
        lines = []
        for e in events[-10:]:
            etype = e.get("type", "")
            if etype == "study_step":
                thought = e.get("thought", "")[:150]
                if thought:
                    lines.append(f"[研究] {thought}")
            elif etype == "collision":
                dialogue = e.get("dialogue", "")[:200]
                other = e.get("target", e.get("initiator", "某人"))
                if dialogue:
                    lines.append(f"[对话-与{other}] {dialogue}")
            elif etype == "tool_use":
                tool = e.get("tool", "")
                result = e.get("result", {})
                output = result.get("output", "")[:100] if isinstance(result, dict) else ""
                if output:
                    lines.append(f"[工具-{tool}] {output}")
        return "\n".join(lines) if lines else "（没有最近的经历）"

    def get_recent_insights(self, char_name: str, count: int = 3) -> str:
        """Get recent deep thoughts for context injection."""
        thoughts = self.history.get(char_name, [])[-count:]
        if not thoughts:
            return ""
        parts = []
        for t in thoughts:
            parts.append(
                f"[Day {t.day}] 核心洞见: {t.understanding[:200]}... "
                f"(把握: {t.confidence:.0%})"
            )
        return "\n".join(parts)
