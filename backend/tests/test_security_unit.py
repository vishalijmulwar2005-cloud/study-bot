"""Security unit tests: identity hashing, ownership denial, rate limiting,
storage path traversal (Phase 20)."""

from __future__ import annotations

import pytest

from app.core.errors import AppError, ErrorCode
from app.core.security import (
    ensure_owner_or_404,
    hash_token,
    identity_from_token,
    new_session_token,
)
from app.services.storage import LocalFileStorage, StorageError


class TestIdentity:
    def test_token_hashing_roundtrip(self):
        token = new_session_token()
        identity = identity_from_token(token)
        assert identity.token_hash == hash_token(token)
        assert identity.owns(identity.token_hash)

    def test_foreign_identity_denied_with_404(self):
        alice = identity_from_token(new_session_token())
        bob = identity_from_token(new_session_token())
        assert not bob.owns(alice.token_hash)
        with pytest.raises(AppError) as exc:
            ensure_owner_or_404(bob, alice.token_hash, "document")
        assert exc.value.code == ErrorCode.NOT_FOUND  # existence hidden
        assert exc.value.http_status == 404

    def test_missing_owner_hash_denied(self):
        alice = identity_from_token(new_session_token())
        with pytest.raises(AppError):
            ensure_owner_or_404(alice, None, "document")

    def test_tokens_are_unique_and_unguessable(self):
        tokens = {new_session_token() for _ in range(50)}
        assert len(tokens) == 50
        assert all(len(t) >= 32 for t in tokens)


class TestRateLimiter:
    def test_blocks_after_limit(self, limiter):
        for _ in range(5):
            limiter.check("chat:key", 5)
        with pytest.raises(AppError) as exc:
            limiter.check("chat:key", 5)
        assert exc.value.code == ErrorCode.RATE_LIMITED
        assert exc.value.http_status == 429

    def test_buckets_are_independent(self, limiter):
        for _ in range(5):
            limiter.check("upload:a", 5)
        limiter.check("chat:a", 5)  # different bucket, must not be blocked

    def test_keys_are_isolated(self, limiter):
        for _ in range(5):
            limiter.check("upload:a", 5)
        limiter.check("upload:b", 5)  # different identity, not blocked


class TestLocalStorage:
    def test_save_load_delete_roundtrip(self, tmp_path):
        storage = LocalFileStorage(tmp_path / "store")
        key = storage.save(b"pdf-bytes")
        assert storage.load(key) == b"pdf-bytes"
        storage.delete(key)
        storage.delete(key)  # idempotent
        with pytest.raises(StorageError):
            storage.load(key)

    def test_path_traversal_rejected(self, tmp_path):
        storage = LocalFileStorage(tmp_path / "store")
        with pytest.raises(StorageError):
            storage.load("../secret.txt")
        with pytest.raises(StorageError):
            storage.load("sub/dir/file")


class TestIdentityCookieMiddleware:
    """B-3: cookie must be set on ALL responses for new identities."""

    @staticmethod
    def _app():
        from fastapi import FastAPI

        from app.core.errors import AppError, ErrorCode, install_error_handlers
        from app.core.security import IdentityCookieMiddleware

        app = FastAPI()
        app.add_middleware(IdentityCookieMiddleware)

        @app.get("/ok")
        def ok():
            return {"fine": True}

        @app.get("/boom")
        def boom():
            raise AppError(ErrorCode.NOT_FOUND)

        install_error_handlers(app)
        return app

    def test_cookie_set_on_success_and_error(self):
        from fastapi.testclient import TestClient

        app = self._app()
        with TestClient(app) as first_visit:
            ok = first_visit.get("/ok")
            assert ok.status_code == 200
            cookie_ok = ok.headers.get("set-cookie", "")
            assert "qa_session=" in cookie_ok
            assert "HttpOnly" in cookie_ok
            assert "SameSite=lax" in cookie_ok
        with TestClient(app) as error_visit:  # fresh identity, hits an error first
            boom = error_visit.get("/boom")
            assert boom.status_code == 404
            cookie_err = boom.headers.get("set-cookie", "")
            assert "qa_session=" in cookie_err, "error response must establish identity"

    def test_existing_identity_not_reset(self):
        from fastapi.testclient import TestClient

        app = self._app()
        with TestClient(app) as client:
            token = "known-token-value_1"
            response = client.get("/ok", headers={"Cookie": f"qa_session={token}"})
            assert response.status_code == 200
            assert "set-cookie" not in response.headers

    def test_token_hash_never_in_response(self):
        from fastapi.testclient import TestClient

        app = self._app()
        with TestClient(app) as client:
            response = client.get("/ok")
            assert "sha256" not in response.text.lower()


class TestConfigValidation:
    def test_embedding_dimensions_mismatch_fails_fast(self):
        from app.config import Settings

        with pytest.raises(Exception) as exc:
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                embedding_dim=1536,
                embedding_dimensions=768,
            )
        assert "EMBEDDING_DIMENSIONS" in str(exc.value)

    def test_matching_dimensions_accepted(self):
        from app.config import Settings

        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            embedding_dim=768,
            embedding_dimensions=768,
        )
        assert settings.embedding_dimensions == 768
