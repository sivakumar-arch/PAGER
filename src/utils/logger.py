"""PAGER structured logging utility.

Provides a consistent logging interface across all PAGER components.
Outputs structured JSON in production mode for log aggregation systems
(e.g. ELK, Datadog) and plain text in development mode.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class StructuredFormatter(logging.Formatter):
    """JSON log formatter for structured/machine-readable output."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include extra fields attached to the log record
        extra_fields = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "taskName",
            }
        }
        if extra_fields:
            log_entry["context"] = extra_fields

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def get_logger(
    name: str,
    level: str = "INFO",
    structured: bool = False,
) -> logging.Logger:
    """Get a configured PAGER logger.

    Args:
        name: Logger name — use __name__ in each module.
        level: Log level string: DEBUG | INFO | WARNING | ERROR.
        structured: If True, output JSON. If False, output plain text.

    Returns:
        Configured Logger instance.

    Example:
        logger = get_logger(__name__)
        logger.info("Agent selected", extra={"agent_id": "labs_agent"})
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if logger already configured
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)

    if structured:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    logger.addHandler(handler)
    logger.propagate = False

    return logger
