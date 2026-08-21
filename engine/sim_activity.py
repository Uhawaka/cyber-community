"""Activation, spontaneous activity, study continue, idle thought."""

from __future__ import annotations

import random

from engine.events import Event
from engine.character import Character
from engine.day_rhythm import get_phase, get_phase_activity
from engine.needs import need_driven_activity, satisfy_needs
from engine.thought_loop import (
    InnerDialogue,
    next_inner_turn,
    extract_insight,
    should_end_dialogue,
)
from engine.interactions import decide_action, run_collision, run_study_step
from engine.culture import psych_action_bias, apply_weight_bias
from engine.inbox import (
    suggest_inbox_action,
    inbox_weight_bias,
    consume_messages_from,
)
from engine.work_queue import adopt_working_object, forced_decision
from engine.literature import SEARCH_TOOL_NAMES, search_is_enabled


class ActivityMixin:
    """Character activation and self-directed activity handlers."""

    def _run_inner_dialogue(
        self,
        char: Character,
        topic: str,
        max_turns: int | None = None,
        verbose: bool = False,
    ) -> InnerDialogue:
        """Shared study path for activate + spontaneous (first turn must run)."""
        dialogue = InnerDialogue()
        dialogue.start(topic)
        limit = max_turns if max_turns is not None else dialogue.max_turns
        while dialogue.can_continue() and len(dialogue.turns) < limit:
            if should_end_dialogue(dialogue) and dialogue.turns:
                break
            if not self._llm_budget_ok():
                break
            turn = next_inner_turn(self.llm, char, dialogue)
            if turn is None:
                break
            dialogue.add_turn(turn.role, turn.content, turn.motivation)
            self.event_log.append({
                "time": self.clock + len(dialogue.turns) * 0.1,
                "type": "inner_turn",
                "actor": char.name,
                "role": turn.role,
                "content": turn.content,
                "motivation": turn.motivation,
            })
        if verbose:
            self._log(f"  💬 {char.name} 内心对话 ({len(dialogue.turns)}轮)")
            for t in dialogue.turns[-3:]:
                prefix = "  我:" if t.role == "self" else "  但:"
                self._log(f"{prefix} {t.content[:100]}")
        return dialogue

    def _knowledge_decision(self, decision: dict) -> dict:
        """Search is opt-in. Without it, looking outward becomes study."""
        if search_is_enabled(
            getattr(self, "world_frame", {}),
            getattr(self, "config", None),
        ):
            return decision
        if decision.get("type") == "observe_world":
            return {
                "type": "study",
                "label": "📖 对着自己的问题继续",
                "topic": decision.get("topic", ""),
            }
        if decision.get("type") == "tool" and decision.get("tool") in SEARCH_TOOL_NAMES:
            return {
                "type": "study",
                "label": "📖 先把已知的推下去",
                "topic": decision.get("topic", ""),
            }
        return decision

    def _ground_public_decision(self, char, decision: dict) -> dict:
        """No working object → cannot socialize/gather as publication."""
        from engine.work_queue import public_topic

        kind = decision.get("type")
        if kind == "socialize" and decision.get("inbox_reply"):
            return decision
        if kind in ("socialize", "gather") and not public_topic(char, decision.get("topic", "")):
            return {
                "type": "study",
                "label": "📖 先有对象再开口",
                "topic": decision.get("topic", "") or "",
            }
        if kind in ("socialize", "gather"):
            decision = dict(decision)
            decision["topic"] = public_topic(char, decision.get("topic", ""))
        return decision

    def _handle_activate(self, event: Event, verbose: bool):
        char = self.characters.get(event.actor)
        if char is None:
            return

        # Inject memory + understanding context (+ inbox briefing)
        self._inject_context(char.name)

        if char.state.energy <= 0:
            self._log(f"  {char.name} 能量耗尽，跳过激活")
            # Rhythm / day_boundary will schedule the next beat — no Poisson chain
            char.reset_energy()
            return

        char.set_available()

        # SOP unfinished work beats inbox; inbox still beats broadcasting new work
        inbox = getattr(char, "_inbox", None) or {}
        inbox_decision = suggest_inbox_action(self, char.name, inbox)
        forced = forced_decision(char)
        if forced:
            decision = forced
            if verbose:
                self._log(
                    f"  [{char.name}] {decision['label']} (E={char.state.energy}) [sop]"
                )
        elif inbox_decision:
            decision = inbox_decision
            if verbose:
                self._log(
                    f"  [{char.name}] {decision['label']} (E={char.state.energy}) [inbox]"
                )
        else:
            # Use day rhythm, override with needs; nudge social if inbox warm
            phase = get_phase(self.clock)
            state = self.needs.get(char.name)
            if state:
                state.decay_all(0.5)  # decay since last activation
            psych_bias = psych_action_bias(char.personality, char.drives)
            for k, v in inbox_weight_bias(inbox, char).items():
                psych_bias[k] = psych_bias.get(k, 1.0) * v
            phase_decision = get_phase_activity(
                phase,
                char.scripts.routines if hasattr(char, "scripts") else None,
                weight_bias=psych_bias,
            )
            decision = need_driven_activity(state, phase_decision) if state else phase_decision
            decision["topic"] = char.state.current_focus or char.config.get("seed", "")

            if verbose:
                self._log(f"  [{char.name}] {decision['label']} (E={char.state.energy})")

        decision = self._ground_public_decision(char, self._knowledge_decision(decision))

        # Consume anon stimuli only when this action can react
        self._consume_anon_if_reactive(char.name, decision["type"])

        if decision["type"] == "observe_world":
            # Enclosed worlds have no window — fall back to study
            frame = getattr(self, "world_frame", {}) or {}
            if frame.get("permeability") == "enclosed":
                decision = {
                    "type": "study",
                    "label": "📖 窗关着，继续自己的研究",
                    "topic": decision.get("topic", ""),
                }
            else:
                char.spend("shallow")
                obs_event = Event(
                    time=self.clock,
                    type="observe_world",
                    actor=char.name,
                    data={
                        "query": decision.get("query") or "",
                        "query_type": decision.get("query_type") or "arxiv",
                        "topic": decision.get("topic") or "",
                    },
                )
                self._handle_observe_world(obs_event, verbose)
                return

        if decision["type"] == "rest":
            char.gain()
            # Also satisfy needs system's energy
            state = self.needs.get(char.name)
            if state:
                satisfy_needs(state, "rest", {"duration": 3})
            return

        if decision["type"] == "move":
            target_node = decision.get("node", "commons")
            if self.environment.move_character(char.name, target_node):
                char.spend("shallow")
                if verbose:
                    node = self.environment.nodes.get(target_node)
                    self._log(f"    🚶 → {node.name if node else target_node}")
            return

        if decision["type"] == "modify_env":
            char.spend("medium")
            self.queue.push(Event(
                time=self.clock + 0.3,
                type="modify_env",
                actor=char.name,
                data=decision
            ))
            return

        if decision["type"] == "entertain":
            char.spend("shallow")
            if verbose:
                self._log(f"    🎵 {char.name} 在放松...")
            if random.random() < 0.2:
                char.state.mood = random.choice(["curious", "playful", "inspired", "calm"])
            return

        if decision["type"] == "tool":
            tool_name = decision.get("tool", "")
            if tool_name and self.tool_registry:
                char.spend("medium")
                self.queue.push(Event(
                    time=self.clock + 0.2,
                    type="tool_use",
                    actor=char.name,
                    data={
                        "tool": tool_name,
                        "topic": decision.get("topic", ""),
                        "arxiv_id": decision.get("arxiv_id", ""),
                        "query": decision.get("query") or "",
                    },
                ))
                if verbose:
                    self._log(f"    🔧 准备使用工具: {tool_name}")
            return

        if decision["type"] == "socialize":
            # Prefer inbox-specified target, else random
            targets = [n for n in self.characters if n != char.name]
            preferred = decision.get("target")
            if preferred and preferred in self.characters and preferred != char.name:
                target_name = preferred
            elif targets:
                target_name = random.choice(targets)
            else:
                target_name = None

            if target_name:
                target = self.characters[target_name]
                if decision.get("inbox_reply"):
                    consume_messages_from(char, target_name)

                if target.can_be_interrupted("normal"):
                    # Immediate collision
                    char.spend("collision")
                    self.queue.push(Event(
                        time=self.clock + 0.1,
                        type="collision",
                        actor=char.name,
                        target=target_name,
                        data={"topic": decision.get("topic", "")}
                    ))
                    if verbose:
                        self._log(f"    → 找 {target_name} 聊天 (立即碰撞)")
                else:
                    # Leave a message — costs less energy since no actual interaction
                    char.spend("shallow")
                    target.add_pending_message(char.name, f"[{char.name} 想找你聊聊]")
                    if verbose:
                        self._log(f"    → 给 {target_name} 留言 (对方 {target.state.status})")
            return

        if decision["type"] == "gather":
            char.spend("gathering")
            # Simplified: just start a gathering event
            self.queue.push(Event(
                time=self.clock + 0.5,
                type="gathering_step",
                actor=char.name,
                data={"phase": "call", "topic": decision.get("topic", "general discussion")}
            ))
            return

        # study or observe — enter inner dialogue loop
        # Rhythm owns the next activate beat (no post-activate Poisson densify)
        char.spend("medium")
        char.set_busy()

        topic = decision.get("topic", char.state.current_focus or "研究方向")
        dialogue = self._run_inner_dialogue(char, topic, verbose=verbose)

        # Record the accumulated thinking as a study_step
        full_thought = "\n".join(f"[{t.role}] {t.content}" for t in dialogue.turns)
        self.event_log.append({
            "time": self.clock,
            "type": "study_step",
            "actor": char.name,
            "step": len(dialogue.turns),
            "topic": topic,
            "thought": full_thought,
        })

        # Update focus and project progress
        char.update_focus(topic, self.day)
        insight = extract_insight(dialogue)
        if insight:
            self._update_soul_from_study(char.name, topic, insight)
        adopt_working_object(char, insight or topic)

        project = char.scripts.get_active_project()
        if project:
            char.scripts.advance_project(random.uniform(0.02, 0.05))

        # Count for deep-think trigger even when soul extract is budget-skipped
        self._record_memory(
            char.name,
            "study",
            f"内心对话{len(dialogue.turns)}轮: {topic[:60]}",
            detail=full_thought[:300],
            valence="curious",
            importance=0.45,
            tags=[topic[:30]],
        )

        char.set_available()

        # Sometimes stay on the blackboard — continue cascade for depth
        if (
            dialogue.turns
            and char.state.energy > 35
            and self._llm_budget_ok()
            and random.random() < 0.4
        ):
            self.queue.push(Event(
                time=self.clock + 0.35,
                type="continue",
                actor=char.name,
                data={"decision": {"type": "study", "topic": topic}, "step": 1},
            ))
            char.set_busy()


    def _handle_continue(self, event: Event, verbose: bool):
        char = self.characters.get(event.actor)
        if char is None:
            return

        decision = event.data.get("decision", {})
        step = event.data.get("step", 1)

        char.spend("medium")
        self._execute_study_step(char, decision, step=step)

        trigger = self._check_trigger_strength(char, decision)
        if trigger == "continue" and char.state.energy > 15:
            self.queue.push(Event(
                time=self.clock + 0.3,
                type="continue",
                actor=char.name,
                data={"decision": decision, "step": step + 1}
            ))
        else:
            char.set_available()
            # Process pending messages
            pending = char.pop_pending_messages()
            if pending and verbose:
                # Log and process: messages become thoughts/pending focus
                for msg in pending:
                    char.state.pending_thoughts.append(f"来自 {msg['from']}: {msg['message'][:80]}")
                self._log(f"    {char.name} 收到 {len(pending)} 条留言 → 写入待思考")


    def _handle_spontaneous(self, event: Event, verbose: bool):
        """Unplanned activity — Poisson-driven, uses LLM decision."""
        char = self.characters.get(event.actor)
        if char is None or char.state.energy < 10:
            return

        self._inject_context(char.name)
        inbox = getattr(char, "_inbox", None) or {}
        decision = self._ground_public_decision(
            char,
            self._knowledge_decision(
                forced_decision(char)
                or suggest_inbox_action(self, char.name, inbox)
                or self._decide_action(char)
            ),
        )
        self._consume_anon_if_reactive(char.name, decision["type"])

        if verbose:
            tag = "inbox" if decision.get("inbox_reply") else "自发"
            self._log(f"  ✨ [{char.name}] {decision.get('label', 'spontaneous')} ({tag})")

        # Route to appropriate handler based on type
        if decision["type"] == "study":
            char.spend("medium")
            char.set_busy()
            topic = decision.get("topic", char.state.current_focus or "")
            dialogue = self._run_inner_dialogue(char, topic, max_turns=8, verbose=verbose)
            full_thought = "\n".join(f"[{t.role}] {t.content}" for t in dialogue.turns)
            self.event_log.append({"time": self.clock, "type": "study_step", "actor": char.name,
                "step": len(dialogue.turns), "topic": topic, "thought": full_thought})
            char.update_focus(topic, self.day)
            insight = extract_insight(dialogue)
            if insight:
                self._update_soul_from_study(char.name, topic, insight)
            adopt_working_object(char, insight or topic)
            self._record_memory(
                char.name, "study",
                f"自发研究{len(dialogue.turns)}轮: {topic[:60]}",
                detail=full_thought[:300],
                valence="curious",
                importance=0.4,
                tags=[topic[:30]],
            )
            char.set_available()
        elif decision["type"] == "socialize":
            targets = [n for n in self.characters if n != char.name]
            preferred = decision.get("target")
            if preferred and preferred in self.characters and preferred != char.name:
                target_name = preferred
            elif targets:
                target_name = random.choice(targets)
            else:
                target_name = None
            if target_name:
                target = self.characters[target_name]
                if decision.get("inbox_reply"):
                    consume_messages_from(char, target_name)
                if target.can_be_interrupted("normal"):
                    char.spend("collision")
                    from engine.work_queue import note_collision

                    note_collision(char)
                    note_collision(target)
                    dialogue = run_collision(char, target, decision.get("topic", ""), self.llm)
                    self.event_log.append({"time": self.clock, "type": "collision",
                        "initiator": char.name, "target": target_name, "dialogue": dialogue})
                    self._update_soul_from_collision(char.name, target_name, decision.get("topic", ""), dialogue)
                else:
                    char.spend("shallow")
                    target.add_pending_message(char.name, f"想找你聊聊")
        elif decision["type"] in ("entertain", "rest"):
            char.spend("shallow")
            state = self.needs.get(char.name)
            if state:
                satisfy_needs(state, decision["type"])
            if random.random() < 0.2:
                char.state.mood = random.choice(["curious", "playful", "calm"])
        elif decision["type"] == "modify_env":
            loc = self.environment.get_location(char.name)
            if loc:
                char.spend("shallow")
                from engine.work_queue import public_speech_ok, public_topic

                obj = public_topic(char)
                note = f"对着 {obj} 改了一下空间" if obj else ""
                if note and public_speech_ok(note, char):
                    self.environment.leave_echo(char.name, loc.id, note)
        elif decision["type"] == "move":
            nodes = list(self.environment.nodes.keys())
            target = random.choice(nodes)
            self.environment.move_character(char.name, target)
            char.spend("shallow")
        elif decision["type"] == "tool":
            tool_name = decision.get("tool", "")
            if tool_name and self.tool_registry:
                char.spend("medium")
                self.queue.push(Event(
                    time=self.clock + 0.2,
                    type="tool_use",
                    actor=char.name,
                    data={
                        "tool": tool_name,
                        "topic": decision.get("topic", ""),
                        "arxiv_id": decision.get("arxiv_id", ""),
                        "query": decision.get("query") or "",
                    },
                ))


    def _handle_idle_thought(self, event: Event, verbose: bool):
        """Low-frequency inner monologue — costs no energy, produces Soul content."""
        char = self.characters.get(event.actor)
        if char is None:
            return

        # Check if it's actually time for an idle thought (respect interval)
        if not char.scripts.should_idle_think(self.clock):
            # Reschedule
            next_t = self.clock + char.scripts.idle_interval * 0.5
            self.queue.push(Event(time=next_t, type="idle_thought", actor=char.name))
            return

        # Generate idle thought via lightweight LLM call
        soul = self.souls.get(char.name)
        idle_context = soul.get_recent_idle_thoughts(3) if soul else ""
        project = char.scripts.get_active_project()
        project_text = f"\n你正在推进的项目: {project.goal}" if project else ""

        thought = "脑海中飘过一些模糊的想法。"
        if self._llm_budget_ok() and not self.dry_run:
            system = char.build_system_prompt()
            prompt = f"""你正在独处。你最近在想什么？{project_text}

最近的杂念:
{idle_context if idle_context else '（还没有记录）'}

写一句话（20字以内），记录你此刻的想法。可以是一个念头、一个怀疑、一个发现、或一个情绪。"""
            try:
                thought = self.llm.chat(
                    [{"role": "user", "content": prompt}], system=system, temperature=0.9
                ).strip()[:100]
            except Exception:
                pass

        # Record
        char.scripts.record_idle_thought(thought, self.clock)
        if soul:
            soul.add_idle_thought(thought)

        if verbose:
            self._log(f"  💭 {char.name}: {thought}")

        # Idle thoughts can occasionally trigger focus shifts
        if random.random() < 0.15 and char.state.current_focus and project:
            # 15% chance idle thought modifies focus
            char.update_focus(project.goal, self.day)

        # Schedule next idle thought
        next_t = self.clock + char.scripts.idle_interval + random.uniform(-1, 2)
        if next_t > self.clock:
            self.queue.push(Event(time=next_t, type="idle_thought", actor=char.name))


    def _decide_action(self, char: Character) -> dict:
        """LLM-driven decision (fallback to weighted random on failure)."""
        # Inject sociology context for decision-making        
        tools_list = self.tool_registry.list_tools() if self.tool_registry else None
        try:
            return decide_action(char, self.llm, tools_list)
        except Exception:
            pass
        
        # Fallback: weighted random
        autonomy = char.config.get("autonomy", {})
        weights = {
            "study": autonomy.get("study_likelihood", 0.5),
            "socialize": autonomy.get("social_likelihood", 0.3),
            "rest": autonomy.get("rest_likelihood", 0.1),
            "gather": 0.05,
            "observe": 0.05 if char.config.get("_permeability") == "connected" else 0.0,
            "move": 0.03,
            "entertain": 0.03,
            "modify_env": 0.02,
        }
        
        # Add tool weights if tools are available
        if self.tool_registry:
            weights["tool_run_code"] = 0.03
            weights["tool_write_paper"] = 0.03
            weights["tool_search_arxiv"] = 0.04
            weights["tool_read_arxiv"] = 0.05
            weights["tool_search_web"] = 0.04

        e = char.state.energy
        if e < 20:
            weights["study"] *= 0.3
            weights["socialize"] *= 0.1
            weights["rest"] *= 3.0
        elif e < 40:
            weights["study"] *= 0.7
            weights["socialize"] *= 0.5

        # ── Script bias: apply multipliers from projects/routines/personality ──
        bias = char.scripts.get_decision_bias(self.clock, char.state.energy)
        for action, multiplier in bias.items():
            if action in weights:
                weights[action] *= max(0.1, min(3.0, multiplier))

        # ── Psychology bias: OCEAN + drives (mild) ──
        weights = apply_weight_bias(weights, psych_action_bias(char.personality, char.drives))

        choice = random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]
        topic = char.state.current_focus or char.config.get("seed", "")

        # Handle tool choices
        tool_map = {
            "tool_run_code": "run_code",
            "tool_write_paper": "write_paper", 
            "tool_search_arxiv": "search_arxiv",
            "tool_read_arxiv": "read_arxiv",
            "tool_search_web": "search_web",
        }
        if choice in tool_map:
            tool_name = tool_map[choice]
            return {"type": "tool", "label": f"🔧 使用工具: {tool_name}", "topic": topic, "tool": tool_name}

        labels = {
            "study": f"📖 研究: {topic[:40]}",
            "socialize": "💬 想找人聊天",
            "rest": "☕ 休息/发呆",
            "gather": "📢 想召集讨论",
            "observe": "🌐 观察人类世界",
            "move": "🚶 换个地方",
            "entertain": "🎵 放松一下",
            "modify_env": "🎨 改造周围的空间",
        }
        return {"type": choice, "label": labels.get(choice, choice), "topic": topic}


    def _check_trigger_strength(self, char: Character, decision: dict) -> str:
        """Check if the character should continue studying (placeholder)."""
        # In a real implementation, this would call the LLM
        # For now, weight-based random with energy gate
        e = char.state.energy
        if e < 15:
            return "stop"
        if e < 30:
            return random.choice(["continue", "pause"])

        # Higher chance of continuing for deep focus
        intensity = char.state.focus_intensity
        r = random.random()
        if r < intensity * 0.6:
            return "continue"
        elif r < 0.8:
            return "pause"
        return "stop"


    def _execute_study_step(self, char: Character, decision: dict, step: int = 1):
        """Execute a study step — LLM-driven deep research."""
        topic = decision.get("topic", char.state.current_focus or "")
        thought = run_study_step(char, topic, step, self.llm)
        self.event_log.append({
            "time": self.clock,
            "type": "study_step",
            "actor": char.name,
            "step": step,
            "topic": topic,
            "thought": thought,
        })
        # Update focus
        char.update_focus(topic, self.day)
        
        # ── Soul evolution: update knowledge ──
        self._update_soul_from_study(char.name, topic, thought)

        # ── Project progress: advance active project ──
        project = char.scripts.get_active_project()

        # ── Memory: record study episode ──
        valence = "exciting" if step > 2 else "curious"
        self._record_memory(char.name, "study", 
            f"研究了{step}步: {topic[:60]}",
            detail=thought[:300],
            valence=valence,
            importance=0.4 + (step * 0.05),
            tags=[topic[:30]])

        if project:
            # Each study step advances 2-5%
            advance = random.uniform(0.02, 0.05)
            reached_milestone = char.scripts.advance_project(advance)
            
            breakthrough_text = ""
            if reached_milestone:
                char.scripts.add_breakthrough(thought[:100])
                breakthrough_text = thought[:100]
            
            soul = self.souls.get(char.name)
            if soul:
                soul.update_project(project.goal, project.progress, breakthrough=breakthrough_text)

