"""Single time source so tests can control expiry deterministically."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_offset = timedelta(0)


def utc_now() -> datetime:
    return datetime.now(timezone.utc) + _offset


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def advance_for_tests(delta: timedelta) -> None:
    global _offset
    _offset += delta


def reset_for_tests() -> None:
    global _offset
    _offset = timedelta(0)
