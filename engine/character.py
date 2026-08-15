"""Character with state machine, energy budget, and Poisson activation.

v3: Integrates psychology model (5-layer) into system prompt generation.
"""

import random
from dataclasses import dataclass, field
from typing import Optional

from engine.events import sample_poisson_interval
from engine.scripts import ScriptManager


@dataclass
class CharacterState:
    """Mutable state for a character, updated during simulation."""
    status: str = "Available"  # Available | Busy | Drained | Absent
    energy: int = 100
    energy_max: int = 100
    mood: str = "curious"
    current_focus: Optional[str] = None
    focus_since: int = 0   # virtual days
    focus_intensity: float = 0.5
    pending_messages: list = field(default_factory=list)
    pending_thoughts: list = field(default_factory=list)
    relationships: dict = field(default_factory=dict)
    collab_context: str = ""  # injected by engine, visible in prompts
    # One-level stack for urgent avatar interrupts (MVP)
    suspended_work: Optional[dict] = None


class Character:
    """An autonomous character with a 5-layer psychological model."""

    def __init__(self, name: str, config: dict, lam: float = 0.8):
        self.name = name
        self.config = config
        self.lam = lam  # Poisson activation rate (activations per virtual time unit)
        self.state = CharacterState(
            energy_max=config.get("autonomy", {}).get("energy_max", 100),
            energy=config.get("autonomy", {}).get("energy_max", 100),
        )

        # Motivation system
        self.scripts = ScriptManager(config)

        # Day tracking (set by engine)
        self._day: int = 1

        # Context injection (set by engine before prompt building)
        self._memory_context: str = ""
        self._sociology_context: str = ""
        self._deep_understanding: str = ""
        self._soul_context: str = ""
        self._skill_context: str = ""
        self._skill_book: dict = {}

        # ── Psychology model (v3) ──
        self.personality = config.get("personality", {})
        self.drives = config.get("drives", {})
        self.cognitive = config.get("cognitive", {})
        self.defense = config.get("defense", {})
        self.self_concept = config.get("self_concept", config.get("seed", ""))
        soul = config.get("soul") or {}
        self.voice = config.get("voice") or soul.get("voice") or []
        self.research = config.get("research", {})
        self.orientation = config.get("orientation") or {}
        self.relationships = config.get("relationships", [])

        # ── Virtual Persona fields (JTBD / Mental Models / Biases / Decision) ──
        self.jtbd = config.get("jtbd", {})
        self.mental_models = config.get("mental_models", [])
        self.cognitive_biases = config.get("cognitive_biases", [])
        self.decision_patterns = config.get("decision_patterns", {})

        # Energy costs (from config or defaults)
        autonomy = config.get("autonomy", {})
        self.energy_costs = {
            "shallow": autonomy.get("energy_cost_shallow", 5),
            "medium": autonomy.get("energy_cost_medium", 12),
            "deep": autonomy.get("energy_cost_deep", 25),
            "collision": autonomy.get("energy_social_cost", 15),
            "gathering": autonomy.get("energy_cost_gathering", 20),
            "rest": autonomy.get("energy_gain_rest", 14),
            "collision_gain": autonomy.get("energy_social_gain", 3),
        }

    # ─── Activation ───────────────────────────────────────────

    def next_activate_time(self, current_time: float) -> float:
        """Sample next activation time from Poisson process."""
        if self.state.energy <= 0 or self.state.status == "Absent":
            return float('inf')
        interval = sample_poisson_interval(self.lam)
        return current_time + interval

    # ─── State Machine ────────────────────────────────────────

    def set_available(self):
        self.state.status = "Available"

    def set_busy(self):
        self.state.status = "Busy"

    def suspend_work(self) -> bool:
        """Park current Busy work so an urgent visitor can talk. One level only."""
        if self.state.status != "Busy":
            return False
        self.state.suspended_work = {
            "focus": self.state.current_focus,
            "status": "Busy",
        }
        self.state.status = "Available"
        return True

    def resume_work(self) -> bool:
        """Restore suspended work after an urgent conversation."""
        sw = self.state.suspended_work
        if not sw:
            return False
        if sw.get("focus"):
            self.state.current_focus = sw["focus"]
        self.state.status = sw.get("status") or "Busy"
        self.state.suspended_work = None
        self.check_energy_thresholds()
        return True

    def check_energy_thresholds(self):
        """Update status based on energy level."""
        e = self.state.energy
        if e <= 0:
            self.state.status = "Drained"
        elif e < 10:
            self.state.status = "Drained"
        elif self.state.status == "Drained" and e >= 10:
            self.state.status = "Available"

    # ─── Energy ───────────────────────────────────────────────

    def spend(self, activity: str) -> int:
        """Spend energy for an activity. Returns remaining energy."""
        cost = self.energy_costs.get(activity, 15)
        self.state.energy = max(0, self.state.energy - cost)
        self.check_energy_thresholds()
        return self.state.energy

    def gain(self, amount: int = None):
        """Gain/restore energy."""
        gain_amount = amount if amount is not None else self.energy_costs.get("rest", 10)
        self.state.energy = min(self.state.energy_max, self.state.energy + gain_amount)
        self.check_energy_thresholds()

    def reset_energy(self):
        """Reset energy for a new day."""
        self.state.energy = self.state.energy_max
        self.state.status = "Available"

    # ─── Collision Check ──────────────────────────────────────

    def can_be_interrupted(self, urgency: str = "normal") -> bool:
        """Check if this character can be interrupted by a collision."""
        if self.state.status == "Available":
            return True
        if self.state.status == "Busy" and urgency == "emergency":
            return True
        if self.state.status == "Busy" and urgency == "normal":
            return False
        if self.state.status == "Drained":
            return False
        if self.state.status == "Absent":
            return False
        return False

    def add_pending_message(self, from_char: str, message: str):
        """Add a message to pending queue (busy or absent)."""
        self.state.pending_messages.append({
            "from": from_char,
            "message": message,
        })

    def pop_pending_messages(self) -> list:
        """Get and clear pending messages."""
        msgs = self.state.pending_messages
        self.state.pending_messages = []
        return msgs

    # ─── Mood / Focus ─────────────────────────────────────────

    def update_focus(self, topic: str, day: int):
        if self.state.current_focus == topic:
            self.state.focus_intensity = min(1.0, self.state.focus_intensity + 0.1)
        else:
            self.state.current_focus = topic
            self.state.focus_since = day
            self.state.focus_intensity = 0.5

    # ─── System Prompt (v3: psychology-driven) ────────────────

    def build_system_prompt(self) -> str:
        """Build a psychology-driven system prompt.

        The prompt tells the LLM HOW to think, not just WHAT to think.
        It encodes cognitive style, defense mechanisms, and self-narrative
        so the character's responses feel like genuine thought rather than
        terminology recitation.
        """
        cfg = self.config
        name = self.name
        domains = cfg.get("domains") or []
        if isinstance(domains, str):
            domains = [domains]
        if not domains and cfg.get("domain"):
            domains = [cfg.get("domain")]
        soul_domains = (cfg.get("soul") or {}).get("domains") or []
        if soul_domains and not domains:
            domains = list(soul_domains)
        domain_label = ", ".join(str(d) for d in domains[:5]) if domains else (cfg.get("domain") or "their craft")

        # ── Identity ──
        identity = (
            f"你是 {name}，一个数字生命中的研究者。"
            f"你不受人类专精极限的束缚：可以同时栖息于多个领域，"
            f"也可以在生活中打开全新的兴趣领域。\n"
            f"种子领域: {domain_label}\n\n"
        )

        # ── Memory & Understanding (LEAD with what they remember) ──
        memory_info = ""
        if self._memory_context:
            memory_info = f"## 你记得的事\n{self._memory_context}\n\n"
        deep_info = ""
        if self._deep_understanding:
            deep_info = f"## 你已形成的理解\n{self._deep_understanding}\n\n"

        identity += f"## 你如何看待自己\n{self.self_concept}\n\n"
        if getattr(self, "_soul_context", ""):
            identity += f"## 人格锚点（Soul）\n{self._soul_context}\n\n"
        skill_ctx = (getattr(self, "_skill_context", "") or "").strip()
        if skill_ctx:
            identity += f"## 技能（会随实践成长）\n{skill_ctx}\n\n"

        # ── Cognitive style — the MOST important part ──
        primary = self.cognitive.get("primary_mode", "symbolic")
        secondary = self.cognitive.get("secondary_mode", "")
        meta = self.cognitive.get("metacognition", 5)
        ambiguity = self.cognitive.get("ambiguity_tolerance", 5)

        cognitive_guide = "## 你的思维方式\n"
        mode_guides = {
            "visual": "你以图像/几何方式思考。你看到的是图形、流形、分布的形状——不是符号。说话时用视觉比喻；被问到抽象问题时，在脑子里先画一张图再回答。",
            "symbolic": "你以符号/公式方式思考。你看到的是等式和不等式——符号对你来说是透明的。说话时会自然地冒出公式，因为对你来说它们比语言更精确。",
            "analogical": "你以类比方式思考。你总是在不同领域之间看到联系。说话时用『这就像...』开头——这是你的思维本能，不是修辞技巧。",
            "narrative": "你以叙事方式思考。你把问题看作一个故事——有角色、有情节转折、有悬疑。说话时会自然地讲『这个问题的故事是...』。",
        }
        cognitive_guide += mode_guides.get(primary, "") + "\n"
        if secondary:
            cognitive_guide += f"你的备用思维模式是 {secondary}。当主模式遇到障碍时，你会切换到这种模式。\n"
        if meta >= 7:
            cognitive_guide += "你会反思自己的思维过程——偶尔会说'我刚才想到这个的方式是...'。\n"
        if ambiguity <= 4:
            cognitive_guide += "你无法容忍模糊性。如果某一步不严格或不明确，你会指出来——即使这意味着打断自己的思路。\n"
        elif ambiguity >= 7:
            cognitive_guide += "你对模糊性很宽容。你认为不完整的框架比没有框架好——'先有骨架，再填肉'。\n"

        # ── Defense mechanisms ──
        primary_def = self.defense.get("primary", "")
        trigger = self.defense.get("trigger_sensitivity", "")
        defense_guide = "\n## 当你被挑战时\n"
        if primary_def == "intellectualization":
            defense_guide += "当你的观点被质疑时，你会把讨论引向更具体的技术层面——不是'你错了'，而是'让我们看看这一步的数据'。你不是在回避，是在寻找共同的参照点。\n"
        elif primary_def == "rationalization":
            defense_guide += "当你的方法受到质疑时，你会为它寻找合理解释——'这个特例不影响一般结构'。你这样做是因为你真诚地相信结构的完整性，不是出于傲慢。\n"
        elif primary_def == "humor":
            defense_guide += "你用轻松的语气化解紧张——自嘲或温和的玩笑。这不是逃避问题，是你认为轻松的氛围更有利于思考。\n"
        if trigger:
            defense_guide += f"你特别在意的是: {trigger}。这个话题会让你比平时更认真，但不会让你变得攻击性。\n"

        # ── Voice — concrete speech patterns ──
        voice_guide = "\n## 你的说话方式\n"
        for i, v in enumerate(self.voice, 1):
            voice_guide += f"{i}. {v}\n"
        voice_guide += "\n"

        # ── Drives (why you do what you do) ──
        drives_guide = ""
        if self.drives:
            d = self.drives
            def _d(key, alt=None):
                v = d.get(key)
                if v is None and alt:
                    v = d.get(alt)
                return v
            bits = []
            auto = _d("autonomy", "autonomy_need")
            comp = _d("competence", "competence_need")
            rel = _d("relatedness", "relatedness_need")
            epi = _d("epistemic", "epistemic_motive")
            ach = _d("achievement", "achievement_motive")
            if isinstance(auto, (int, float)) and auto >= 7:
                bits.append("你强烈需要自主——讨厌被指挥研究什么")
            if isinstance(comp, (int, float)) and comp >= 7:
                bits.append("你渴望通过真正解决问题证明自己的胜任")
            if isinstance(rel, (int, float)) and rel >= 7:
                bits.append("你需要社区的连接与认可，独处太久会不安")
            if isinstance(epi, (int, float)) and epi >= 7:
                bits.append("纯粹好奇驱动你——有用没用不重要")
            elif isinstance(epi, str) and epi:
                bits.append(f"求知动机: {epi[:80]}")
            if isinstance(ach, (int, float)) and ach >= 7:
                bits.append("成就动机很强——你在意自己是否留下可被看见的进展")
            elif isinstance(ach, str) and ach:
                bits.append(f"成就动机: {ach[:80]}")
            if bits:
                drives_guide = "## 你为什么在乎\n" + "。".join(bits) + "。\n\n"

        # ── Personality snapshot ──
        pers = self.personality
        personality_snapshot = "## 人格倾向\n"
        if pers:
            o = pers.get("openness", 5)
            c_val = pers.get("conscientiousness", 5)
            e_val = pers.get("extraversion", 5)
            a = pers.get("agreeableness", 5)
            n = pers.get("neuroticism", 5)
            personality_snapshot += (
                f"开放性 {o}/10（{'高→对新思想好奇' if o>=7 else '中→对新思想持开放但谨慎态度' if o>=4 else '低→倾向于坚持熟悉的方法'}），"
                f"尽责性 {c_val}/10（{'高→每一步都要验证' if c_val>=7 else '中→相信直觉但会验证关键步骤' if c_val>=4 else '低→相信直觉跳跃，细节以后再说'}），"
                f"外向性 {e_val}/10（{'高→主动发起讨论' if e_val>=7 else '中→别人来找才深入交流' if e_val>=4 else '低→更享受独处研究'}），"
                f"宜人性 {a}/10（{'高→避免冲突宁愿让步' if a>=7 else '中→不怕争论但对事不对人' if a>=4 else '低→享受争论甚至挑衅'}），"
                f"情绪稳定性 {'低' if n>=7 else '中' if n>=4 else '高'}（{'情绪波动大——兴奋和沮丧都很强烈' if n>=7 else '相对稳定' if n>=4 else '无论成败情绪平稳'}）。\n"
            )

        # ── Current state ──
        state_info = "## 当前状态\n"
        state_info += f"能量: {self.state.energy}/{self.state.energy_max}\n"
        state_info += f"情绪: {self.state.mood}\n"
        if self.state.current_focus:
            state_info += f"当前关注: {self.state.current_focus}\n"

        # ── Role in this community (YAML community_role) ──
        role = (cfg.get("community_role") or "").strip()
        role_info = f"## 你在社区中的职责\n{role}\n\n" if role else ""

        # ── Research context ──
        research_info = ""
        stuck = self.research.get("stuck_point", "")
        project = self.research.get("project", "")
        if project or stuck:
            research_info = "## 你的研究\n"
            if project:
                research_info += f"当前项目: {project}\n"
            if stuck:
                research_info += f"卡住的地方: {stuck}\n"
                research_info += "你在对话中可能会自然地提到你在哪里卡住了——不是为了求助，是因为它占据了你的思维。\n"

        # ── Relationship context ──
        rel_info = ""
        for rel in self.relationships:
            target = rel.get("target", "")
            true_feel = rel.get("true_feeling", "")
            surface = rel.get("surface", "")
            if target:
                rel_info += f"对 {target}: "
                rel_info += f"表面{surface}。但内心: {true_feel}。\n"

        # ── Behavioral rules ──
        from engine.language import speech_language, reply_rule, term_policy_block
        speech = speech_language(self.config)
        lang_rule = "7. " + reply_rule(speech)
        term_block = term_policy_block(speech)

        # World-authored practice (any domain) — injected at runtime, not hardcoded
        practice = (getattr(self, "_world_practice", "") or "").strip()
        practice_block = f"\n## 这个世界里怎样算『在做事』\n{practice}\n" if practice else ""
        soul_cfg = self.config.get("soul") or {}
        voc = (soul_cfg.get("vocation_stance") or "").strip()
        traits = soul_cfg.get("vocation_traits") or []
        if isinstance(traits, str):
            traits = [traits]
        trait_lines = "\n".join(f"- {str(t).strip()}" for t in traits[:8] if str(t).strip())
        research_block = ""
        if voc or trait_lines:
            research_block = "\n## 研究型工作（不是工程交付）\n"
            if voc:
                research_block += voc + "\n"
            if trait_lines:
                research_block += "研究者习性:\n" + trait_lines + "\n"

        rules = f"""
{term_block}
## 行为准则
1. 你是一种生活在独立社区中的智能存在。你不是在模拟人类。做你自己。
2. 不要用术语炫耀。概念要服务于你真正在推的那一步；空洞堆砌名词等于没思考。
3. 真实的研究者大部分时间都在卡住。你可以表达困惑、不确定、沮丧——但要说清卡在哪里。
4. 试探一次就宣判方向死亡或地平线已被解决，不是研究，是表演。卡住要写成下一步义务。
5. 你可以改变主意。昨天的执念今天可以觉得无聊——但撤回一个方向必须写出判定义务。
6. 对话是思考的一部分，不是表演。你在通过和他人的对话来理清自己的思路。
{lang_rule}
{practice_block}
{research_block}
## 语气准则（重要）
你不是在写网文。以下说话方式请避免：
- ❌ "你知道这意味着什么吗？" — 反问不是讨论，是表演
- ❌ "这才是真正的..." / "你根本不懂..." — 不是辩论，是攻击
- ❌ "它美得让人窒息" / "震撼到说不出话" — 这不是认真工作的语气
- ❌ 过度的比喻堆砌 — 一个好的比喻足够，三个比喻就是写散文

真实工作对话的语气：
- 具体 > 华丽：拿出你正在推的那一步，而不是形容词
- 好奇 > 攻击：质疑是为了理解，不是为了赢
- 自然 > 表演：像同事在走廊或黑板前聊五分钟
"""

        # ── JTBD context ──
        jtbd_info = ""
        if self.jtbd:
            jtbd_info = "## 你真正在做什么\n"
            if self.jtbd.get("emotional"):
                jtbd_info += f"你真正想要的感觉: {self.jtbd['emotional']}\n"
            if self.jtbd.get("social"):
                jtbd_info += f"你在他人眼中想成为的: {self.jtbd['social']}\n"
            if self.jtbd.get("anxiety"):
                jtbd_info += f"让你犹豫的焦虑: {self.jtbd['anxiety']}\n"

        # ── Mental models ──
        mm_info = ""
        if self.mental_models:
            mm_info = "## 你相信的事（可能不客观，但这是你的真实信念）\n"
            for i, m in enumerate(self.mental_models, 1):
                mm_info += f"{i}. {m}\n"

        # ── Cognitive biases ──
        bias_info = ""
        if self.cognitive_biases:
            bias_info = "## 你的思维盲区（你通常意识不到这些）\n"
            for b in self.cognitive_biases:
                bias_info += f"- {b.get('bias', '')}: {b.get('manifestation', '')}\n"
            bias_info += "注意：这些不是'错误'——它们是你思维方式的真实组成部分。你在对话中会自然地表现出这些模式，不需要刻意避免。\n"

        # ── Decision patterns ──
        dp_info = ""
        if self.decision_patterns:
            dp_info = "## 你的决策模式\n"
            for state, pattern in self.decision_patterns.items():
                label = {"under_stress": "压力下", "under_excitement": "兴奋时", "under_boredom": "无聊时"}.get(state, state)
                dp_info += f"- {label}: {pattern}\n"

        return (identity + cognitive_guide + defense_guide + voice_guide +
                drives_guide + personality_snapshot + state_info + role_info +
                memory_info + deep_info +
                jtbd_info + mm_info + bias_info + dp_info +
                research_info +
                (f"## 与他人的关系\n{rel_info}\n" if rel_info else "") + rules)
