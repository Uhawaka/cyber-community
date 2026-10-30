"""Local character vectors for memory ranking. No model call, no stored archive copy.

Vectors are derived from the summary when a memory is indexed. A query ranks
those vectors and returns a few ids; the text stays on the memory record.
"""

from __future__ import annotations

from zlib import crc32

_DIM = 64


def embed(text: str) -> tuple[float, ...]:
    """Stable bag of characters and neighboring pairs. Empty text is the zero vector."""
    acc = [0.0] * _DIM
    chars = "".join(text.split())
    for index, char in enumerate(chars):
        acc[crc32(char.encode()) % _DIM] += 1.0
        if index:
            acc[crc32((chars[index - 1] + char).encode()) % _DIM] += 2.0
    norm = sum(value * value for value in acc) ** 0.5
    if norm == 0.0:
        return tuple(acc)
    return tuple(value / norm for value in acc)


def similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right))
