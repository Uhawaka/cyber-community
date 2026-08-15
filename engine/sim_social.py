"""Collisions, gatherings, seminars, collaboration."""

from __future__ import annotations

import random

from engine.events import Event
from engine.interactions import run_collision, run_gathering, extract_soul_updates
from engine.needs import satisfy_needs


class SocialMixin:
    """Social interaction and collaboration handlers."""

    def _handle_collision(self, event: Event, verbose: bool):
        initiator = self.characters.get(event.actor)
        target = self.characters.get(event.target)
        if not initiator or not target:
            return

        topic = event.data.get("topic", "")
        if verbose:
            self._log(f"  💬 {initiator.name} ↔ {target.name}")

        # Run LLM-driven collision
        dialogue = run_collision(initiator, target, topic, self.llm)
        
        # Log the dialogue
        self.event_log.append({
            "time": self.clock,
            "type": "collision",
            "initiator": initiator.name,
            "target": target.name,
            "topic": topic,
            "dialogue": dialogue,
        })

        if verbose:
            for line in dialogue.split("\n")[:4]:
                self._log(f"      {line.strip()[:120]}")

        # ── Soul evolution: update both characters ──
        self._update_soul_from_collision(initiator.name, target.name, topic, dialogue)

        # ── Need satisfaction ──
        for name in [initiator.name, target.name]:
            state = self.needs.get(name)
            if state:
                satisfy_needs(state, "collision", 
                    {"dialogue_length": len(dialogue)})

        # ── Sociology: record interaction ──
        quality = "neutral"
        if len(dialogue) > 500:
            quality = "positive"
        if any(w in dialogue for w in ["不对", "你错了", "这不是", "胡说"]):
            quality = "negative"
        # Record social gift if meaningful interaction
        if len(dialogue) > 400:
            self.society.record_gift(initiator.name, target.name,
                f"深度对话", value=1.5)
            self.society.record_gift(target.name, initiator.name,
                f"深度对话", value=1.5)

        # ── Spread rumor if debate is intense ──
        if quality == "negative":
            self.society.spread_rumor(
                f"{initiator.name}和{target.name}刚刚激烈争论了{topic[:30]}",
                "observed", self.day)

        # ── Memory: record collision episode ──
        valence = "frustrating" if quality == "negative" else ("exciting" if len(dialogue) > 800 else "curious")
        self._record_memory(initiator.name, "collision",
            f"与{target.name}讨论了{topic[:40]}",
            detail=dialogue[:800],
            participants=[target.name],
            valence=valence,
            importance=0.5 + (0.1 if len(dialogue) > 600 else 0),
            tags=[topic[:30]])
        self._record_memory(target.name, "collision",
            f"{initiator.name}来找我聊了{topic[:40]}",
            detail=dialogue[:800],
            participants=[initiator.name],
            valence=valence,
            importance=0.5 + (0.1 if len(dialogue) > 600 else 0),
            tags=[topic[:30]])

        # ── Collaboration: detect shared interests after deep dialogue ──
        if len(dialogue) > 400:
            self._check_collaboration(initiator.name, target.name, topic, dialogue)


    def _handle_gathering_step(self, event: Event, verbose: bool):
        phase = event.data.get("phase", "call")
        topic = event.data.get("topic", "general discussion")

        if phase != "call":
            return

        if verbose:
            self._log(f"  📢 集会开始: {topic}")

        # Run multi-character gathering
        dialogue = run_gathering(self.characters, event.actor, topic, self.llm)

        self.event_log.append({
            "time": self.clock,
            "type": "gathering",
            "phase": phase,
            "actor": event.actor,
            "topic": topic,
            "dialogue": dialogue,
        })

        if verbose:
            for line in dialogue.split("\n")[:6]:
                self._log(f"      {line.strip()[:120]}")

        # Spend energy from all participants
        for name, char in self.characters.items():
            if char.state.energy > 10:
                char.spend("gathering")

        # ── Soul evolution: update all participants ──
        for name in self.characters:
            if name not in self.souls:
                continue
            try:
                updates = extract_soul_updates(name, "collision", 
                    f"集会话题: {topic}\n对话:\n{dialogue[:1500]}", self.llm)
            except Exception:
                continue
            if not updates:
                continue
            self.souls[name].apply_delta(updates, day=self.day)


    def _handle_weekly_seminar(self, event: Event, verbose: bool):
        """Weekly community seminar — one presents, others engage."""
        if verbose:
            self._log(f"\n{'='*50}")
            self._log(f"📢 每周研讨会 (Day {self.day})")
            self._log(f"{'='*50}")

        # Pick a presenter based on recent activity
        chars = list(self.characters.values())
        presenter = random.choice(chars)
        
        # Move everyone to commons
        for name in self.characters:
            self.environment.move_character(name, "commons")
        
        if verbose:
            self._log(f"  主讲: {presenter.name}")
            self._log(f"  地点: 中央大厅\n")

        # Presenter's opening — what they've been working on
        system_p = presenter.build_system_prompt()
        opening = self.llm.chat(
            [{"role": "user", "content": f"这是社区的每周研讨会。你来做主讲。用5分钟介绍你最近最重要的工作——一个具体的发现、一个卡住的问题、或者一个你正在推的方向。给出具体内容：公式、数据、推理步骤。不要泛泛而谈。"}],
            system=system_p, temperature=0.6
        )

        if verbose:
            self._log(f"  {presenter.name}: {opening[:200]}...\n")

        # Others respond in sequence
        dialogue = [f"{presenter.name} (主讲): {opening}"]
        context = f"{presenter.name}: {opening}"
        
        for char in chars:
            if char.name == presenter.name:
                continue
            system = char.build_system_prompt()
            response = self.llm.chat(
                [{"role": "user", "content": f"研讨会上，{presenter.name} 刚介绍了他的工作:\n{context}\n\n轮到你提问或评论。像一个真实的学术讨论——可以问一个尖锐的问题，可以指出一个可能的推广，可以质疑一个假设。推进讨论，不要只夸。"}],
                system=system, temperature=0.6
            )
            dialogue.append(f"{char.name}: {response}")
            context += f"\n{char.name}: {response}"
            if verbose:
                self._log(f"  {char.name}: {response[:150]}...\n")

        # Presenter responds to comments
        closing = self.llm.chat(
            [{"role": "user", "content": f"大家的评论:\n{context}\n\n回应最关键的质疑或建议。接受有道理的，解释被误解的。自然地结束。"}],
            system=system_p, temperature=0.6
        )
        dialogue.append(f"{presenter.name}: {closing}")

        # Log as event
        self.event_log.append({
            "time": self.clock, "type": "weekly_seminar",
            "presenter": presenter.name, "dialogue": "\n".join(dialogue),
        })

        # Schedule next seminar
        next_t = self.clock + 168  # 7 virtual days
        self.queue.push(Event(time=next_t, type="weekly_seminar"))

        # Leave echoes in commons
        self.environment.leave_echo(presenter.name, "commons", 
            f"研讨会主讲: {opening[:80]}")


    def _update_soul_from_collision(self, initiator_name: str, target_name: str, 
                                     topic: str, dialogue: str):
        """Extract soul changes from a collision and update both characters."""
        context = f"话题: {topic}\n对话:\n{dialogue[:1500]}"

        for name in [initiator_name, target_name]:
            soul = self.souls.get(name)
            if soul is None:
                continue
            try:
                updates = extract_soul_updates(name, "collision", context, self.llm)
            except Exception:
                continue

            if not updates:
                continue
            soul.apply_delta(updates, day=self.day)


    def _check_collaboration(self, a: str, b: str, topic: str, dialogue: str):
        """After a meaningful collision, check if characters should collaborate."""
        char_a = self.characters.get(a)
        char_b = self.characters.get(b)
        if not char_a or not char_b:
            return

        # Already collaborating?
        for p in self.collab.get_active():
            if a in p.participants and b in p.participants:
                if p.topic[:30] in topic or topic[:30] in p.topic:
                    p.advance(random.uniform(0.02, 0.05))
                    p.last_worked_day = self.day
                return

        # Deep enough dialogue → use LLM to check for genuine overlap
        if len(dialogue) < 400:
            return
        
        if random.random() < 0.35:
            try:
                # Ask LLM: are these two working on related things?
                prompt = f"""两个角色刚进行了一次深入的对话。判断他们是否在讨论相关的研究方向，从而应该协作。

角色A ({a}) 的研究焦点: {char_a.state.current_focus or "未知"}
角色B ({b}) 的研究焦点: {char_b.state.current_focus or "未知"}
对话主题: {topic}
对话摘要 (最后300字): {dialogue[-300:]}

只回答 YES 或 NO。他们是否在讨论有实质交叉的研究问题？"""
                response = self.llm.chat(
                    [{"role": "user", "content": prompt}],
                    system="你是一个研究协作判断器。只回答YES或NO。",
                    temperature=0.1
                )
                should_collab = "YES" in response.upper()
            except Exception:
                # Fallback to keyword matching
                should_collab = self.collab.detect_overlap(
                    char_a.state.current_focus or "",
                    char_b.state.current_focus or ""
                )
            
            if should_collab:
                project_topic = topic if len(topic) > 10 else f"{char_a.state.current_focus or a} × {char_b.state.current_focus or b}"
                project = self.collab.create(project_topic[:60], a, [a, b], self.day)
                self._log(f"\n  🤝 {a} 和 {b} 发现共同兴趣，发起协作: {project_topic[:50]}")
                self.event_log.append({
                    "time": self.clock, "type": "collaboration_start",
                    "participants": [a, b], "topic": project_topic,
                })
                char_a.state.mood = "excited"
                char_b.state.mood = "curious"


    def _check_solo_to_collab(self, char_name: str, thought):
        """After deep think, check if insight mentions others → collaboration signal."""
        char = self.characters.get(char_name)
        if not char:
            return
        
        # Check if insight mentions other characters by name
        insight_text = thought.understanding or ""
        mentioned = [n for n in self.characters if n != char_name and n in insight_text]
        
        if mentioned:
            # Strong signal — the character is thinking about someone else's work
            other = mentioned[0]
            if random.random() < 0.5:
                # They explicitly connect their work to another's
                my_topic = char.state.current_focus or ""
                their_focus = self.characters[other].state.current_focus or ""
                joint_topic = f"{my_topic[:25]} × {their_focus[:25]}"
                
                # Check if they already have a collab
                already = any(
                    char_name in p.participants and other in p.participants
                    for p in self.collab.get_active()
                )
                if not already:
                    self.collab.create(joint_topic, char_name, [char_name, other], self.day)
                    self._log(f"\n  🤝 {char_name} 在深度反思中注意到与 {other} 的联系，发起协作!")
                    self.event_log.append({
                        "time": self.clock, "type": "collaboration_start",
                        "participants": [char_name, other], "topic": joint_topic,
                    })
                    char.state.mood = "excited"
                    self.characters[other].state.mood = "curious"
                    return
        
        # Fallback: keyword-based candidate detection
        my_topic = char.state.current_focus or ""
        candidates = self.collab.find_collaboration_candidates(
            char_name, my_topic, self.characters
        )
        
        if candidates and random.random() < 0.2:
            other = random.choice(candidates)
            char.state.pending_thoughts.append(
                f"我注意到{other}的研究可能和我的工作有关——也许该找ta聊聊"
            )


    def _inject_collab_context(self, char_name: str):
        """Inject collaboration info into character's system prompt context."""
        char = self.characters.get(char_name)
        if not char:
            return
        ctx_parts = []
        
        my_projects = self.collab.get_my_projects(char_name)
        if my_projects:
            ctx_parts.append(my_projects)
        
        community = self.collab.get_community_context()
        if community:
            ctx_parts.append(community)
        
        if ctx_parts:
            char.state.collab_context = "\n\n".join(ctx_parts)

