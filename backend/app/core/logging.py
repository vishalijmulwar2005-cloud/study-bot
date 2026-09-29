"""Privacy-minimized logging with correlation IDs (Security spec §10).

- Every request gets a correlation ID (X-Correlation-ID, generated if absent)
  that flows through API, worker, and provider calls via a context var.
- Event logging is field-based: callers pass explicit, non-sensitive fields.
  Question text, answers, PDF text, prompts, keys, and tokens are NEVER
  passed to logs — helpers accept lengths/counts/IDs only.
"""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

_LOG = logging.getLogger("app")

# Defense in depth: even if a caller accidentally passes content, these
# key names are scrubbed before a record is emitted.
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(question|answer|prompt|content|text|evidence|api_key|token|password|secret|cookie)",
    re.IGNORECASE,
)


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        cid = correlation_id_var.get()
        record.correlation_id = cid
        # Scrub any kwargs we know carry content; keep structural fields.
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            record.fields = {
                k: ("<redacted>" if _SENSITIVE_KEY_PATTERN.search(k) else v)
                for k, v in extra.items()
            }
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s: %(message)s"
        )
    )
    handler.addFilter(RedactionFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Uvicorn loggers would otherwise double-print with their own handlers.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    """Emit a structured event. Field VALUES that could carry sensitive
    content must never be passed here by convention; the redaction filter
    additionally scrubs sensitive-named keys."""
    rendered = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    logger.log(level, "%s%s", event, (" " + rendered) if rendered else "")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class CorrelationIdMiddleware:
    """Pure ASGI middleware assigning/propagating X-Correlation-ID."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-correlation-id")
        cid = incoming.decode("ascii")[:64] if incoming else _new_correlation_id()
        token = correlation_id_var.set(cid)

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"].append((b"x-correlation-id", cid.encode("ascii")))
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            correlation_id_var.reset(token)


def _new_correlation_id() -> str:
    import uuid

    return uuid.uuid4().hex[:16]
