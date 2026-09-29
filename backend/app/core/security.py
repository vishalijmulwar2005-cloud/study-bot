"""Anonymous session identity + server-side authorization (Security spec §04).

MVP identity model:
- The API issues a random opaque session token in an HttpOnly, SameSite=Lax
  cookie ("qa_session"). Secure flag follows APP_ENV.
- Only the SHA-256 hash of the token is stored (documents.session_id,
  sessions.session_id), so a database leak does not leak usable tokens.
- Client-supplied IDs are identifiers, never proof of permission: every
  document-scoped operation re-resolves ownership from the cookie.

Cross-owner access returns 404 (existence hidden) per Security §11
"Generic 403/404 behavior" — this also satisfies acceptance TEST 6.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from app.core.errors import AppError, ErrorCode

SESSION_COOKIE_NAME = "qa_session"


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Identity:
    """Resolved request identity for the anonymous MVP."""

    token: str
    token_hash: str

    @classmethod
    def from_token(cls, token: str) -> "Identity":
        return cls(token=token, token_hash=hash_token(token))

    def owns(self, owner_hash: str | None) -> bool:
        return owner_hash is not None and owner_hash == self.token_hash


def identity_from_token(token: str) -> Identity:
    return Identity.from_token(token)


def ensure_owner_or_404(identity: Identity, owner_hash: str | None, resource: str) -> None:
    """Deny with 404 (hidden) when the identity does not own the resource.

    Authenticated users are an open product decision (docs/DECISIONS.md #7);
    the user_id columns exist but the MVP authorization boundary is the
    session token.
    """
    if not identity.owns(owner_hash):
        # Existence-hidden denial: do not reveal foreign resources.
        raise AppError(ErrorCode.NOT_FOUND, f"{resource} not found")


class IdentityCookieMiddleware:
    """Ensures consistent anonymous identity behavior (audit fix B-3).

    Every request gets a session token (from the cookie, or a freshly minted
    one stored in scope state), and every response — 200, 404, 422, 429, 500 —
    sets the cookie when a new token was minted. Only the SHA-256 hash of the
    token is ever persisted; the raw token exists only in the cookie.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = _token_from_cookie(scope)
        minted = None
        if not token:
            token = new_session_token()
            minted = token
        scope.setdefault("state", {})
        scope["state"]["session_token"] = token

        async def send_with_cookie(message):
            if minted and message["type"] == "http.response.start":
                from app.config import get_settings

                secure = get_settings().app_env != "development"
                cookie = (
                    f"{SESSION_COOKIE_NAME}={minted}; HttpOnly; Path=/; "
                    f"SameSite=lax; Max-Age=2592000"
                )
                if secure:
                    cookie += "; Secure"
                message["headers"] = list(message.get("headers", [])) + [
                    (b"set-cookie", cookie.encode("ascii"))
                ]
            await send(message)

        await self.app(scope, receive, send_with_cookie)


def _token_from_cookie(scope) -> str | None:
    from http.cookies import SimpleCookie

    headers = dict(scope.get("headers") or [])
    raw = headers.get(b"cookie")
    if not raw:
        return None
    try:
        jar = SimpleCookie()
        jar.load(raw.decode("latin-1"))
        morsel = jar.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel else None
    except Exception:  # noqa: BLE001 — malformed cookies must not break requests
        return None
