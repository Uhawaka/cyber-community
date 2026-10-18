"""Thin JSON presentation-storage adapter using the narrative store as its core."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.narrative.store import PresentationStore


class JsonPresentationStorage:
    """Explicit composition wrapper; persistence logic remains in PresentationStore."""

    def __init__(self, path: str | Path) -> None:
        selected = Path(path)
        self._store = (
            PresentationStore.load(selected)
            if selected.exists()
            else PresentationStore(selected)
        )

    @property
    def core(self) -> PresentationStore:
        return self._store

    def cursor_for(self, audience_id: str) -> int:
        return self._store.cursor_for(audience_id)

    def publish(self, *args: Any, **kwargs: Any) -> Any:
        return self._store.publish(*args, **kwargs)

    def get(self, presentation_id: str) -> Any:
        return self._store.get(presentation_id)

    def rerender(self, *args: Any, **kwargs: Any) -> Any:
        return self._store.rerender(*args, **kwargs)

    def clear(self, audience_id: str | None = None) -> None:
        self._store.clear(audience_id)
