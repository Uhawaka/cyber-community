"""Shared validation for bounded community contract values."""


def require_text(value: str, field: str, limit: int = 2000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} requires bounded non-empty text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} requires valid Unicode text") from exc


def require_int(value: int, field: str, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} requires an integer >= {minimum}")


def require_sources(sources: tuple[str, ...]) -> None:
    if not isinstance(sources, (tuple, list)) or not sources or len(sources) > 16:
        raise ValueError("sources must be non-empty, unique and bounded")
    for source in sources:
        require_text(source, "source", 200)
    if len(sources) != len(set(sources)):
        raise ValueError("sources must be non-empty, unique and bounded")
