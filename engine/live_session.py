"""Persistent community session: wall-clock hang windows + avatar REPL.

Batch experiments stay in main.py. This module powers live.py.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from engine.memory import Episode
from engine.engine import SimulationEngine


DEFAULT_WAKE_TIMES = ("09:30", "14:00", "21:00")


def parse_wake_times(raw: str | list | tuple | None) -> list[tuple[int, int]]:
    """Parse '09:30,14:00,21:00' or list into sorted (hour, minute) tuples."""
    if raw is None:
        items = list(DEFAULT_WAKE_TIMES)
    elif isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw]
    else:
        items = [p.strip() for p in str(raw).split(",") if p.strip()]
    out: list[tuple[int, int]] = []
    for item in items:
        hh, mm = item.split(":")
        out.append((int(hh), int(mm)))
    return sorted(set(out))


def community_has_lived(engine: SimulationEngine) -> bool:
    """True only after a founding virtual day — not empty souls / backstory.

    Engine __init__ always writes souls, backstory, and seed-shelf memories.
    A previous live start that never ran a day must still count as unfounded.
    Day/clock reset every process unless sim_state.json says otherwise.
    """
    state = getattr(engine, "_sim_state", None) or {}
    if state.get("founded"):
        return True
    if int(getattr(engine, "day", 1) or 1) > 1:
        return True
    for archive in getattr(engine, "archives", {}).values():
        try:
            rows = archive._read()
        except Exception:
            continue
        if any(isinstance(r, dict) and (r.get("summary") or r.get("day")) for r in (rows or [])):
            return True
    return False


def next_wake_after(now: datetime, wake_times: list[tuple[int, int]]) -> datetime:
    """Next wall-clock wake strictly after `now` (local naive datetime)."""
    today = now.date()
    candidates = []
    for h, m in wake_times:
        candidates.append(datetime(today.year, today.month, today.day, h, m))
        candidates.append(
            datetime(today.year, today.month, today.day, h, m) + timedelta(days=1)
        )
    future = [c for c in candidates if c > now]
    return min(future)


class LiveSession:
    """Background hang scheduler + foreground avatar REPL."""

    def __init__(
        self,
        engine: SimulationEngine,
        avatar_name: str = "Visitor",
        avatar_bio: str = "",
        wake_times: list[tuple[int, int]] | None = None,
        virtual_hours_per_wake: float = 8.0,
        max_events_per_wake: int = 70,
        max_llm_calls_per_wake: int = 160,
        sleep: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] | None = None,
    ):
        self.engine = engine
        self.lock = threading.RLock()
        self.avatar_name = (avatar_name or "Visitor").strip()
        self.avatar_bio = (avatar_bio or "").strip()
        self.focus: Optional[str] = None
        self.wake_times = wake_times or parse_wake_times(None)
        self.virtual_hours_per_wake = float(virtual_hours_per_wake)
        self.max_events_per_wake = int(max_events_per_wake)
        self.max_llm_calls_per_wake = int(max_llm_calls_per_wake)
        self._sleep = sleep
        self._now = now_fn or datetime.now

        self.watch = False
        self.guide_name = "向导"
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._idle = threading.Condition(self.lock)
        self._last_wake: Optional[datetime] = None
        self._wake_count = 0
        self._wake_running = False
        self._log_lines: list[str] = []

        # Patch engine logger so watch can toggle without drowning the REPL
        self._orig_log = engine._log
        engine._log = self._engine_log

    # ── logging ───────────────────────────────────────────────

    def _engine_log(self, msg: str):
        if self.watch:
            self._orig_log(msg)
        else:
            self._log_lines.append(msg)
            if len(self._log_lines) > 200:
                self._log_lines = self._log_lines[-200:]

    # ── background hang ───────────────────────────────────────

    def ensure_founded(self, *, verbose: bool = True) -> dict:
        """If the community has never lived, create it and run one virtual day.

        Live used to only bootstrap empty files and wait for a wall-clock wake,
        which looks like 'nothing happened, no error'. Founding is a real day
        (same path as `main.py --days 1`), then hang continues from there.
        """
        if community_has_lived(self.engine):
            return {
                "created": False,
                "day": self.engine.day,
                "clock": self.engine.clock,
                "processed": 0,
                "output_dir": str(self.engine._output_dir),
            }
        prev_log = self.engine._log
        if verbose:
            self.engine._log = self._orig_log
            self._orig_log("社区尚未创建 — 先建档并跑完第一个虚拟日…")
        try:
            self.engine.run(max_days=1, verbose=verbose)
        finally:
            self.engine._bootstrapped = True
            self.engine.running = False
            self.engine._log = prev_log
            if hasattr(self.engine, "save_sim_state"):
                self.engine.save_sim_state(
                    founded=self.engine.day > 1 or bool(self.engine.event_log)
                )
        if verbose:
            self._orig_log(
                f"第一个虚拟日结束：Day {self.engine.day}, t={self.engine.clock:.1f}。"
                f"产出 {self.engine._output_dir}。进入常驻。"
            )
        return {
            "created": True,
            "day": self.engine.day,
            "clock": self.engine.clock,
            "processed": len(self.engine.event_log),
            "output_dir": str(self.engine._output_dir),
        }

    def start(self):
        with self.lock:
            if not getattr(self.engine, "_bootstrapped", False):
                self.engine.bootstrap()
                self.engine._bootstrapped = True
            self.engine.running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._hang_loop, name="cc-hang", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        with self.lock:
            self.engine.running = False
            self._idle.notify_all()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self.engine._log = self._orig_log

    def _hang_loop(self):
        self._force_wake_event = threading.Event()
        while not self._stop.is_set():
            now = self._now()
            nxt = next_wake_after(now, self.wake_times)
            wait_s = max(0.05, (nxt - now).total_seconds())
            end = time.time() + wait_s
            while not self._stop.is_set() and time.time() < end:
                if self._force_wake_event.is_set():
                    self._force_wake_event.clear()
                    break
                self._sleep(min(0.5, max(0.05, end - time.time())))
            if self._stop.is_set():
                break
            self.run_wake_window(verbose=self.watch)

    def force_wake(self) -> dict:
        """Run one hang window immediately (tests / nextwake debugging)."""
        return self.run_wake_window(verbose=self.watch)

    def run_wake_window(self, verbose: bool = False) -> dict:
        """Advance one hang window without holding the REPL lock across LLM work."""
        with self.lock:
            if self._wake_running:
                return {
                    "processed": 0,
                    "clock": self.engine.clock,
                    "day": self.engine.day,
                    "queue": len(self.engine.queue),
                    "llm_calls": 0,
                    "skipped": "wake_in_progress",
                }
            self._wake_running = True
            until = self.engine.clock + self.virtual_hours_per_wake
            max_events = self.max_events_per_wake
            max_llm = self.max_llm_calls_per_wake
        try:
            # DES + LLM run unlocked so status / ask / talk can proceed
            stats = self.engine.run_slice(
                until_time=until,
                max_events=max_events,
                max_llm_calls=max_llm,
                verbose=verbose,
            )
        finally:
            with self.lock:
                self._wake_running = False
                self._last_wake = self._now()
                self._wake_count += 1
                self._idle.notify_all()
        return stats

    def next_wake_at(self) -> datetime:
        return next_wake_after(self._now(), self.wake_times)

    # ── status helpers ────────────────────────────────────────

    def status_text(self) -> str:
        with self.lock:
            eng = self.engine
            lines = [
                f"Day {eng.day}  t={eng.clock:.1f}  queue={len(eng.queue)}  "
                f"wakes={self._wake_count}  avatar={self.avatar_name}",
                f"next wall wake: {self.next_wake_at().strftime('%Y-%m-%d %H:%M')}",
            ]
            for name, char in eng.characters.items():
                loc = eng.environment.get_location(name)
                loc_name = loc.name if loc else "?"
                focus = (char.state.current_focus or "")[:40]
                sus = " [suspended]" if char.state.suspended_work else ""
                lines.append(
                    f"  {name}: {char.state.status} E={char.state.energy} "
                    f"@ {loc_name} focus={focus!r}{sus}"
                )
            return "\n".join(lines)

    def who_text(self) -> str:
        with self.lock:
            lines = []
            for name, soul in self.engine.souls.items():
                ident = (soul.data.get("identity") or {})
                craft = (ident.get("craft") or "")[:80]
                focus = (soul.data.get("orientation") or {}).get("current_focus", "")
                lines.append(f"{name}: {craft}")
                if focus:
                    lines.append(f"  focus: {str(focus)[:80]}")
            return "\n".join(lines) if lines else "(no cast)"

    # ── observer guide (saves UI work) ─────────────────────────

    def observer_briefing(self) -> str:
        """Compact community snapshot for the guide agent (never injected into cast)."""
        with self.lock:
            eng = self.engine
            parts = [
                f"World day={eng.day} virtual_t={eng.clock:.1f} queue={len(eng.queue)}",
                f"Visitor alias: {self.avatar_name}",
                "Members:",
            ]
            for name, char in eng.characters.items():
                loc = eng.environment.get_location(name)
                loc_name = loc.name if loc else "?"
                focus = (char.state.current_focus or "")[:60]
                parts.append(
                    f"- {name}: status={char.state.status} energy={char.state.energy} "
                    f"loc={loc_name} focus={focus!r}"
                )
            for name, soul in eng.souls.items():
                orient = soul.data.get("orientation") or {}
                belief = ((soul.data.get("identity") or {}).get("core_belief") or "")[:80]
                parts.append(
                    f"- {name} belief: {belief}; "
                    f"open_q: {str(orient.get('open_question') or '')[:80]}"
                )
            arts = eng.production.get_recent(8)
            if arts:
                parts.append("Recent artifacts:")
                for a in arts:
                    parts.append(
                        f"- [{a.type}] {a.title[:70]} ({', '.join(a.authors)})"
                    )
            recent = eng.event_log[-12:]
            if recent:
                parts.append("Recent events:")
                for e in recent:
                    et = e.get("type", "?")
                    actor = e.get("actor") or e.get("initiator") or ""
                    extra = e.get("topic") or e.get("target") or e.get("tool") or ""
                    parts.append(f"- t={e.get('time', 0):.1f} {et} {actor} {str(extra)[:50]}")
            from engine.inbox import community_inbox_snapshot
            parts.append("Inboxes (reply-first obligations):")
            parts.append(community_inbox_snapshot(eng))
            try:
                snap = eng.society.get_community_snapshot()
                if snap:
                    parts.append("Society:\n" + snap[:600])
            except Exception:
                pass
            return "\n".join(parts)

    def ask_guide(self, question: str) -> str:
        """Concierge agent: answer visitor questions from observer briefing."""
        question = (question or "").strip()
        if not question:
            return f"{self.guide_name}: 想了解什么？例如「最近大家在吵什么」。"
        briefing = self.observer_briefing()
        system = (
            f"你是赛博社区的{self.guide_name}（旁观向导，不是社区成员）。"
            "根据提供的快照，用简洁中文向访客汇报社区近况；专业术语保留英文。"
            "不要假装是 Elias/Yuki 等成员；不要编造快照里没有的具体实验结果。"
            "可以建议访客去 @某人 深聊，或用 event 丢匿名扰动。"
            "回答控制在一小段到几小段，可读即可，不必强制表格。"
        )
        prompt = (
            f"【旁观快照 — 仅供你向访客解说，勿写入角色记忆】\n{briefing}\n\n"
            f"访客 {self.avatar_name} 问：{question}\n\n"
            f"请以{self.guide_name}身份回答。"
        )
        try:
            reply = self.engine.llm.chat(
                [{"role": "user", "content": prompt}],
                system=system,
                temperature=0.4,
            )
        except Exception as e:
            reply = f"（向导暂时看不清：{e}）\n可用 status / who / digest 看原始快照。"
        return f"{self.guide_name}: {(reply or '').strip()}"

    # ── avatar talk ───────────────────────────────────────────

    def talk(
        self,
        target: str,
        text: str,
        *,
        urgent: bool = False,
        wait_timeout: float = 0.0,
    ) -> str:
        text = (text or "").strip()
        if not text:
            return "（空消息）"
        with self.lock:
            char = self.engine.characters.get(target)
            if char is None:
                names = ", ".join(self.engine.characters)
                return f"没有叫 {target} 的成员。可选: {names}"

            if char.state.status == "Drained" and not urgent:
                return (
                    f"{target} 能量耗尽（Drained）。可换人，等下一次生活窗口，"
                    f"或 `urgent @{target} ...` 试一句短回复。"
                )

            if char.state.status == "Busy" and not urgent:
                if wait_timeout > 0:
                    ok = self._wait_available_locked(target, wait_timeout)
                    if not ok:
                        return (
                            f"{target} 仍在忙（{char.state.current_focus or '工作中'}）。"
                            f"再试 `wait`，或 `urgent @{target} {text}`。"
                        )
                else:
                    topic = char.state.current_focus or "某件事"
                    return (
                        f"{target} 正忙于「{topic}」。"
                        f"输入 `wait` 等 TA 空闲，或 `urgent @{target} {text}` 挂起工作来聊。"
                    )

            suspended = False
            if char.state.status == "Busy" and urgent:
                if char.state.suspended_work:
                    return f"{target} 已有一层挂起工作，请先结束当前对话或等 TA 恢复。"
                suspended = char.suspend_work()

            brief = char.state.status == "Drained"
            # Prepare under lock; LLM outside so wake/status aren't blocked
            system, user_msg = self._prepare_avatar_prompt(char, text, brief=brief)
            char_name = char.name

        reply = self._avatar_llm_reply(system, user_msg)

        with self.lock:
            char = self.engine.characters.get(char_name)
            if char is None:
                return f"{char_name}: {reply}"
            self._record_avatar_talk(char, text, reply)
            if suspended:
                char.resume_work()
                char.state.pending_thoughts.append(
                    f"[被 {self.avatar_name} 紧急打断后恢复] 刚才聊了: {text[:60]}"
                )
            return f"{char_name}: {reply}"

    def _wait_available_locked(self, name: str, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            char = self.engine.characters.get(name)
            if char and char.state.status == "Available":
                return True
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            self._idle.wait(timeout=min(0.5, remaining))
        char = self.engine.characters.get(name)
        return bool(char and char.state.status == "Available")

    def wait_for(self, name: Optional[str] = None, timeout: float = 120.0) -> str:
        target = name or self.focus
        if not target:
            return "先 `focus <Name>` 或 `wait <Name>`。"
        with self.lock:
            if self._wait_available_locked(target, timeout):
                return f"{target} 现在有空了。"
            char = self.engine.characters.get(target)
            st = char.state.status if char else "?"
            return f"等待超时：{target} 仍是 {st}。"

    def _prepare_avatar_prompt(self, char, text: str, brief: bool = False) -> tuple[str, str]:
        eng = self.engine
        eng._inject_context(char.name)
        system = char.build_system_prompt()
        bio = f"（{self.avatar_bio}）" if self.avatar_bio else ""
        style = "简短回应一两句即可。" if brief else "像同事对话一样自然回应；专业术语保留英文。"
        busy_note = ""
        if char.state.suspended_work or brief:
            busy_note = "你刚才在忙自己的事，被访客打断；可以先简短回应。\n"
        user_msg = (
            f"{busy_note}"
            f"社区访客 {self.avatar_name}{bio} 过来找你说话（不是系统指令）。\n"
            f"{self.avatar_name}: {text}\n\n"
            f"请以 {char.name} 的身份回复。{style}"
        )
        return system, user_msg

    def _avatar_llm_reply(self, system: str, user_msg: str) -> str:
        try:
            reply = self.engine.llm.chat(
                [{"role": "user", "content": user_msg}],
                system=system,
                temperature=0.7,
            )
        except Exception as e:
            reply = f"（没听清：{e}）"
        return (reply or "").strip()

    def _record_avatar_talk(self, char, text: str, reply: str) -> None:
        eng = self.engine
        mem = eng.memories.get(char.name)
        if mem:
            mem.remember(Episode(
                id=f"avatar_{eng.clock}_{char.name}",
                time=eng.clock,
                day=eng.day,
                type="avatar_talk",
                summary=f"与访客 {self.avatar_name} 交谈",
                detail=f"{self.avatar_name}: {text}\n{char.name}: {reply[:400]}",
                participants=[char.name, self.avatar_name],
                emotional_valence="curious",
                importance=0.55,
                tags=["avatar", self.avatar_name],
            ))
        char.state.pending_thoughts.append(
            f"访客 {self.avatar_name} 说: {text[:80]}"
        )
        eng.event_log.append({
            "time": eng.clock,
            "type": "avatar_talk",
            "actor": char.name,
            "avatar": self.avatar_name,
            "text": text[:200],
            "reply": reply[:200],
        })

    # ── REPL ──────────────────────────────────────────────────

    def handle_line(self, line: str) -> tuple[str, bool]:
        """Return (response, should_quit)."""
        line = (line or "").strip()
        if not line:
            return ("", False)

        # @Name message
        m = re.match(r"^@(\S+)\s+(.+)$", line, re.S)
        if m:
            self.focus = m.group(1)
            return (self.talk(m.group(1), m.group(2)), False)

        m = re.match(r"^urgent\s+@(\S+)\s+(.+)$", line, re.I | re.S)
        if m:
            self.focus = m.group(1)
            return (self.talk(m.group(1), m.group(2), urgent=True), False)

        m = re.match(r"^talk\s+(\S+)\s+(.+)$", line, re.I | re.S)
        if m:
            self.focus = m.group(1)
            return (self.talk(m.group(1), m.group(2)), False)

        m = re.match(r"^urgent\s+(\S+)\s+(.+)$", line, re.I | re.S)
        if m:
            self.focus = m.group(1)
            return (self.talk(m.group(1), m.group(2), urgent=True), False)

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("quit", "exit", "q"):
            return ("再见。社区生活窗口已停止。", True)

        if cmd == "help":
            return (HELP_TEXT, False)

        if cmd in ("ask", "guide", "?"):
            q = arg if cmd != "?" else (arg or line.lstrip("?").strip())
            if cmd == "?" and not q:
                q = "现在社区里发生了什么？"
            return (self.ask_guide(q or "现在社区里发生了什么？"), False)

        if cmd == "iam":
            bits = arg.split(maxsplit=1)
            if not bits or not bits[0]:
                return (f"当前马甲: {self.avatar_name} — {self.avatar_bio or '(no bio)'}", False)
            self.avatar_name = bits[0]
            self.avatar_bio = bits[1] if len(bits) > 1 else self.avatar_bio
            return (f"马甲设为 {self.avatar_name}", False)

        if cmd == "focus":
            if not arg:
                return (f"focus={self.focus}", False)
            if arg in ("-", "none", "clear", "off"):
                self.focus = None
                return ("已取消 focus；裸输入会问向导。", False)
            if arg not in self.engine.characters:
                return (f"未知角色: {arg}", False)
            self.focus = arg
            return (f"之后裸输入默认对 {arg} 说。用 focus clear 回到向导。", False)

        if cmd == "unfocus":
            self.focus = None
            return ("已取消 focus；裸输入会问向导。", False)

        if cmd == "wait":
            name = arg.strip() or None
            return (self.wait_for(name), False)

        if cmd == "status":
            return (self.status_text(), False)

        if cmd == "who":
            return (self.who_text(), False)

        if cmd == "digest":
            with self.lock:
                dig = self.engine.production.generate_digest("daily")
                snap = self.engine.society.get_community_snapshot()
            return (f"{dig}\n\n---\n{snap}", False)

        if cmd == "soul":
            name = arg.strip() or self.focus
            if not name or name not in self.engine.souls:
                return ("用法: soul <Name>（旁观摘要，不注入对话）", False)
            with self.lock:
                summary = self.engine.souls[name].get_context_summary()
            return (f"[observer-only]\n{summary}", False)

        if cmd in ("papers", "arts"):
            with self.lock:
                arts = self.engine.production.get_recent(15)
            if not arts:
                return ("（尚无制品）", False)
            lines = [f"- [{a.type}] {a.title} ({', '.join(a.authors)}, Day{a.created_day})" for a in arts]
            return ("\n".join(lines), False)

        if cmd == "event":
            if not arg:
                return ("用法: event <匿名扰动文本>", False)
            with self.lock:
                framed = self.engine.inject_anonymous_event(arg, verbose=False)
            return (f"已注入匿名事件:\n{framed}", False)

        if cmd == "nextwake":
            return (f"下一墙钟生活窗口: {self.next_wake_at().strftime('%Y-%m-%d %H:%M')}", False)

        if cmd == "wake":
            # Manual nudge — useful when testing without waiting for calendar
            stats = self.force_wake()
            return (
                f"已跑完一个生活窗口: processed={stats['processed']} "
                f"llm={stats.get('llm_calls', '?')} "
                f"t={stats['clock']:.1f} Day{stats['day']}",
                False,
            )

        if cmd == "watch":
            mode = arg.strip().lower()
            if mode in ("on", "1", "true"):
                self.watch = True
                return ("watch on — 后台事件将刷屏", False)
            if mode in ("off", "0", "false"):
                self.watch = False
                return ("watch off", False)
            return (f"watch={'on' if self.watch else 'off'}", False)

        # Bare text → member if focused, else observer guide (no fancy UI needed)
        if self.focus:
            return (self.talk(self.focus, line), False)

        return (self.ask_guide(line), False)

    def prompt(self) -> str:
        world = (
            self.engine.config.get("name")
            or (self.engine.config.get("meta") or {}).get("name")
            or "community"
        )
        focus = f"/{self.focus}" if self.focus else ""
        return f"{world}/{self.avatar_name}{focus}> "


HELP_TEXT = """命令:
  ask <问题>           问向导（旁观汇报，省展示 UI）
  （无 focus 时裸输入也会问向导）
  iam <Name> [bio]     设置马甲
  focus <Name>         裸输入改为对该成员说话；focus clear 回到向导
  @Name <text>         与成员对话
  talk / urgent ...    同上 / 挂起工作后对话
  wait [Name]          等待空闲
  status / who / digest / papers / soul   原始快照（调试用）
  event <text>         匿名扰动
  nextwake / wake      下一窗口 / 立刻跑一窗
  watch on|off         后台事件刷屏
  help / quit"""
