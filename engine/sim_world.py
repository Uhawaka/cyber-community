"""Environment, observation, tools, anonymous/external events."""

from __future__ import annotations

import random
from typing import Optional

from engine.events import Event
from engine.interactions import run_tool_use
from engine.observation import get_observation_queries
from engine.needs import satisfy_needs
from engine.culture import frame_observation


class WorldMixin:
    """World observation, tools, environment edits, anonymous events."""

    def _window_open(self) -> bool:
        frame = getattr(self, "world_frame", {}) or {}
        return frame.get("permeability", "connected") != "enclosed"

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


    def _handle_observe_world(self, event: Event, verbose: bool):
        """Character looks through the window at the human world."""
        char = self.characters.get(event.actor)
        if char is None:
            return

        if not self._window_open():
            if verbose:
                self._log(f"  🪟 {char.name} 走到窗边——窗是关着的，只好收回目光")
            char.state.pending_thoughts.append("窗外什么也看不见。只能继续在社区里想自己的事。")
            return

        if self.dry_run:
            if verbose:
                self._log(f"  📖 {char.name} 翻阅人类世界的图书馆 (dry_run — 跳过)")
            return

        domains = char.config.get("domains") or []
        if isinstance(domains, str):
            domains = [domains]
        focus = (
            getattr(char.state, "current_focus", None)
            or (char.research or {}).get("project")
            or ""
        )
        frame = getattr(self, "world_frame", {}) or {}
        queries = get_observation_queries(
            char.research,
            char.config.get("domain", ""),
            domains=domains,
            focus=focus,
            world_or_frame=frame,
            config=getattr(self, "config", None),
        )
        if not queries:
            fb = (frame.get("literature") or {}).get("fallback_query") or "research open problems"
            queries = [("arxiv", fb)]

        day_key = str(self.day)
        done_today = self._search_history.setdefault(day_key, set())
        fresh_queries = [(t, q) for t, q in queries if q not in done_today]
        if not fresh_queries:
            if verbose:
                self._log(f"  📖 {char.name} 今天已在图书馆待够了")
            next_t = self.clock + random.uniform(8, 16)
            self.queue.push(Event(time=next_t, type="observe_world", actor=char.name))
            return

        query_type, query = random.choice(fresh_queries)
        done_today.add(query)

        try:
            if self.tool_registry:
                tool_name = "search_web" if query_type == "web" else "search_arxiv"
                result = self.tool_registry.execute(
                    tool_name, char.name, {"query": query, "topic": query}
                )
                framed = frame_observation(
                    query, query_type, result.output if result.success else "", result.success
                )
                if verbose:
                    self._log(f"  {framed['log']}")

                if result.success:
                    source = "web" if query_type == "web" else "arxiv"
                    self.production.record_observation(source, result.output[:500], char.name)
                    self._record_memory(
                        char.name,
                        "observe",
                        framed["memory"],
                        detail=result.output[:300],
                        valence="curious",
                        importance=0.55,
                        tags=["observe", query_type, query[:30]],
                    )

                    mission = self.missions.process_observation(char.name, result.output)
                    if mission and mission.is_complete():
                        if verbose:
                            self._log(f"    🎯 心里那道题有了着落: {mission.question[:60]}")
                        char.state.mood = "excited"
                        char.gain(amount=10)
                        state = self.needs.get(char.name)
                        if state:
                            satisfy_needs(state, "mission_complete")
                        self.rich_env.record_event(f"{char.name} 在窗外读到了关键材料")
                    elif mission and mission.progress > 0:
                        if verbose:
                            self._log(f"    · 对「{mission.question[:40]}」多了一点把握")
                        if mission.progress > 0.5:
                            char.state.mood = "curious"

                    if "找到" in result.output and random.random() < 0.4:
                        char.state.pending_thoughts.append(framed["thought"])
                        char.state.mood = "curious"
                elif verbose:
                    self._log(f"    · {framed['thought']}")
        except Exception:
            pass

        next_t = self.clock + random.uniform(8, 16)
        self.queue.push(Event(time=next_t, type="observe_world", actor=char.name))


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
            params = run_tool_use(
                char,
                tool_name,
                topic,
                self.llm,
                world_frame=getattr(self, "world_frame", None),
            )
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

        # Tools update memory/production — NOT Soul (Soul is identity, not a lab notebook)

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


    def inject_anonymous_event(
        self,
        content: str,
        target: Optional[str] = None,
        framing: Optional[str] = None,
        verbose: bool = True,
    ) -> str:
        """Inject a user event without revealing the creator.

        Characters perceive it as a letter / coincidence / rumor / discovery.
        """
        if target and target not in self.characters:
            raise ValueError(f"未知角色: {target}")

        anon = self.anonymous.inject(
            content,
            day=self.day,
            time=self.clock,
            target=target,
            framing=framing,
        )

        # Leave a physical trace in the commons (author masked as "unknown")
        self.environment.leave_echo("unknown", "commons", anon.framed[:120])
        self.environment.deposit("unknown", "commons", anon.framed, "anonymous_event")

        # Soft rumor so others may hear of it even if not targeted
        self.society.spread_rumor(anon.framed[:100], "unknown", self.day, accuracy=0.6)

        self.queue.push(Event(
            time=self.clock,
            type="external",
            data={
                "description": anon.framed,
                "raw": anon.raw,
                "framing": anon.framing_type,
                "target": target or "",
            },
        ))

        self.event_log.append({
            "time": self.clock,
            "type": "anonymous_event",
            "actor": "unknown",
            "target": target or "",
            "framing": anon.framing_type,
            "description": anon.framed,
            "raw": anon.raw,
        })

        if verbose:
            who = target or "全社区"
            self._log(f"  ✉️ 匿名事件 → {who}: {anon.framed}")

        return anon.framed


    def _handle_external(self, event: Event, verbose: bool):
        description = event.data.get("description", "")
        target = event.data.get("target") or None

        if verbose:
            self._log(f"  📡 外部事件: {description}")

        # Seed pending thoughts / memory for affected characters
        names = [target] if target else list(self.characters.keys())
        for name in names:
            char = self.characters.get(name)
            if not char:
                continue
            char.state.pending_thoughts.append(f"[你察觉到] {description}")
            self._record_memory(
                name,
                "anonymous_event",
                description[:160],
                detail=description,
                valence="curious",
                importance=0.75,
                tags=["anonymous", "external"],
            )
            mem = self.memories.get(name)
            if mem:
                mem.add_question(description[:80])
                mem.add_observation(f"环境中出现异常: {description[:80]}")

