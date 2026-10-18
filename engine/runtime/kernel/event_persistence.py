"""Locked JSONL persistence primitives for the event log."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def append_record(
    path: Path,
    record: Mapping[str, Any],
    *,
    expected_sequence: int,
    world_hash: str,
    pre_state_hash: str | None,
    current_state_hash: str,
    expected_tail_pre_state_hash: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _path_lock(path):
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            if not _validate_tail(
                descriptor,
                expected_sequence=expected_sequence,
                world_hash=world_hash,
                pre_state_hash=pre_state_hash,
                current_state_hash=current_state_hash,
                candidate_record=record,
                expected_tail_pre_state_hash=expected_tail_pre_state_hash,
            ):
                return
            payload = json.dumps(
                record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8") + b"\n"
            write_all(descriptor, payload)
            os.fsync(descriptor)
        except EventPersistenceIOError:
            raise
        except OSError as exc:
            raise EventPersistenceIOError(f"cannot append event log: {exc}") from exc
        finally:
            if fcntl is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(descriptor)


def recover_tail(path: Path, payload: bytes, valid_length: int) -> None:
    quarantine = path.with_name(path.name + ".corrupt-tail")
    _replace_file(quarantine, payload[valid_length:])
    temporary = path.with_name(path.name + ".recovering")
    _replace_file(temporary, payload[:valid_length])
    os.replace(temporary, path)
    fsync_directory(path.parent)


class EventPersistenceIOError(ValueError):
    pass


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _validate_tail(
    descriptor: int,
    *,
    expected_sequence: int,
    world_hash: str,
    pre_state_hash: str | None,
    current_state_hash: str,
    candidate_record: Mapping[str, Any],
    expected_tail_pre_state_hash: str | None,
) -> bool:
    size = os.fstat(descriptor).st_size
    if size == 0:
        if expected_sequence != 0:
            raise EventPersistenceIOError("persisted event sequence diverged")
    else:
        os.lseek(descriptor, 0, os.SEEK_SET)
        payload = b""
        while len(payload) < size:
            chunk = os.read(descriptor, size - len(payload))
            if not chunk:
                break
            payload += chunk
        if not payload.endswith(b"\n"):
            raise EventPersistenceIOError(
                "event log has an unterminated tail; recover it before append"
            )
        lines = payload.splitlines()
        try:
            tail = json.loads(lines[-1].decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise EventPersistenceIOError("invalid persisted event log tail") from exc
        if tail.get("world_hash") != world_hash:
            raise EventPersistenceIOError("event log world hash mismatch")
        sequence = tail.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise EventPersistenceIOError("persisted event sequence diverged")
        if sequence + 1 > expected_sequence:
            if expected_sequence >= len(lines):
                raise EventPersistenceIOError("persisted event sequence diverged")
            try:
                existing = json.loads(lines[expected_sequence].decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise EventPersistenceIOError(
                    "invalid persisted event log record"
                ) from exc
            if existing != candidate_record:
                raise EventPersistenceIOError(
                    "concurrent event writer produced a divergent event"
                )
            return False
        if sequence + 1 != expected_sequence:
            raise EventPersistenceIOError("persisted event sequence diverged")
        tail_event = tail.get("event")
        if (
            not isinstance(tail_event, dict)
            or tail_event.get("pre_state_hash")
            != expected_tail_pre_state_hash
        ):
            raise EventPersistenceIOError(
                "persisted event pre-state hash diverged"
            )
    if pre_state_hash is not None and pre_state_hash != current_state_hash:
        raise EventPersistenceIOError(
            "event pre-state hash diverged before append"
        )
    return True


def _replace_file(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        write_all(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("event log write made no progress")
        view = view[written:]


def fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
