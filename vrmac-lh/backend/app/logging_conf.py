"""Logging without PII: e-mails and bearer tokens are redacted from every record."""
from __future__ import annotations

import logging
import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*")


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        redacted = _BEARER.sub("Bearer [redacted]", _EMAIL.sub("[email redacted]", msg))
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    for h in root.handlers:
        if not any(isinstance(f, RedactFilter) for f in h.filters):
            h.addFilter(RedactFilter())
    # uvicorn access logs would contain client addresses → disabled (see Dockerfile: --no-access-log)
    logging.getLogger("uvicorn.access").disabled = True
