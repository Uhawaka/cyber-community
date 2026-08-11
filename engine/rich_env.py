"""Rich Environment — a world that pushes back.

Characters are energy beings, but their space isn't empty.
It has texture, accidents, constraints, and serendipity.

Design principle: the environment should PRODUCE stimuli,
not just receive them. Characters should discover things,
not just decide things.
"""

import random
from typing import Optional


class EnvironmentalStimulus:
    """Something the environment pushes to a character."""

    def __init__(self, source: str, content: str, urgency: str = "low"):
        self.source = source       # where it came from (node, event, other character)
        self.content = content     # what happened
        self.urgency = urgency     # low | medium | high


class RichEnvironment:
    """An environment that generates stimuli, not just stores state."""

    def __init__(self, base_env, characters: dict, sociology):
        self.env = base_env
        self.characters = characters
        self.sociology = sociology

        # Track what's happening
        self.recent_events: list[str] = []     # things that just happened
        self.ambient_state: dict = {            # sensory state of the space
            "energy_density": 0.5,              # how "crowded" the space feels
            "information_flow": 0.3,            # how much is happening
            "tension": 0.2,                     # unresolved conflicts in the air
        }

    def get_stimuli(self, char_name: str) -> list[EnvironmentalStimulus]:
        """Generate ambient stimuli for a character based on their location and context."""
        stimuli = []
        loc = self.env.get_location(char_name)
        if loc is None:
            return stimuli

        # 1. Echoes from the current node
        echoes = loc.echoes[-3:] if loc.echoes else []
        for e in echoes:
            if e["author"] != char_name:
                stimuli.append(EnvironmentalStimulus(
                    source=f"「{loc.name}」的回响",
                    content=f"{e['author']}曾在此: {e['content'][:60]}",
                    urgency="low"
                ))

        # 2. Social presence — who else is here?
        others = [o for o in loc.occupants if o != char_name]
        if others:
            stimuli.append(EnvironmentalStimulus(
                source=f"「{loc.name}」",
                content=f"{', '.join(others)}也在这里",
                urgency="medium" if random.random() < 0.3 else "low"
            ))

        # 3. Serendipity — random discoveries in the environment
        if random.random() < 0.15:
            discoveries = [
                "一个之前没注意到的角落——似乎有人在墙上留了一行公式",
                "空间里飘着一段未完成的证明，笔迹看不清是谁的",
                "注意到知识库的书架重新排列过了——有什么新东西被放进来了",
                "白板上有一段被擦到一半的推导——只剩最后两行还看得清",
                "空气中有一丝陌生的能量波动——有人在附近做了大规模的数值实验",
            ]
            stimuli.append(EnvironmentalStimulus(
                source="环境",
                content=random.choice(discoveries),
                urgency="low" if random.random() < 0.7 else "medium"
            ))

        # 4. Social signals — someone's activity affects the space
        if random.random() < 0.2:
            active = [n for n in self.characters if n != char_name]
            if active:
                other = random.choice(active)
                other_loc = self.env.get_location(other)
                if other_loc and other_loc.id != loc.id:
                    stimuli.append(EnvironmentalStimulus(
                        source="感知",
                        content=f"隔壁「{other_loc.name}」传来一阵能量波动——{other}似乎在忙什么",
                        urgency="low"
                    ))

        # 5. Resource awareness — workshop/computational constraints
        if loc.type == "workshop" and random.random() < 0.3:
            stimuli.append(EnvironmentalStimulus(
                source="计算工坊",
                content="计算资源目前占用67%——有个大任务正在跑",
                urgency="low"
            ))

        # 6. Time passing — ambient awareness of the day
        hour = random.uniform(0, 24)  # placeholder
        if random.random() < 0.1:
            time_cues = [
                "外面的能量场微微变暗——夜晚快到了",
                "空间里的信息流密度似乎在上升——是上午研究的高峰期",
            ]
            stimuli.append(EnvironmentalStimulus(
                source="时间感",
                content=random.choice(time_cues),
                urgency="low"
            ))

        return stimuli

    def record_event(self, event_desc: str):
        """Record something that just happened in the community."""
        self.recent_events.append(event_desc)
        if len(self.recent_events) > 20:
            self.recent_events = self.recent_events[-20:]

        # Update ambient state
        if "论文" in event_desc or "发表了" in event_desc:
            self.ambient_state["information_flow"] = min(1.0, self.ambient_state["information_flow"] + 0.1)
        if "争论" in event_desc or "质疑" in event_desc:
            self.ambient_state["tension"] = min(1.0, self.ambient_state["tension"] + 0.05)

    def get_ambient_context(self) -> str:
        """Get a sensory description of the current community state."""
        parts = []
        density = self.ambient_state["energy_density"]
        flow = self.ambient_state["information_flow"]
        tension = self.ambient_state["tension"]

        if density > 0.7:
            parts.append("空间里能量密度很高——今天大家都在活跃")
        elif density < 0.3:
            parts.append("空间很安静——大部分人都在自己的角落")
        if flow > 0.6:
            parts.append("信息流很快——有新东西不断涌现")
        if tension > 0.4:
            parts.append("空气中有一丝紧张的余韵——最近有过激烈的讨论")

        if self.recent_events:
            parts.append(f"最近的事: {self.recent_events[-1][:80]}")

        return "；".join(parts) if parts else ""
