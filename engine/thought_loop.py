"""Inner Dialogue — thinking as a conversation with yourself.

Human thinking is not a monologue. It's a dialogue with an inner voice:
  "Wait, why is this term diverging?"
  "Maybe because the boundary condition is wrong..."
  "No, I checked that. What if I try a different expansion?"
  "That could work — let me write down the first two terms..."

Each turn is:
- Short (1-2 sentences, like real inner speech)
- Motivated (driven by a specific micro-goal: check, verify, question, propose)
- Responsive (builds on what was just thought)

This replaces the monolithic "study step" with a chain of small,
motivated turns that accumulate into genuine reasoning.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InnerTurn:
    """One turn in the inner dialogue."""
    role: str          # "self" or "critic" — the two voices
    content: str       # what was thought
    motivation: str    # why this thought (check, question, propose, verify, reject)


@dataclass
class InnerDialogue:
    """A character's active thinking process — a conversation with themselves."""

    turns: list = field(default_factory=list)
    topic: str = ""
    confidence: float = 0.0
    stuck_count: int = 0
    max_turns: int = 10

    def start(self, topic: str):
        self.topic = topic
        self.turns = []
        self.confidence = 0.0
        self.stuck_count = 0

    def add_turn(self, role: str, content: str, motivation: str):
        self.turns.append(InnerTurn(role=role, content=content, motivation=motivation))

    def can_continue(self) -> bool:
        """True if another turn may be generated (including the first)."""
        return bool(self.topic) and len(self.turns) < self.max_turns and self.stuck_count < 3

    def is_active(self) -> bool:
        """Alias for can_continue — empty dialogues must still enter the first turn."""
        return self.can_continue()

    def recent_context(self, count: int = 4) -> str:
        """Recent turns for the LLM to build on."""
        recent = self.turns[-count:]
        lines = []
        for t in recent:
            voice = "我" if t.role == "self" else "但"
            lines.append(f"{voice}: {t.content}")
        return "\n".join(lines)

    def summary(self) -> str:
        if not self.topic:
            return ""
        return f"在想: {self.topic[:60]} [{len(self.turns)}轮]"


# ═══════════════════════════════════════════════════════════════
# Inner Dialogue Driver
# ═══════════════════════════════════════════════════════════════

def next_inner_turn(llm, char, dialogue: InnerDialogue) -> InnerTurn | None:
    """Generate the next turn in the character's inner dialogue.

    The LLM takes on one of two voices:
    - "self": the character proposing, questioning, exploring
    - "critic": the inner skeptic evaluating, doubting, redirecting

    Returns None if the dialogue should end.
    """
    system = char.build_system_prompt()
    topic = dialogue.topic
    practice = (getattr(char, "_world_practice", "") or "").strip()
    from engine.skills import skill_phase_block

    skills = getattr(char, "_skills_text", None) or {}
    research = skill_phase_block(skills, phase="think") or (
        getattr(char, "_research_protocol", "") or ""
    ).strip()
    practice_line = f"\n本社区工作规范:\n{practice}\n" if practice else "\n"
    grain = f"\n{research}\n" if research else ""

    if not dialogue.turns:
        prompt = (
            f"你在研究: {topic}\n{practice_line}{grain}"
            f"你正在和自己对话。第一个念头要具体——"
            f"今天的工作单元是哪一小步（不是整个未解问题）？"
            f"2-4句。不要开场白。"
        )
        role = "self"
    else:
        context = dialogue.recent_context()
        last_role = dialogue.turns[-1].role
        next_role = "critic" if last_role == "self" else "self"
        role = next_role

        if role == "critic":
            prompt = (
                f"你在心里和自己对话。刚才你想:\n{context}\n{practice_line}{grain}"
                f"内心质疑者：哪里可能不对？缺什么义务（实验/推导）才能判定？"
                f"不要宣判整个方向死亡。2-3句。"
            )
        else:
            prompt = (
                f"你在心里和自己对话。质疑者说:\n{context}\n{practice_line}{grain}"
                f"回应并推进工作单元：接受则改一小步，反驳则补一步。"
                f"不要总结，不要给地平线问题下定论。2-4句。"
            )

    response = llm.chat([{"role": "user", "content": prompt}], system=system, temperature=0.5)

    motivation = "explore"
    if any(w in response for w in ["不对", "但", "等等", "wait", "不是", "缺"]):
        motivation = "question"
    elif any(w in response for w in ["试试", "试一下", "算一下", "验证", "estimate", "check"]):
        motivation = "propose"
    elif any(w in response for w in ["所以", "因此", "这意味着", "这说明", "hence"]):
        motivation = "conclude"

    return InnerTurn(role=role, content=response.strip()[:400], motivation=motivation)


def should_end_dialogue(dialogue: InnerDialogue) -> bool:
    """Check if the inner dialogue has run its course."""
    if len(dialogue.turns) >= dialogue.max_turns:
        return True
    if dialogue.stuck_count >= 3:
        return True
    # If last 2 turns are very short, the dialogue is winding down
    if len(dialogue.turns) >= 4:
        last_two = dialogue.turns[-2:]
        if all(len(t.content) < 30 for t in last_two):
            return True
    return False


def extract_insight(dialogue: InnerDialogue) -> str:
    """Extract the key insight from a completed inner dialogue."""
    if not dialogue.turns:
        return ""
    # The last "self" turn usually has the conclusion
    for t in reversed(dialogue.turns):
        if t.role == "self" and t.motivation in ("conclude", "propose"):
            return t.content
    return dialogue.turns[-1].content
