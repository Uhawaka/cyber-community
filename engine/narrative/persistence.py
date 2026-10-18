"""Atomic file writer for presentation snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Mapping


def next_id(prefix: str, values: Mapping[str, object]) -> str:
    highest = max(
        (
            int(key.removeprefix(prefix + "-"))
            for key in values
            if key.startswith(prefix + "-")
            and key.removeprefix(prefix + "-").isdigit()
        ),
        default=0,
    )
    return f"{prefix}-{highest + 1:04d}"


def persist_snapshot(
    path: Path,
    *,
    schema_version: str,
    cursors: Mapping[str, int],
    presentations: Mapping[str, object],
    episodes: Mapping[str, object],
    presentation_record: Callable[[object], dict[str, object]],
    episode_record: Callable[[object], dict[str, object]],
) -> None:
    record = {
        "schema_version": schema_version,
        "render_version": max(
            (
                getattr(item, "render_version")
                for item in presentations.values()
            ),
            default=1,
        ),
        "cursors": dict(sorted(cursors.items())),
        "presentations": [
            presentation_record(item) for item in presentations.values()
        ],
        "episodes": [episode_record(item) for item in episodes.values()],
    }
    payload = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    atomic_write_text(path, payload)


def atomic_write_text(path: Path, payload: str) -> None:
    """Atomically replace a private UTF-8 text artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = -1
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
