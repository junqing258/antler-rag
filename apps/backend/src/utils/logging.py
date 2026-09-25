from __future__ import annotations

import logging
import sys
from functools import lru_cache

from loguru import logger


def set_logger_name(record: dict) -> bool:
    """Use the original standard-library logger name when a record is bridged."""
    record["name"] = record["extra"].get("logger_name", record["name"])
    return True


class InterceptHandler(logging.Handler):
    """Forward standard-library logs from dependencies to Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.bind(logger_name=record.name).opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


@lru_cache(maxsize=1)
def configure_logging():
    """Configure Loguru and route Uvicorn and dependency logs through it."""
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        colorize=True,
        filter=set_logger_name,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
            "<level>{level: <8}</level> "
            "<cyan>{name}</cyan> "
            "<level>{message}</level>"
        ),
    )

    handler = InterceptHandler()
    logging.basicConfig(handlers=[handler], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        target.handlers = [handler]
        target.propagate = False
    return logger
