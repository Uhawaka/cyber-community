"""Event types and priority queue for Discrete Event Simulation."""

import heapq
import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass(order=True)
class Event:
    """An event in the DES queue. Ordered by time."""
    time: float
    type: str = field(compare=False)
    actor: str = field(default="", compare=False)
    target: str = field(default="", compare=False)
    data: dict = field(default_factory=dict, compare=False)

    def __repr__(self):
        return f"Event(t={self.time:.2f}, {self.type}, actor={self.actor}, target={self.target})"


class EventQueue:
    """Min-heap priority queue of Events."""

    def __init__(self):
        self._heap = []
        self._counter = 0  # tie-breaker for events at same time

    def push(self, event: Event):
        heapq.heappush(self._heap, (event.time, self._counter, event))
        self._counter += 1

    def pop(self) -> Optional[Event]:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)[2]

    def peek_time(self) -> Optional[float]:
        if not self._heap:
            return None
        return self._heap[0][0]

    def __len__(self):
        return len(self._heap)

    def __bool__(self):
        return len(self._heap) > 0


def sample_poisson_interval(lam: float) -> float:
    """Sample from exponential distribution: interval ~ Exp(λ)."""
    if lam <= 0:
        return float('inf')
    return random.expovariate(lam)


def sample_next_activate(lam: float, current_time: float) -> float:
    """Sample the next activation time for a character."""
    interval = sample_poisson_interval(lam)
    return current_time + interval
