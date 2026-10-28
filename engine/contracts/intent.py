"""Bounded private plans, dependencies, conditions and resource budgets."""

from __future__ import annotations

from dataclasses import dataclass

from engine.contracts.validation import require_int, require_sources, require_text


INTENT_STEP_VERBS = frozenset({
    "move", "inspect", "repair", "take", "use", "speak", "learn", "rest", "wait",
})


@dataclass(frozen=True)
class IntentCondition:
    kind: str
    target_id: str
    quantity: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in {"at_location", "inventory_at_least"}:
            raise ValueError("unsupported personal plan condition")
        require_text(self.target_id, "condition target", 200)
        require_int(self.quantity, "condition quantity", 1)
        if self.quantity > 100 or (self.kind == "at_location" and self.quantity != 1):
            raise ValueError("invalid personal plan condition quantity")


@dataclass(frozen=True)
class IntentStep:
    verb: str
    target_id: str
    quantity: int = 1
    item_id: str = ""
    speech: str = ""
    on_failure: int = -1
    depends_on: tuple[int, ...] | None = None
    guards: tuple[IntentCondition, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.verb, str) or self.verb not in INTENT_STEP_VERBS:
            raise ValueError("plan step requires a supported registered action")
        require_text(self.target_id, "step target")
        require_int(self.quantity, "step quantity", 1)
        if self.quantity > 100:
            raise ValueError("step quantity exceeds action capacity")
        if not isinstance(self.item_id, str) or not isinstance(self.speech, str):
            raise ValueError("step optional text must be strings")
        try:
            self.item_id.encode("utf-8")
            self.speech.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("step text requires valid Unicode") from exc
        if len(self.item_id) > 2000 or len(self.speech) > 2000:
            raise ValueError("step text exceeds budget")
        if self.item_id or (self.verb != "speak" and self.speech):
            raise ValueError("unsupported optional fields in plan step")
        if self.verb == "speak":
            require_text(self.speech, "step speech")
        if self.verb not in {"take", "use"} and self.quantity != 1:
            raise ValueError("step quantity is not supported for this action")
        if isinstance(self.on_failure, bool) or not isinstance(self.on_failure, int) or self.on_failure < -1:
            raise ValueError("invalid failure branch")
        if self.depends_on is not None:
            if (not isinstance(self.depends_on, (tuple, list)) or len(self.depends_on) > 8
                    or any(isinstance(item, bool) or not isinstance(item, int) or item < 0
                           for item in self.depends_on)
                    or len(set(self.depends_on)) != len(self.depends_on)):
                raise ValueError("invalid plan dependencies")
            object.__setattr__(self, "depends_on", tuple(sorted(self.depends_on)))
        if not isinstance(self.guards, (tuple, list)) or len(self.guards) > 4:
            raise ValueError("personal plan conditions exceed budget")
        try:
            guards = tuple(IntentCondition(**item) if isinstance(item, dict) else item for item in self.guards)
        except TypeError as exc:
            raise ValueError("invalid personal plan condition") from exc
        if not all(isinstance(item, IntentCondition) for item in guards) or len(set(guards)) != len(guards):
            raise ValueError("invalid personal plan conditions")
        object.__setattr__(self, "guards", guards)


def intent_budget(value):
    if not isinstance(value, (tuple, list)) or len(value) > 8:
        raise ValueError("personal plan budget must be bounded")
    rows = []
    for row in value:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise ValueError("invalid personal plan budget")
        item, amount = row
        require_text(item, "budget resource", 200)
        require_int(amount, "budget amount")
        if amount > 10000:
            raise ValueError("personal plan budget amount exceeds limit")
        rows.append((item, amount))
    if len({item for item, _ in rows}) != len(rows):
        raise ValueError("personal plan budget resources must be unique")
    return tuple(sorted(rows))


def validate_intent_steps(steps):
    dependencies = []
    for index, step in enumerate(steps):
        if step.on_failure != -1 and not index < step.on_failure < len(steps):
            raise ValueError("failure branch must target a later plan step")
        required = tuple(range(index)) if step.depends_on is None else step.depends_on
        if any(item >= len(steps) or item == index for item in required):
            raise ValueError("invalid plan dependencies")
        dependencies.append(required)
    active, done = set(), set()

    def visit(index):
        if index in active:
            raise ValueError("cyclic plan dependencies")
        if index in done:
            return
        active.add(index)
        for dependency in dependencies[index]:
            visit(dependency)
        active.remove(index)
        done.add(index)

    for index in range(len(steps)):
        visit(index)


@dataclass(frozen=True)
class IntentPlan:
    plan_id: str
    owner_id: str
    description: str
    steps: tuple[IntentStep, ...]
    source_refs: tuple[str, ...]
    cursor: int = 0
    status: str = "ready"
    plan_budget: tuple[tuple[str, int], ...] = ()
    skipped_steps: tuple[int, ...] = ()
    completed_steps: tuple[int, ...] | None = None
    goal_id: str = ""
    deadline_tick: int | None = None
    deadline_reached: bool = False

    def __post_init__(self) -> None:
        for field in ("plan_id", "owner_id", "description"):
            require_text(getattr(self, field), field)
        if not isinstance(self.goal_id, str):
            raise ValueError("plan goal reference must be text")
        if self.goal_id:
            require_text(self.goal_id, "plan goal reference")
        if self.deadline_tick is not None:
            require_int(self.deadline_tick, "plan deadline")
        if not isinstance(self.deadline_reached, bool) or (self.deadline_reached and self.deadline_tick is None):
            raise ValueError("invalid plan deadline review state")
        if not isinstance(self.steps, (tuple, list)) or not 1 <= len(self.steps) <= 8:
            raise ValueError("personal plan requires one to eight steps")
        steps = tuple(IntentStep(**step) if isinstance(step, dict) else step for step in self.steps)
        if not all(isinstance(step, IntentStep) for step in steps):
            raise ValueError("invalid personal plan step")
        validate_intent_steps(steps)
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "plan_budget", intent_budget(self.plan_budget))
        require_sources(self.source_refs)
        require_int(self.cursor, "plan cursor")
        if self.cursor > len(steps) or self.status not in {"ready", "blocked", "completed", "abandoned"}:
            raise ValueError("invalid personal plan lifecycle")
        if (self.status == "completed") != (self.cursor == len(steps)):
            raise ValueError("completed plan requires all steps")
        if (not isinstance(self.skipped_steps, (tuple, list))
                or any(isinstance(n, bool) or not isinstance(n, int) or not 0 <= n < len(steps)
                       for n in self.skipped_steps)
                or tuple(self.skipped_steps) != tuple(sorted(set(self.skipped_steps)))):
            raise ValueError("invalid skipped plan steps")
        object.__setattr__(self, "skipped_steps", tuple(self.skipped_steps))
        completed = self.completed_steps
        if completed is None:
            completed = tuple(i for i in range(self.cursor) if i not in self.skipped_steps)
        if (not isinstance(completed, (tuple, list))
                or any(isinstance(n, bool) or not isinstance(n, int) or not 0 <= n < len(steps)
                       for n in completed)
                or tuple(completed) != tuple(sorted(set(completed)))
                or set(completed) & set(self.skipped_steps)):
            raise ValueError("invalid completed plan steps")
        object.__setattr__(self, "completed_steps", tuple(completed))


def ready_intent_steps(plan: IntentPlan) -> tuple[int, ...]:
    completed, skipped = set(plan.completed_steps), set(plan.skipped_steps)
    ready = []
    for index, step in enumerate(plan.steps):
        if index in completed or index in skipped:
            continue
        if step.depends_on is None:
            available = all(i in completed or i in skipped for i in range(index))
        else:
            available = all(i in completed for i in step.depends_on)
        if available:
            ready.append(index)
    return tuple(ready)
