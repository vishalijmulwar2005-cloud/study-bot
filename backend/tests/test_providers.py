"""Provider wrapper tests using httpx mock transports (no network, no keys).

Verifies the honest-failure contract: provider outages surface as safe 503s
and dimension mismatches are detected before vectors reach the database.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.errors import ErrorCode
from app.services.embeddings import (
    EmbeddingDimensionMismatch,
    OpenAICompatibleEmbedding,
    ProviderUnavailable,
)
from app.services.llm import OpenAICompatibleLLM


def _embedding_response(vectors: list[list[float]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]},
        request=httpx.Request("POST", "https://provider.test/v1/embeddings"),
    )


def run(coro):
    return asyncio.run(coro)


class TestEmbeddingProvider:
    def test_happy_path_returns_ordered_vectors(self):
        vec = [[0.1] * 8, [0.2] * 8]

        def handler(request: httpx.Request) -> httpx.Response:
            return _embedding_response(vec)

        service = OpenAICompatibleEmbedding(
            api_key="k", base_url="https://provider.test/v1",
            model="m", dim=8, transport=httpx.MockTransport(handler),
        )
        result = run(service.embed_texts(["a", "b"]))
        assert result == vec

    def test_unconfigured_raises_not_configured(self):
        service = OpenAICompatibleEmbedding(
            api_key="", base_url="https://x/v1", model="m", dim=8
        )
        with pytest.raises(ProviderUnavailable) as exc:
            run(service.embed_texts(["a"]))
        assert exc.value.code == ErrorCode.EMBEDDING_NOT_CONFIGURED

    def test_provider_500_maps_to_safe_503(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, request=request)

        service = OpenAICompatibleEmbedding(
            api_key="k", base_url="https://x/v1", model="m", dim=8,
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderUnavailable) as exc:
            run(service.embed_texts(["a"]))
        assert exc.value.http_status == 503

    def test_dimension_mismatch_detected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _embedding_response([[0.1] * 3])

        service = OpenAICompatibleEmbedding(
            api_key="k", base_url="https://x/v1", model="m", dim=1536,
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(EmbeddingDimensionMismatch):
            run(service.embed_texts(["a"]))


class TestLLMProvider:
    def test_happy_path_returns_content(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "A grounded answer."}}]},
                request=httpx.Request("POST", "https://provider.test/v1/chat/completions"),
            )

        service = OpenAICompatibleLLM(
            api_key="k", base_url="https://provider.test/v1", model="m",
            transport=httpx.MockTransport(handler),
        )
        assert (
            run(service.complete([{"role": "user", "content": "q"}], 100))
            == "A grounded answer."
        )

    def test_unconfigured_raises_not_configured(self):
        service = OpenAICompatibleLLM(api_key="", base_url="https://x/v1", model="m")
        with pytest.raises(ProviderUnavailable) as exc:
            run(service.complete([{"role": "user", "content": "q"}], 100))
        assert exc.value.code == ErrorCode.LLM_NOT_CONFIGURED
        assert exc.value.http_status == 503

    def test_provider_error_maps_to_safe_503(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, request=request)

        service = OpenAICompatibleLLM(
            api_key="k", base_url="https://x/v1", model="m",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderUnavailable) as exc:
            run(service.complete([{"role": "user", "content": "q"}], 100))
        assert exc.value.code == ErrorCode.LLM_PROVIDER_FAILED

    def test_malformed_payload_maps_to_safe_503(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": True}, request=request)

        service = OpenAICompatibleLLM(
            api_key="k", base_url="https://x/v1", model="m",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderUnavailable):
            run(service.complete([{"role": "user", "content": "q"}], 100))

    def test_empty_content_maps_to_safe_503(self):
        # Reasoning models can return empty content when the token budget is
        # consumed by the hidden reasoning channel. This must stay an honest
        # 503 (retryable), never the no-evidence product answer.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": ""}}]},
                request=request,
            )

        service = OpenAICompatibleLLM(
            api_key="k", base_url="https://x/v1", model="m",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderUnavailable):
            run(service.complete([{"role": "user", "content": "q"}], 100))


class TestProviderRetryBackoff:
    """Phase 7: transient failures retry with backoff; invalid ones fail fast."""

    def _embedding(self, handler) -> OpenAICompatibleEmbedding:
        return OpenAICompatibleEmbedding(
            api_key="k", base_url="https://x/v1", model="m", dim=8,
            transport=httpx.MockTransport(handler),
            retry_base_delay=0.01,  # keep tests fast
        )

    def test_429_then_success_recovers(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, request=request)
            return _embedding_response([[0.5] * 8])

        service = self._embedding(handler)
        result = run(service.embed_texts(["a"]))
        assert result == [[0.5] * 8]
        assert calls["n"] == 2

    def test_persistent_429_exhausts_retries(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, request=request)

        service = self._embedding(handler)
        with pytest.raises(ProviderUnavailable) as exc:
            run(service.embed_texts(["a"]))
        assert exc.value.http_status == 503
        assert calls["n"] == 3  # bounded: no infinite retry

    def test_invalid_request_not_retried(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, request=request)

        service = self._embedding(handler)
        with pytest.raises(ProviderUnavailable):
            run(service.embed_texts(["a"]))
        assert calls["n"] == 1  # fail fast on non-transient errors

    def test_5xx_then_success_recovers(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(502, request=request)
            return _embedding_response([[0.5] * 8])

        service = self._embedding(handler)
        assert run(service.embed_texts(["a"])) == [[0.5] * 8]

    def test_llm_retries_transient_failure(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, request=request)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "recovered"}}]},
                request=request,
            )

        service = OpenAICompatibleLLM(
            api_key="k", base_url="https://x/v1", model="m",
            transport=httpx.MockTransport(handler), retry_base_delay=0.01,
        )
        assert (
            run(service.complete([{"role": "user", "content": "q"}], 10))
            == "recovered"
        )
        assert calls["n"] == 2

    def test_network_error_then_success_recovers(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("boom", request=request)
            return _embedding_response([[0.5] * 8])

        service = self._embedding(handler)
        assert run(service.embed_texts(["a"])) == [[0.5] * 8]
