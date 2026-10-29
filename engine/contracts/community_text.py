"""Text matching shared by the runtime and the narrative layer.

Kept in contracts so both sides can use one rule without either importing the other.
"""

from __future__ import annotations

REVEAL_OVERLAP = 8
"""A line counts as repeating a secret when it shares this many contiguous characters."""


def shared_phrase(left: str, right: str) -> int:
    """Length of the longest substring of ``left`` that also appears in ``right``."""
    best = 0
    for start in range(len(left)):
        for size in range(best + 1, len(left) - start + 1):
            if left[start:start + size] in right:
                best = size
            else:
                break
    return best
