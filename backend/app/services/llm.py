"""LLMService abstraction (Phase 2).

Default implementation targets any OpenAI-compatible /chat/completions
endpoint. The LLM receives fully constructed messages (see services/prompts.py)
and returns answer text only — it never produces the source metadata the UI
renders (Phase 10: sources are validated server-side from retrieval).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.core.errors import ErrorCode
from app.core.logging import get_logger, log_event
from app.services.embeddings import (
    MAX_PROVIDER_ATTEMPTS,
    PROVIDER_RETRY_BASE_DELAY,
    ProviderUnavailable,
    post_with_retry,
)

logger = get_logger("app.llm")


class LLMService(ABC):
    @abstractmethod
    async def complete(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        """Return the assistant answer text for the given message list."""

    @property
    @abstractmethod
    def configured(self) -> bool: ...


class OpenAICompatibleLLM(LLMService):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int = 60,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = MAX_PROVIDER_ATTEMPTS,
        retry_base_delay: float = PROVIDER_RETRY_BASE_DELAY,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._transport = transport  # injectable for tests only
        self.max_attempts = max_attempts
        self.retry_base_delay = retry_base_delay

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def complete(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        if not self.configured:
            raise ProviderUnavailable(ErrorCode.LLM_NOT_CONFIGURED)
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = await post_with_retry(
                    client,
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    payload={
                        "model": self.model,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": 0.2,
                    },
                    max_attempts=self.max_attempts,
                    base_delay=self.retry_base_delay,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            log_event(logger, "llm provider error", level=40, detail=exc.__class__.__name__)
            raise ProviderUnavailable(ErrorCode.LLM_PROVIDER_FAILED) from exc
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailable(ErrorCode.LLM_PROVIDER_FAILED) from exc
        if not isinstance(content, str) or not content.strip():
            # Reasoning models can spend the whole token budget in a hidden
            # reasoning channel and answer with empty content (often with
            # finish_reason=length). That is a provider malfunction, not
            # "evidence missing" — surface the honest 503 instead of letting
            # the caller disguise it as the no-evidence product response.
            log_event(logger, "llm returned empty content", level=30)
            raise ProviderUnavailable(ErrorCode.LLM_PROVIDER_FAILED)
        return content
