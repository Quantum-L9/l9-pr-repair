from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

_LOGGER_NAME = "pr_repair"

# Decoupled fan-out for structured events. Sinks (e.g. the trace recorder) register
# here so they receive every log_event without logging.py depending on them.
EventSink = Callable[[str, dict[str, Any]], None]
_EVENT_SINKS: list[EventSink] = []


def add_event_sink(sink: EventSink) -> None:
    # Idempotent registration: registering the same sink twice (e.g. start()
    # called more than once) must not double-fan-out events to it.
    if sink not in _EVENT_SINKS:
        _EVENT_SINKS.append(sink)


def remove_event_sink(sink: EventSink) -> None:
    # Remove every occurrence so a sink is reliably detached even if it had
    # somehow been registered more than once; stopping must be complete.
    while sink in _EVENT_SINKS:
        _EVENT_SINKS.remove(sink)


def configure_logging(level: str = "INFO") -> logging.Logger:
    """
    Configure and return the package logger.

    This module intentionally uses stdlib logging so the local-first pipeline
    works in Cursor without assuming repo-level structlog bootstrap.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        logger.setLevel(level.upper())
        return logger

    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    """Return the configured pipeline logger."""
    return logging.getLogger(_LOGGER_NAME)


def log_event(event: str, **fields: Any) -> None:
    """
    Emit a structured key=value log line.

    Secrets must be masked before being passed here.
    """
    logger = get_logger()
    payload = " ".join(f"{key}={value!r}" for key, value in sorted(fields.items()))
    logger.info("%s %s", event, payload)
    for sink in _EVENT_SINKS:
        # Deliberately broad: a registered sink is third-party code and must
        # never break the pipeline's logging, so any failure it raises is
        # reported and stepped over. Exception rather than BaseException keeps
        # KeyboardInterrupt and cancellation propagating.
        # nosemgrep: l9.baseline.python.broad-except
        try:
            sink(event, fields)
        except Exception:
            logger.exception("event sink failed for %s", event)
