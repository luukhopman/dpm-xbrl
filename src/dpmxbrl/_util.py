"""Small shared helpers for report adapters."""

from __future__ import annotations

import gc
import json
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, NoReturn
from urllib.parse import urljoin, urlsplit

from .model import ReportError


class FrozenDict(dict[str, str]):
    """A dict that refuses changes, so facts can share one.

    It pickles, copies and serializes as a plain dict.
    """

    __slots__ = ()

    def _refuse(self, *_: object, **__: object) -> NoReturn:
        raise TypeError("fact mappings are read-only; copy one with dict()")

    __setitem__ = __delitem__ = __ior__ = _refuse
    clear = pop = popitem = setdefault = update = _refuse

    def __reduce__(self) -> tuple[type[dict[str, str]], tuple[dict[str, str]]]:
        """Pickle and copy as a plain dict.

        Returns:
            tuple: ``dict`` and its argument.
        """
        return dict, (dict(self),)


EMPTY_MAPPING = FrozenDict()
"""Empty mapping shared by facts without dimensions or keys."""

_gc_lock = threading.Lock()
_gc_pauses = 0
_gc_was_enabled = False


@contextmanager
def gc_paused() -> Generator[None]:
    """Pause the cyclic garbage collector while a report's facts are built.

    Facts form no reference cycles, but millions of new tracked objects make
    the collector rescan the growing heap; pausing it halves read times of
    large reports. Nested and concurrent pauses re-enable the collector only
    when the last one ends, and only if it was enabled before the first.

    Yields:
        None: Control while the collector is paused.
    """
    global _gc_pauses, _gc_was_enabled
    with _gc_lock:
        if _gc_pauses == 0:
            _gc_was_enabled = gc.isenabled()
            gc.disable()
        _gc_pauses += 1
    try:
        yield
    finally:
        with _gc_lock:
            _gc_pauses -= 1
            if _gc_pauses == 0 and _gc_was_enabled:
                gc.enable()


@dataclass(slots=True)
class _Aggregate:
    count: int
    first_location: str


class WarningLog:
    """Collect warnings, aggregating repeated per-fact findings."""

    def __init__(self) -> None:
        """Create an empty warning log."""
        self._messages: list[str] = []
        self._aggregates: dict[str, _Aggregate] = {}

    def add(self, message: str) -> None:
        """Record one warning once."""
        if message not in self._messages:
            self._messages.append(message)

    def count(self, message: str, location: str) -> None:
        """Count one occurrence of a repeated finding."""
        aggregate = self._aggregates.get(message)
        if aggregate is None:
            self._aggregates[message] = _Aggregate(1, location)
        else:
            aggregate.count += 1

    def result(self) -> tuple[str, ...]:
        """Return the collected warnings.

        Returns:
            tuple[str, ...]: Single warnings followed by aggregated findings.
        """
        aggregated = [
            f"{message} ({aggregate.count} occurrence"
            f"{'' if aggregate.count == 1 else 's'}, "
            f"first at {aggregate.first_location})"
            for message, aggregate in self._aggregates.items()
        ]
        return (*self._messages, *aggregated)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_json_object(data: bytes, label: str) -> dict[str, Any]:
    """Parse one JSON object, rejecting duplicate keys.

    Returns:
        dict[str, Any]: Parsed object.

    Raises:
        ReportError: If the document is not a valid JSON object.
    """
    try:
        value = json.loads(
            data.decode("utf-8-sig"), object_pairs_hook=_reject_duplicate_keys
        )
    except UnicodeDecodeError as error:
        raise ReportError(f"{label}: not valid UTF-8 ({error.reason})") from error
    except json.JSONDecodeError as error:
        raise ReportError(
            f"{label}:{error.lineno}: invalid JSON ({error.msg})"
        ) from error
    except ValueError as error:
        raise ReportError(f"{label}: invalid JSON ({error})") from error
    except RecursionError as error:
        raise ReportError(f"{label}: invalid JSON (nested too deeply)") from error
    if not isinstance(value, dict):
        raise ReportError(f"{label}: expected a JSON object")
    return value


def url_scheme(url: str) -> str | None:
    """Return a URL's scheme, ``""`` for a relative reference.

    Returns:
        str | None: The scheme, or ``None`` if the URL cannot be parsed, such
        as ``http://[::1`` with an unclosed IPv6 address.
    """
    try:
        return urlsplit(url).scheme
    except ValueError:
        return None


def join_url(base: str, url: str) -> str | None:
    """Resolve a reference against a base URL.

    Returns:
        str | None: The absolute URL, or ``None`` if either cannot be parsed.
    """
    try:
        return urljoin(base, url)
    except ValueError:
        return None
