"""Simulation lifecycle: bootstrap, run loop, day boundary."""

from __future__ import annotations

import random

from engine.events import Event
from engine.character import Character


class LifecycleMixin:
    """DES main loop and day-boundary housekeeping."""

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
            # Idle thoughts always; observe only if the human-world window is open
            if not self.dry_run:
                self.queue.push(Event(time=random.uniform(3.0, 6.0), type="idle_thought", actor=char.name))
                frame = getattr(self, "world_frame", {}) or {}
                if frame.get("permeability", "connected") != "enclosed":
                    self.queue.push(
                        Event(time=random.uniform(4.0, 8.0), type="observe_world", actor=char.name)
                    )

        self.queue.push(Event(time=24.0, type="day_boundary"))
        self.queue.push(Event(time=72.0, type="weekly_seminar"))


    def run(self, max_days: int = 1, verbose: bool = True):
        """Run simulation for max_days virtual days (batch / experiment)."""
        self.running = True
        self.bootstrap()

        max_time = max_days * 24.0
        self.run_slice(until_time=max_time, max_events=10_000_000, verbose=verbose)

        self.running = False
        if verbose:
            self._log(f"模拟结束: Day {self.day}, t={self.clock:.1f}")

    def run_slice(
        self,
        until_time: float | None = None,
        max_events: int = 40,
        verbose: bool = False,
    ) -> dict:
        """Process a bounded DES slice (used by live hang windows).

        Dispatches events with time <= until_time (if set), up to max_events.
        Does not call bootstrap; caller must bootstrap once for live mode.
        """
        if not getattr(self, "_bootstrapped", False):
            self.bootstrap()
            self._bootstrapped = True
            self.running = True

        processed = 0
        while self.running and self.queue and processed < max_events:
            peek = self.queue.peek_time()
            if peek is None:
                break
            if until_time is not None and peek > until_time:
                break
            event = self.queue.pop()
            if event is None:
                break
            # Guard for batch: pop may return event past until after race; skip
            if until_time is not None and event.time > until_time:
                self.queue.push(event)
                break
            self.clock = event.time
            self._dispatch(event, verbose)
            processed += 1

        return {
            "processed": processed,
            "clock": self.clock,
            "day": self.day,
            "queue": len(self.queue),
        }


    def _dispatch(self, event: Event, verbose: bool):
        handler = getattr(self, f"_handle_{event.type}", None)
        if handler:
            handler(event, verbose)
        else:
            if verbose:
                self._log(f"⚠ 未知事件类型: {event.type}")


    def _log(self, msg: str):
        print(msg, flush=True)


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
            summary = ""
            if char_events:
                summary = self._generate_day_summary(name, char, char_events)
                self.archives[name].add_day_summary(completed_day, summary, char_events)
                if verbose:
                    self._log(f"  📝 {name}: {summary[:80]}...")

            # Memory consolidation — promote facts, compress stale episodes
            mem = self.memories.get(name)
            if mem:
                stats = mem.consolidate_day(completed_day)
                if verbose and (stats.get("facts_added") or stats.get("compressed")):
                    self._log(
                        f"  🧠 {name} 记忆整理: +{stats['facts_added']}事实, "
                        f"压缩{stats['compressed']}条, 剩余{stats['remaining']}"
                    )

            # Soul calibration every 7 days — fight personality flattening
            if completed_day > 0 and completed_day % 7 == 0:
                soul = self.souls.get(name)
                if soul:
                    recent = []
                    if summary:
                        recent.append(summary)
                    archive_ctx = self.archives[name].get_recent_context(3)
                    if archive_ctx:
                        recent.append(archive_ctx)
                    note = soul.calibrate(completed_day, recent)
                    if note:
                        char.state.pending_thoughts.append(f"[内心提醒] {note}")
                        if verbose:
                            self._log(f"  ⚓ {name} 人格校准")

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
            # Idle thoughts + observation (same as bootstrap)
            if not self.dry_run:
                self.queue.push(Event(time=self.clock + random.uniform(3.0, 6.0),
                                       type="idle_thought", actor=char.name))
                frame = getattr(self, "world_frame", {}) or {}
                if frame.get("permeability", "connected") != "enclosed":
                    self.queue.push(Event(
                        time=self.clock + random.uniform(4.0, 8.0),
                        type="observe_world", actor=char.name,
                    ))


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

