"""Main simulation engine — DES event loop."""

import random
from typing import Optional
from pathlib import Path

from engine.events import Event, EventQueue
from engine.character import Character
from engine.llm import LLM
from engine.interactions import decide_action, run_collision, extract_soul_updates, run_gathering, run_tool_use
from engine.soul import SoulFile, DailyArchive
from engine.tools import ToolRegistry
from engine.sociology import CommunityEngine
from engine.deep_think import DeepThinkEngine
from engine.environment import Environment
from engine.thought_loop import InnerDialogue, next_inner_turn, extract_insight
from engine.needs import NeedsState, need_driven_activity, satisfy_needs
from engine.mission import MissionBoard
from engine.rich_env import RichEnvironment
from engine.day_rhythm import get_phase, get_phase_activity
from engine.observation import get_observation_queries
from engine.production import ProductionPipeline
from engine.memory import Memory, Episode
from engine.collaboration import CollaborationBoard, JointProject


class SimulationEngine:
    """Discrete Event Simulation engine for the community."""

    def __init__(self, config: dict, llm: LLM, memory=None, dry_run: bool = False):
        self.config = config
        self.llm = llm
        self.memory = memory
        self.dry_run = dry_run  # skip external API calls (for smoke tests)

        self.queue = EventQueue()
        self.clock = 0.0  # virtual time
        self.day = 1
        self.running = False

        # Create characters
        self.characters: dict[str, Character] = {}
        self.souls: dict[str, SoulFile] = {}
        self.archives: dict[str, DailyArchive] = {}
        
        permeability = config.get("domain", {}).get("permeability", "connected")
        # In dry_run, use temp dir to avoid contaminating persistent files
        if dry_run:
            import tempfile
            self._output_dir = Path(tempfile.mkdtemp(prefix="cc_dryrun_"))
        else:
            self._output_dir = Path("outputs") / config.get("name", "community").replace(" ", "-")
        output_dir = self._output_dir

        for char_cfg in config.get("characters", []):
            name = char_cfg["name"]
            lam = char_cfg.get("autonomy", {}).get("lam", random.uniform(0.5, 1.0))
            char_cfg["_permeability"] = permeability
            self.characters[name] = Character(name, char_cfg, lam=lam)
            
            # Initialize Soul file
            soul_path = output_dir / "souls" / f"{name}.yaml"
            soul = SoulFile(str(soul_path))
            soul.init_from_config(name, char_cfg)
            self.souls[name] = soul
            
            # Initialize daily archive
            archive_path = output_dir / "archives" / f"{name}.json"
            self.archives[name] = DailyArchive(str(archive_path))

        # Event log
        self.event_log: list[dict] = []

        # Memory system
        self.memories: dict[str, Memory] = {}
        for char_cfg in config.get("characters", []):
            name = char_cfg["name"]
            mem_path = output_dir / "memory" / f"{name}.json"
            mem = Memory(str(mem_path))
            # Seed backstory on first run (check for backstory episodes, not just any episodes)
            has_backstory = any(e.type == "backstory" for e in mem.episodes)
            if not has_backstory:
                mem.seed_backstory(char_cfg)
            self.memories[name] = mem

        # Tools
        tool_configs = config.get("tools", [])
        self.tool_registry = ToolRegistry(tool_configs, output_dir, llm) if tool_configs else None

        # Sociology
        self.society = CommunityEngine(self.characters)

        # Deep thinking
        self.deep_think = DeepThinkEngine(llm)
        self._event_counts: dict[str, dict] = {}  # per-char counters
        self._last_deep_think: dict[str, float] = {}

        # Inner dialogues — active thinking per character
        self._dialogues: dict[str, InnerDialogue] = {}

        # Environment
        env_path = output_dir / "environment.json"
        self.environment = Environment(str(env_path))

        # Rich environment — generates stimuli
        self.rich_env = RichEnvironment(self.environment, self.characters, self.society)

        # Mission board
        self.missions = MissionBoard(self.characters)

        # Needs system
        self.needs: dict[str, NeedsState] = {}
        for name in self.characters:
            self.needs[name] = NeedsState()

        # Production pipeline
        prod_path = output_dir / "production.json"
        self.production = ProductionPipeline(str(prod_path), llm)

        # Collaboration — characters discover shared interests organically
        self.collab = CollaborationBoard()

        # Search dedup cache — avoid redundant arXiv calls
        self._search_history: dict[str, set] = {}  # day → {queries done}

        for name in self.characters:
            self._event_counts[name] = {"study": 0, "collision": 0, "tool": 0}
            self._last_deep_think[name] = 0.0

    # ─── Initialization ───────────────────────────────────────

    def bootstrap(self):
        """Schedule day rhythm + Poisson for spontaneous activities."""
        for char in self.characters.values():
            # Rhythm: structured day
            self.queue.push(Event(time=2.0, type="activate", actor=char.name))
            self.queue.push(Event(time=7.0, type="activate", actor=char.name))
            self.queue.push(Event(time=10.0, type="activate", actor=char.name))
            self.queue.push(Event(time=14.0, type="activate", actor=char.name))
            self.queue.push(Event(time=18.0, type="activate", actor=char.name))
            # Poisson: spontaneous between rhythm beats
            self.queue.push(Event(time=random.uniform(0, 24.0), type="spontaneous", actor=char.name))
            self.queue.push(Event(time=random.uniform(0, 24.0), type="spontaneous", actor=char.name))
            # Observations and idle thoughts — skip in dry_run (no external API)
            if not self.dry_run:
                self.queue.push(Event(time=random.uniform(4.0, 8.0), type="observe_world", actor=char.name))
                self.queue.push(Event(time=random.uniform(3.0, 6.0), type="idle_thought", actor=char.name))

        self.queue.push(Event(time=24.0, type="day_boundary"))
        self.queue.push(Event(time=72.0, type="weekly_seminar"))

    # ─── Main Loop ────────────────────────────────────────────

    def run(self, max_days: int = 1, verbose: bool = True):
        """Run simulation for max_days virtual days."""
        self.running = True
        self.bootstrap()

        max_time = max_days * 24.0

        while self.running and self.queue:
            event = self.queue.pop()
            if event is None or event.time > max_time:
                break

            self.clock = event.time
            self._dispatch(event, verbose)

            if not self.queue:
                self._log("事件队列为空，模拟结束")
                break

        self.running = False
        if verbose:
            self._log(f"模拟结束: Day {self.day}, t={self.clock:.1f}")

    # ─── Event Dispatch ───────────────────────────────────────

    def _dispatch(self, event: Event, verbose: bool):
        handler = getattr(self, f"_handle_{event.type}", None)
        if handler:
            handler(event, verbose)
        else:
            if verbose:
                self._log(f"⚠ 未知事件类型: {event.type}")

    # ─── activate ─────────────────────────────────────────────

    def _handle_activate(self, event: Event, verbose: bool):
        char = self.characters.get(event.actor)
        if char is None:
            return

        # Inject memory + understanding context
        self._inject_context(char.name)

        if char.state.energy <= 0:
            self._log(f"  {char.name} 能量耗尽，跳过激活")
            # Still schedule next activation for tomorrow
            char.reset_energy()
            next_t = char.next_activate_time(self.clock)
            if next_t < float('inf'):
                self.queue.push(Event(time=next_t, type="activate", actor=char.name))
            return

        char.set_available()

        # Use day rhythm, override with needs
        phase = get_phase(self.clock)
        state = self.needs.get(char.name)
        if state:
            state.decay_all(0.5)  # decay since last activation
        phase_decision = get_phase_activity(phase, char.scripts.routines if hasattr(char, 'scripts') else None)
        decision = need_driven_activity(state, phase_decision) if state else phase_decision
        decision["topic"] = char.state.current_focus or char.config.get("seed", "")

        if verbose:
            self._log(f"  [{char.name}] {decision['label']} (E={char.state.energy})")

        if decision["type"] == "observe_world":
            # Directly trigger observation
            char.spend("shallow")
            obs_event = Event(time=self.clock, type="observe_world", actor=char.name)
            self._handle_observe_world(obs_event, verbose)
            next_t = char.next_activate_time(self.clock)
            if next_t < float('inf'):
                self.queue.push(Event(time=next_t, type="activate", actor=char.name))
            return

        if decision["type"] == "rest":
            char.gain()
            # Also satisfy needs system's energy
            state = self.needs.get(char.name)
            if state:
                satisfy_needs(state, "rest", {"duration": 3})
            next_t = char.next_activate_time(self.clock)
            if next_t < float('inf'):
                self.queue.push(Event(time=next_t, type="activate", actor=char.name))
            return

        if decision["type"] == "move":
            target_node = decision.get("node", "commons")
            if self.environment.move_character(char.name, target_node):
                char.spend("shallow")
                if verbose:
                    node = self.environment.nodes.get(target_node)
                    self._log(f"    🚶 → {node.name if node else target_node}")
            next_t = char.next_activate_time(self.clock)
            if next_t < float('inf'):
                self.queue.push(Event(time=next_t, type="activate", actor=char.name))
            return

        if decision["type"] == "modify_env":
            char.spend("medium")
            self.queue.push(Event(
                time=self.clock + 0.3,
                type="modify_env",
                actor=char.name,
                data=decision
            ))
            next_t = char.next_activate_time(self.clock)
            if next_t < float('inf'):
                self.queue.push(Event(time=next_t, type="activate", actor=char.name))
            return

        if decision["type"] == "entertain":
            char.spend("shallow")
            if verbose:
                self._log(f"    🎵 {char.name} 在放松...")
            if random.random() < 0.2:
                char.state.mood = random.choice(["curious", "playful", "inspired", "calm"])
            next_t = char.next_activate_time(self.clock)
            if next_t < float('inf'):
                self.queue.push(Event(time=next_t, type="activate", actor=char.name))
            return

        if decision["type"] == "tool":
            tool_name = decision.get("tool", "")
            if tool_name and self.tool_registry:
                char.spend("medium")
                self.queue.push(Event(
                    time=self.clock + 0.2,
                    type="tool_use",
                    actor=char.name,
                    data={"tool": tool_name, "topic": decision.get("topic", "")}
                ))
                if verbose:
                    self._log(f"    🔧 准备使用工具: {tool_name}")
                next_t = char.next_activate_time(self.clock)
                if next_t < float('inf'):
                    self.queue.push(Event(time=next_t, type="activate", actor=char.name))
            return

        if decision["type"] == "socialize":
            # Pick a target
            targets = [n for n in self.characters if n != char.name]
            if targets:
                target_name = random.choice(targets)
                target = self.characters[target_name]

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

            # Schedule next activation
            next_t = char.next_activate_time(self.clock)
            if next_t < float('inf'):
                self.queue.push(Event(time=next_t, type="activate", actor=char.name))
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
            next_t = char.next_activate_time(self.clock)
            if next_t < float('inf'):
                self.queue.push(Event(time=next_t, type="activate", actor=char.name))
            return

        # study or observe — enter inner dialogue loop
        char.spend("medium")
        char.set_busy()

        topic = decision.get("topic", char.state.current_focus or "研究方向")
        dialogue = InnerDialogue()
        dialogue.start(topic)

        # Run the inner dialogue — multiple short turns
        turn_count = 0
        while dialogue.is_active() and turn_count < dialogue.max_turns:
            turn = next_inner_turn(self.llm, char, dialogue)
            if turn is None:
                break
            dialogue.add_turn(turn.role, turn.content, turn.motivation)
            turn_count += 1

            # Log each turn
            self.event_log.append({
                "time": self.clock + turn_count * 0.1,
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

        project = char.scripts.get_active_project()
        if project:
            char.scripts.advance_project(random.uniform(0.02, 0.05))

        char.set_available()

        # Schedule next activation
        next_t = char.next_activate_time(self.clock)
        if next_t < float('inf'):
            self.queue.push(Event(time=next_t, type="activate", actor=char.name))

    # ─── continue ─────────────────────────────────────────────

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

    # ─── collision ────────────────────────────────────────────

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
            detail=dialogue[:300],
            participants=[target.name],
            valence=valence,
            importance=0.5 + (0.1 if len(dialogue) > 600 else 0),
            tags=[topic[:30]])
        self._record_memory(target.name, "collision",
            f"{initiator.name}来找我聊了{topic[:40]}",
            detail=dialogue[:300],
            participants=[initiator.name],
            valence=valence,
            importance=0.5 + (0.1 if len(dialogue) > 600 else 0),
            tags=[topic[:30]])

        # ── Collaboration: detect shared interests after deep dialogue ──
        if len(dialogue) > 400:
            self._check_collaboration(initiator.name, target.name, topic, dialogue)

    # ─── gathering_step ───────────────────────────────────────

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
            soul = self.souls[name]
            for rel in updates.get("relationship_updates", []):
                target = rel.get("target", "")
                bond = rel.get("new_bond", "")
                note = rel.get("history_note", "")
                if target and bond:
                    soul.update_relationship(target, bond, note)
            moment = updates.get("witnessed_moment", "")
            if moment:
                soul.add_witnessed_moment(moment)

    # ─── modify_env ───────────────────────────────────────────

    def _handle_modify_env(self, event: Event, verbose: bool):
        char = self.characters.get(event.actor)
        if char is None:
            return

        action = event.data.get("modify_action", "leave_echo")
        node_id = event.data.get("node", "")
        content = event.data.get("content", "")

        loc = self.environment.get_location(char.name)
        if loc is None:
            return

        target_node = node_id if node_id else loc.id

        if action == "leave_echo":
            if content:
                self.environment.leave_echo(char.name, target_node, content)
                if verbose:
                    self._log(f"    📝 {char.name} 在「{loc.name}」留下回响")
        elif action == "deposit":
            if content:
                self.environment.deposit(char.name, target_node, content)
                if verbose:
                    self._log(f"    📚 {char.name} 向知识库存入内容")
        elif action == "modify_aesthetics":
            new_aes = event.data.get("aesthetics", "")
            self.environment.modify_node(char.name, target_node, new_aesthetics=new_aes)
            if verbose:
                self._log(f"    🎨 {char.name} 改变了「{loc.name}」的面貌")

    # ─── weekly_seminar ───────────────────────────────────────

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

    # ─── observe_world ────────────────────────────────────────

    def _handle_spontaneous(self, event: Event, verbose: bool):
        """Unplanned activity — Poisson-driven, uses LLM decision."""
        char = self.characters.get(event.actor)
        if char is None or char.state.energy < 10:
            return

        self._inject_context(char.name)
        # Use the old LLM-based decision for spontaneity
        decision = self._decide_action(char)

        if verbose:
            self._log(f"  ✨ [{char.name}] {decision.get('label', 'spontaneous')} (自发)")

        # Route to appropriate handler based on type
        if decision["type"] == "study":
            char.spend("medium")
            char.set_busy()
            topic = decision.get("topic", char.state.current_focus or "")
            dialogue = InnerDialogue()
            dialogue.start(topic)
            for _ in range(min(dialogue.max_turns, 4)):
                turn = next_inner_turn(self.llm, char, dialogue)
                if turn is None:
                    break
                dialogue.add_turn(turn.role, turn.content, turn.motivation)
            full_thought = "\n".join(f"[{t.role}] {t.content}" for t in dialogue.turns)
            self.event_log.append({"time": self.clock, "type": "study_step", "actor": char.name,
                "step": len(dialogue.turns), "topic": topic, "thought": full_thought})
            char.update_focus(topic, self.day)
            insight = extract_insight(dialogue)
            if insight:
                self._update_soul_from_study(char.name, topic, insight)
            char.set_available()
        elif decision["type"] == "socialize":
            targets = [n for n in self.characters if n != char.name]
            if targets:
                target_name = random.choice(targets)
                target = self.characters[target_name]
                if target.can_be_interrupted("normal"):
                    char.spend("collision")
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
                self.environment.leave_echo(char.name, loc.id, f"随手改动了一下空间")
        elif decision["type"] == "move":
            nodes = list(self.environment.nodes.keys())
            target = random.choice(nodes)
            self.environment.move_character(char.name, target)
            char.spend("shallow")

    def _handle_observe_world(self, event: Event, verbose: bool):
        """Character looks at the human world — arxiv, news, discoveries."""
        char = self.characters.get(event.actor)
        if char is None:
            return

        if self.dry_run:
            if verbose:
                self._log(f"  🔭 {char.name} 观察人类世界 (dry_run — 跳过)")
            return

        # Get relevant queries (now returns (type, query) tuples)
        queries = get_observation_queries(char.research, char.config.get("domain", ""))
        if not queries:
            queries = [("arxiv", "mathematics recent")]

        # Dedup: skip queries already done today
        day_key = str(self.day)
        done_today = self._search_history.setdefault(day_key, set())
        fresh_queries = [(t, q) for t, q in queries if q not in done_today]
        if not fresh_queries:
            if verbose:
                self._log(f"  🔭 {char.name} 今日搜索已完成")
            next_t = self.clock + random.uniform(8, 16)
            self.queue.push(Event(time=next_t, type="observe_world", actor=char.name))
            return

        query_type, query = random.choice(fresh_queries)
        done_today.add(query)

        if verbose:
            icon = "🌐" if query_type == "web" else "📡"
            self._log(f"  {icon} {char.name} 观察人类世界: {query}")

        # Try search (arxiv or web)
        try:
            if self.tool_registry:
                tool_name = "search_web" if query_type == "web" else "search_arxiv"
                result = self.tool_registry.execute(tool_name, char.name,
                    {"query": query, "topic": query})
                if result.success:
                    source = "web" if query_type == "web" else "arxiv"
                    self.production.record_observation(source, result.output[:500], char.name)
                    
                    # Mission evaluation — did this help the character's goal?
                    mission = self.missions.process_observation(char.name, result.output)
                    if mission and mission.is_complete():
                        if verbose:
                            self._log(f"    🎯 任务完成: {mission.question[:60]}！")
                        char.state.mood = "excited"
                        char.gain(amount=10)
                        state = self.needs.get(char.name)
                        if state:
                            satisfy_needs(state, "mission_complete")
                        self.rich_env.record_event(f"{char.name} 完成了一个观察任务")
                    elif mission and mission.progress > 0:
                        if verbose:
                            self._log(f"    📊 任务进度 {mission.progress:.0%}: {mission.question[:40]}")
                        if mission.progress > 0.5:
                            char.state.mood = "curious"

                    if verbose:
                        preview = result.output[:120].replace("\n", " ")
                        self._log(f"    📡 {preview}")
                    
                    # If interesting results found, bias toward social discussion
                    if "找到" in result.output and random.random() < 0.4:
                        char.state.pending_thoughts.append(
                            f"arXiv上发现有趣的东西: {result.output[:100]}")
                        # Increase social probability for next decision
                        char.state.mood = "curious"
                elif verbose:
                    self._log(f"    ⚠ 搜索无结果")
        except Exception:
            pass

        # Schedule next observation
        next_t = self.clock + random.uniform(8, 16)
        self.queue.push(Event(time=next_t, type="observe_world", actor=char.name))

    # ─── idle_thought ──────────────────────────────────────────

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

        system = char.build_system_prompt()
        prompt = f"""你正在独处。你最近在想什么？{project_text}

最近的杂念:
{idle_context if idle_context else '（还没有记录）'}

写一句话（20字以内），记录你此刻的想法。可以是一个念头、一个怀疑、一个发现、或一个情绪。"""

        try:
            thought = self.llm.chat([{"role": "user", "content": prompt}], system=system, temperature=0.9)
            thought = thought.strip()[:100]
        except Exception:
            thought = "脑海中飘过一些模糊的想法。"

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

    # ─── external ─────────────────────────────────────────────

    def _handle_external(self, event: Event, verbose: bool):
        if verbose:
            self._log(f"  📡 外部事件: {event.data.get('description', '')}")

    # ─── tool_use ─────────────────────────────────────────────

    def _handle_tool_use(self, event: Event, verbose: bool):
        char = self.characters.get(event.actor)
        if char is None or self.tool_registry is None:
            return

        if self.dry_run:
            if verbose:
                self._log(f"  🔧 {char.name} 使用工具 (dry_run — 跳过)")
            return

        tool_name = event.data.get("tool", "")
        topic = event.data.get("topic", char.state.current_focus or "")

        if verbose:
            self._log(f"  🔧 {char.name} 使用工具: {tool_name}")

        # Step 1: LLM generates tool parameters
        try:
            params = run_tool_use(char, tool_name, topic, self.llm)
        except Exception as e:
            self._log(f"    ⚠ 工具参数生成失败: {e}")
            return

        if params.get("error"):
            self._log(f"    ⚠ {params['error']}")
            return

        # Step 2: Execute tool
        result = self.tool_registry.execute(tool_name, char.name, params)
        
        # Step 3: Log and display
        self.event_log.append({
            "time": self.clock,
            "type": "tool_use",
            "actor": char.name,
            "tool": tool_name,
            "topic": topic,
            "params": params,
            "result": result.to_dict(),
        })

        if verbose:
            output_preview = result.output[:200].replace("\n", " ")
            status = "✓" if result.success else "✗"
            self._log(f"    {status} {output_preview}")
            if result.artifact_path:
                self._log(f"    📁 制品: {result.artifact_path}")

        # Step 4: Update soul
        soul = self.souls.get(char.name)
        if soul:
            if result.success:
                soul.add_knowledge("gained", f"[{tool_name}] {result.output[:100]}")
                soul.add_witnessed_moment(f"使用{tool_name}获得发现")
            else:
                soul.add_knowledge("question", f"[{tool_name}失败] {result.output[:100]}")

        # ── Memory: record tool use episode ──
        self._record_memory(char.name, "tool_use",
            f"使用了{tool_name}: {result.output[:80]}",
            detail=result.output[:200],
            valence="exciting" if result.success else "frustrating",
            importance=0.5 if result.success else 0.3,
            tags=[tool_name, topic[:30]])

        # ── Production: record paper artifacts ──
        if tool_name == "write_paper" and result.success:
            title = params.get("title", "无标题")
            content = params.get("content", "")
            self.production._current_day = self.day
            self.production.create_artifact(
                "paper", title, content, [char.name], confidence=0.7)

            # Community board
            self.society.spread_rumor(
                f"{char.name}发表了《{title[:40]}》", char.name, self.day)
            self.society.boost_status(char.name, 8)

            # ── Environment: announce in commons ──
            self.environment.leave_echo(char.name, "commons",
                f"发表了论文: {title[:60]}")
            self.environment.deposit(char.name, "archive", 
                f"[论文] {title}: {content[:200]}")

    # ─── day_boundary ─────────────────────────────────────────

    def _handle_day_boundary(self, event: Event, verbose: bool):
        completed_day = self.day
        self.day += 1
        if verbose:
            self._log(f"\n{'='*50}")
            self._log(f"🌅 Day {self.day} 开始 (Day {completed_day} 结束)")
            self._log(f"{'='*50}")

        # Generate daily summaries for each character
        today_events = [e for e in self.event_log 
                       if self.clock - 24 <= e["time"] <= self.clock]
        
        for name, char in self.characters.items():
            char_events = [e for e in today_events if e.get("actor") == name]
            if char_events:
                summary = self._generate_day_summary(name, char, char_events)
                self.archives[name].add_day_summary(completed_day, summary, char_events)
                if verbose:
                    self._log(f"  📝 {name}: {summary[:80]}...")
            
            # Reset energy
            char.reset_energy()
            char._day = self.day

        # Schedule next day boundary
        self.queue.push(Event(time=self.clock + 24.0, type="day_boundary"))

        # Save environment
        self.environment.save()

        # Schedule rhythm-based activations for the new day
        # Each character gets 4-6 activations spread across the day
        for char in self.characters.values():
            # Morning deep work (t+2, t+4, t+6)
            self.queue.push(Event(time=self.clock + 2.0, type="activate", actor=char.name))
            # Late morning check (t+7)
            self.queue.push(Event(time=self.clock + 7.0, type="activate", actor=char.name))
            # Midday social (t+10)
            self.queue.push(Event(time=self.clock + 10.0, type="activate", actor=char.name))
            # Afternoon work (t+14)
            self.queue.push(Event(time=self.clock + 14.0, type="activate", actor=char.name))
            # Evening reflection (t+18)
            self.queue.push(Event(time=self.clock + 18.0, type="activate", actor=char.name))
            # Night wind-down (t+22)
            if random.random() < 0.5:
                self.queue.push(Event(time=self.clock + 22.0, type="activate", actor=char.name))
            # Poisson: 2-3 spontaneous events scattered through the day
            for _ in range(random.randint(2, 3)):
                self.queue.push(Event(time=self.clock + random.uniform(1, 23), 
                                       type="spontaneous", actor=char.name))

    def _generate_day_summary(self, name: str, char: Character, events: list) -> str:
        """Generate a daily summary for a character using LLM."""
        study_steps = [e for e in events if e["type"] == "study_step"]
        collisions = [e for e in events if e["type"] == "collision" and 
                     (e.get("actor") == name or e.get("target") == name or e.get("initiator") == name)]
        tool_uses = [e for e in events if e["type"] == "tool_use" and e.get("actor") == name]
        
        if not study_steps and not collisions and not tool_uses:
            return "休息和思考"
        
        # Build context
        context_parts = []
        for s in study_steps[-3:]:
            thought = s.get("thought", "")[:150]
            if thought:
                context_parts.append(f"研究思考: {thought}")
        
        for c in collisions[-3:]:
            dialogue = c.get("dialogue", "")[:200]
            if dialogue:
                context_parts.append(f"对话: {dialogue}")
        
        if not context_parts:
            parts = []
            if study_steps:
                parts.append("做了一些研究")
            if collisions:
                others = set()
                for c in collisions:
                    for key in ["actor", "target", "initiator"]:
                        if c.get(key) and c[key] != name:
                            others.add(c[key])
                if others:
                    parts.append(f"与 {', '.join(others)} 进行了交流")
            if tool_uses:
                tool_names = set(e.get("tool", "") for e in tool_uses)
                parts.append(f"使用工具: {', '.join(tool_names)}")
            return "；".join(parts) if parts else "休息和思考"
        
        context = "\n".join(context_parts)
        system = f"你是 {name} 的日记助手。用一句话（20字以内）总结 {name} 今天做了什么、想了什么。用第一人称。"
        prompt = f"今天的事件:\n{context}\n\n用一句话总结今天（第一人称，20字以内）:"
        
        try:
            summary = self.llm.chat([{"role": "user", "content": prompt}], system=system, temperature=0.5)
            return summary.strip()[:60]
        except Exception:
            return "深度研究了感兴趣的话题"

    # ─── Decision Helpers ─────────────────────────────────────

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

        choice = random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]
        topic = char.state.current_focus or char.config.get("seed", "")

        # Handle tool choices
        tool_map = {
            "tool_run_code": "run_code",
            "tool_write_paper": "write_paper", 
            "tool_search_arxiv": "search_arxiv",
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

    # ─── Soul Evolution ────────────────────────────────────────

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

            # Relationship updates
            for rel in updates.get("relationship_updates", []):
                target = rel.get("target", "")
                bond = rel.get("new_bond", "")
                note = rel.get("history_note", "")
                if target and bond:
                    soul.update_relationship(target, bond, note)

            # Witnessed moment
            moment = updates.get("witnessed_moment", "")
            if moment:
                soul.add_witnessed_moment(moment)

            # Knowledge from conversation
            for item in updates.get("knowledge_gained", [])[:2]:
                soul.add_knowledge("gained", item)
            for item in updates.get("knowledge_questions", [])[:2]:
                soul.add_knowledge("question", item)

    def _update_soul_from_study(self, char_name: str, topic: str, thought: str):
        """Extract soul changes from a study step."""
        soul = self.souls.get(char_name)
        if soul is None:
            return

        context = f"研究主题: {topic}\n思考:\n{thought[:1500]}"
        try:
            updates = extract_soul_updates(char_name, "study", context, self.llm)
        except Exception:
            return

        if not updates:
            return

        for item in updates.get("knowledge_gained", [])[:3]:
            soul.add_knowledge("gained", item)
        for item in updates.get("knowledge_questions", [])[:2]:
            soul.add_knowledge("question", item)
        for item in updates.get("knowledge_abandoned", [])[:2]:
            soul.add_knowledge("abandoned", item)

        moment = updates.get("witnessed_moment", "")
        if moment:
            soul.add_witnessed_moment(moment)

    # ─── Logging ──────────────────────────────────────────────

    def _log(self, msg: str):
        print(msg, flush=True)

    def _inject_context(self, char_name: str):
        """Inject memory, understanding, sociology, and location context into character."""
        char = self.characters.get(char_name)
        if char is None:
            return
        mem = self.memories.get(char_name)
        soul = self.souls.get(char_name)
        if mem:
            char._memory_context = mem.get_context()
        if soul:
            char._deep_understanding = soul.get_deep_understanding(3)
            # Also update research focus from Soul
            understanding = soul.data.get("understanding", [])
            if understanding:
                latest = understanding[-1]
                if latest.get("confidence", 0) > 0.5 and latest.get("insight"):
                    char.state.current_focus = latest["insight"][:100]        
        # Inject location context
        loc = self.environment.get_location_context(char_name)
        if loc:
            char._memory_context = loc + "\n\n" + char._memory_context

        # Inject environmental stimuli
        stimuli = self.rich_env.get_stimuli(char_name)
        if stimuli:
            stim_lines = ["## 你感知到的事"]
            for s in stimuli[-4:]:
                prefix = {"high": "⚡", "medium": "🔔", "low": "·"}.get(s.urgency, "·")
                stim_lines.append(f"{prefix} [{s.source}] {s.content}")
            char._memory_context += "\n" + "\n".join(stim_lines)

        # Inject mission context
        mission_ctx = self.missions.get_context(char_name)
        if mission_ctx:
            char._memory_context = mission_ctx + "\n\n" + char._memory_context

        # Inject need state
        state = self.needs.get(char_name)
        if state:
            char._memory_context = "## 你的当前状态\n" + state.summary() + "\n\n" + char._memory_context

        # Inject community public context (what everyone can see)
        social_ctx = self.society.get_social_context(char_name)
        if social_ctx:
            char._memory_context = "## 社区中的你\n" + social_ctx + "\n\n" + char._memory_context

        # Inject collaboration context
        self._inject_collab_context(char_name)
        if hasattr(char.state, 'collab_context') and char.state.collab_context:
            char._memory_context = char.state.collab_context + "\n\n" + char._memory_context

    # ─── Deep Think Trigger ────────────────────────────────────

    def _record_memory(self, char_name: str, ep_type: str, summary: str, 
                        detail: str = "", participants: list = None,
                        valence: str = "neutral", importance: float = 0.5,
                        tags: list = None):
        """Record an episode in the character's memory and update event counts."""
        mem = self.memories.get(char_name)
        if mem is None:
            return

        ep = Episode(
            id=f"{char_name}_{self.clock:.1f}_{ep_type}",
            time=self.clock,
            day=self.day,
            type=ep_type,
            summary=summary[:200],
            detail=detail[:500],
            participants=participants or [],
            emotional_valence=valence,
            importance=importance,
            tags=tags or [],
        )
        mem.remember(ep)

        # Apply psychology-aware encoding
        char = self.characters.get(char_name)
        if char:
            soc_ctx = {"tension_zones": self.config.get("sociology", {}).get("hierarchy", {}).get("tension_zones", [])}
            ep = mem.encode_with_psychology(ep, char.personality, soc_ctx)
            # Re-save with adjusted importance
            mem.save()

        # Update working memory
        if ep_type == "study":
            mem.add_observation(summary)
        elif ep_type == "collision":
            mem.add_observation(f"与{', '.join(participants or ['某人'])}的对话: {summary[:80]}")
        elif ep_type == "tool_use":
            mem.add_observation(f"使用工具的结果: {summary[:80]}")

        # Increment event counter for deep think trigger
        counts = self._event_counts.get(char_name, {"study": 0, "collision": 0, "tool": 0})
        if ep_type in counts:
            counts[ep_type] += 1
        self._event_counts[char_name] = counts

        # Check if deep think should trigger
        self._check_deep_think(char_name)

    def _check_deep_think(self, char_name: str):
        """Check if character should do a deep thinking session."""
        counts = self._event_counts.get(char_name, {"study": 0, "collision": 0, "tool": 0})
        last = self._last_deep_think.get(char_name, 0.0)
        hours_since = self.clock - last

        if not self.deep_think.should_trigger(
            char_name, counts["study"], counts["collision"], 
            counts["tool"], hours_since
        ):
            return

        char = self.characters.get(char_name)
        if char is None:
            return

        # Gather recent events for this character
        recent = [e for e in self.event_log[-30:] 
                  if e.get("actor") == char_name or e.get("target") == char_name 
                  or e.get("initiator") == char_name]

        # Get soul context
        soul = self.souls.get(char_name)
        soul_ctx = soul.get_context_summary() if soul else ""

        # Run deep think
        self._log(f"\n  🧠 {char_name} 开始深度反思...")
        try:
            thought = self.deep_think.think_deep(char, recent, soul_ctx)
        except Exception as e:
            self._log(f"    ⚠ 深思失败: {e}")
            return

        self._log(f"    💡 洞见: {thought.understanding[:150]}...")
        self._log(f"    📊 把握: {thought.confidence:.0%}")

        # Reset counters
        self._event_counts[char_name] = {"study": 0, "collision": 0, "tool": 0}
        self._last_deep_think[char_name] = self.clock

        # Write to Soul
        if soul and not self.dry_run:
            soul.add_deep_thought(thought)

        # ── Production: record as insight artifact ──
        if not self.dry_run:
            self.production._current_day = self.day
            self.production.create_artifact(
                "insight", 
                f"洞见: {thought.understanding[:60]}...",
                thought.understanding[:500],
                [char_name],
                confidence=thought.confidence,
            )

        # ── Environment: notify rich env ──
        self.rich_env.record_event(f"{char_name} 有了一个深度洞见")

        # ── Need satisfaction ──
        state = self.needs.get(char_name)
        if state:
            satisfy_needs(state, "deep_think")

        # ── Environment: leave echo of deep insight ──
        loc = self.environment.get_location(char_name)
        if loc:
            self.environment.leave_echo(char_name, loc.id,
                f"深度反思 (Day{self.day}): {thought.understanding[:80]}")
        
        # Log event
        self.event_log.append({
            "time": self.clock,
            "type": "deep_think",
            "actor": char_name,
            "understanding": thought.understanding,
            "confidence": thought.confidence,
        })

        # ── Collaboration: deep insights may reveal shared interests ──
        self._check_solo_to_collab(char_name, thought)

    # ─── Collaboration Detection ──────────────────────────────

    def _check_collaboration(self, a: str, b: str, topic: str, dialogue: str):
        """After a meaningful collision, check if characters should collaborate."""
        char_a = self.characters.get(a)
        char_b = self.characters.get(b)
        if not char_a or not char_b:
            return

        focus_a = char_a.state.current_focus or ""
        focus_b = char_b.state.current_focus or ""

        # Already collaborating?
        for p in self.collab.get_active():
            if a in p.participants and b in p.participants:
                # They're already working together — advance the project
                if p.topic[:30] in topic or topic[:30] in p.topic:
                    p.advance(random.uniform(0.02, 0.05))
                    p.last_worked_day = self.day
                return

        # Check topic overlap
        if not self.collab.detect_overlap(focus_a, focus_b):
            return

        # Deep enough dialogue + overlapping interests → propose collaboration
        if len(dialogue) > 600:
            # Higher chance if dialogue is substantive
            if random.random() < 0.4:
                project_topic = topic if len(topic) > 10 else f"{focus_a[:30]} × {focus_b[:30]}"
                project = self.collab.create(
                    project_topic, a, [a, b], self.day
                )
                self._log(f"\n  🤝 {a} 和 {b} 发现共同兴趣，发起协作: {project_topic[:50]}")
                self.event_log.append({
                    "time": self.clock, "type": "collaboration_start",
                    "participants": [a, b], "topic": project_topic,
                })
                # Boost mood
                char_a.state.mood = "excited"
                char_b.state.mood = "curious"

    def _check_solo_to_collab(self, char_name: str, thought):
        """After deep think, character may notice others' work relates to theirs."""
        char = self.characters.get(char_name)
        if not char:
            return
        
        my_topic = char.state.current_focus or ""
        candidates = self.collab.find_collaboration_candidates(
            char_name, my_topic, self.characters
        )
        
        if candidates and random.random() < 0.25:
            other = random.choice(candidates)
            # They notice the connection
            char.state.pending_thoughts.append(
                f"我注意到{other}的研究可能和我的工作有关——也许该找ta聊聊"
            )
            if hasattr(char, '_verbose') or random.random() < 0.3:
                pass  # The pending_thoughts will surface in future context

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
