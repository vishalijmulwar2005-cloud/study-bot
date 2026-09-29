"""EmbeddingService abstraction (Phase 2).

Default implementation targets any OpenAI-compatible /embeddings endpoint.
The service raises ProviderUnavailable when unconfigured or unreachable —
the caller converts that into the safe 503 / FAILED job paths. There is no
fallback "fake" embedding in the production path.

Provider resilience (Phase 7): transient failures (429/5xx, network errors,
timeouts) are retried up to 3 times with exponential backoff; invalid
requests (other 4xx) fail immediately without retry.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import httpx

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger, log_event

logger = get_logger("app.embeddings")

# Statuses worth retrying; anything else (400/401/403/404/413/415/422) fails fast.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_PROVIDER_ATTEMPTS = 3
PROVIDER_RETRY_BASE_DELAY = 0.75  # seconds; exponential (0.75, 1.5)


class ProviderUnavailable(AppError):
    """Embedding/LLM provider missing or unreachable (never leaks details)."""

    def __init__(self, code: str = ErrorCode.SERVICE_UNAVAILABLE, message: str | None = None):
        super().__init__(code, message)


class EmbeddingDimensionMismatch(Exception):
    """The provider returned vectors whose size differs from EMBEDDING_DIM."""


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict,
    max_attempts: int = MAX_PROVIDER_ATTEMPTS,
    base_delay: float = PROVIDER_RETRY_BASE_DELAY,
) -> httpx.Response:
    """POST with bounded exponential backoff for transient failures.

    Retries: 429/500/502/503/504 and connection errors. Never retries other
    client errors (invalid request). Returns the final response; raises the
    last transport error when retries are exhausted.
    """
    for attempt in range(max_attempts):
        try:
            response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError:
            if attempt == max_attempts - 1:
                raise
        else:
            if (
                response.status_code not in RETRYABLE_STATUS_CODES
                or attempt == max_attempts - 1
            ):
                return response
        await asyncio.sleep(base_delay * (2**attempt))
    raise RuntimeError("retry loop exhausted")  # pragma: no cover


class EmbeddingService(ABC):
    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts; order is preserved."""

    @property
    @abstractmethod
    def configured(self) -> bool: ...


class OpenAICompatibleEmbedding(EmbeddingService):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        dim: int,
        batch_size: int = 64,
        timeout_seconds: int = 60,
        transport: httpx.AsyncBaseTransport | None = None,
        request_dimensions: int | None = None,
        max_attempts: int = MAX_PROVIDER_ATTEMPTS,
        retry_base_delay: float = PROVIDER_RETRY_BASE_DELAY,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim
        self.batch_size = max(1, batch_size)
        self.timeout_seconds = timeout_seconds
        self._transport = transport  # injectable for tests only
        self._request_dimensions = request_dimensions
        self.max_attempts = max_attempts
        self.retry_base_delay = retry_base_delay

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.configured:
            raise ProviderUnavailable(ErrorCode.EMBEDDING_NOT_CONFIGURED)
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self._transport) as client:
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start : start + self.batch_size]
                payload: dict = {"model": self.model, "input": batch}
                if self._request_dimensions is not None:
                    payload["dimensions"] = self._request_dimensions
                try:
                    response = await post_with_retry(
                        client,
                        f"{self.base_url}/embeddings",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        payload=payload,
                        max_attempts=self.max_attempts,
                        base_delay=self.retry_base_delay,
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    log_event(
                        logger,
                        "embedding provider error",
                        level=40,
                        detail=exc.__class__.__name__,
                    )
                    raise ProviderUnavailable(ErrorCode.EMBEDDING_NOT_CONFIGURED) from exc
                payload = response.json()
                data = payload.get("data", [])
                if len(data) != len(batch):
                    raise ProviderUnavailable(ErrorCode.EMBEDDING_NOT_CONFIGURED)
                # Sort by index defensively; providers return unordered batches.
                ordered = sorted(data, key=lambda item: item.get("index", 0))
                for item in ordered:
                    vector = item.get("embedding")
                    if not isinstance(vector, list) or len(vector) != self.dim:
                        raise EmbeddingDimensionMismatch(
                            f"expected dim {self.dim}, got {len(vector) if isinstance(vector, list) else 'unknown'}"
                        )
                    vectors.append([float(x) for x in vector])
        return vectors
