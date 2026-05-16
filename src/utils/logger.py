"""Structured logging utility for PAGER.

Wraps Python's standard logging with a clean interface that supports
structured key-value context via keyword arguments.
"""

import logging
import sys
from typing import Any


def get_logger(name: str, level: str = "INFO") -> "PAGERLogger":
    """Get a structured logger for a PAGER module.

    Args:
        name: Logger name (use __name__ in each module).
        level: Log level string (DEBUG, INFO, WARNING, ERROR).

    Returns:
        PAGERLogger instance.
    """
    return PAGERLogger(name=name, level=level)


class PAGERLogger:
    """Thin wrapper around stdlib logging with structured kwargs support.

    Allows calling logger.info("msg", key=value, key2=value2) and formats
    the kwargs as appended key=value pairs in the log message.

    This avoids Python 3.13's stricter _log() signature which rejects
    unexpected keyword arguments.
    """

    def __init__(self, name: str, level: str = "INFO") -> None:
        self._logger = logging.getLogger(name)

        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    def _fmt(self, message: str, kwargs: dict[str, Any]) -> str:
        """Format message with structured key=value pairs appended."""
        if not kwargs:
            return message
        pairs = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        return f"{message} | {pairs}"

    def debug(self, message: str, **kwargs: Any) -> None:
        self._logger.debug(self._fmt(message, kwargs))

    def info(self, message: str, **kwargs: Any) -> None:
        self._logger.info(self._fmt(message, kwargs))

    def warning(self, message: str, **kwargs: Any) -> None:
        self._logger.warning(self._fmt(message, kwargs))

    def error(self, message: str, **kwargs: Any) -> None:
        self._logger.error(self._fmt(message, kwargs))

    def critical(self, message: str, **kwargs: Any) -> None:
        self._logger.critical(self._fmt(message, kwargs))
