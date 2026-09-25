from __future__ import annotations

import logging

from uvicorn.logging import DefaultFormatter


def configure_logging() -> logging.Logger:
    """Configure development console logs with colored severity prefixes."""
    formatter = DefaultFormatter(
        "%(asctime)s %(levelprefix)s %(name)s %(message)s",
        use_colors=True,
    )
    formatter.default_msec_format = "%s.%03d"
    for name in ("antler_rag", "uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        target.handlers = []
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        target.addHandler(handler)
        target.setLevel(logging.INFO)
        target.propagate = False
    return logging.getLogger("antler_rag")
