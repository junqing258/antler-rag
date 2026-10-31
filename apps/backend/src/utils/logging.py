from __future__ import annotations

import logging
import sys
from functools import lru_cache

from loguru import logger


def set_logger_name(record: dict) -> bool:
    """桥接日志时使用原始的标准库 logger 名称。"""
    record["name"] = record["extra"].get("logger_name", record["name"])
    return True


class InterceptHandler(logging.Handler):
    """把依赖库的标准库日志转发到 Loguru。"""

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
    """配置 Loguru，并让 Uvicorn 与依赖库的日志经由它输出。"""
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
