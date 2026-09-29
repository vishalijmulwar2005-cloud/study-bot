"""Shared FastAPI dependencies: bundle, DB session, identity, rate limits."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.exc import OperationalError

from app.bundle import ServiceBundle
from app.core.errors import AppError, ErrorCode
from app.core.security import SESSION_COOKIE_NAME, Identity, new_session_token
from app.database import get_session_factory


def get_bundle(request: Request) -> ServiceBundle:
    return request.app.state.bundle


def get_db_session():
    factory = get_session_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except OperationalError as exc:
        # Unreachable database is a temporary dependency failure (spec §12),
        # not an application bug — never leak driver details.
        db.rollback()
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_identity(request: Request) -> Identity:
    """Resolve the anonymous session identity.

    IdentityCookieMiddleware guarantees a token exists in scope state (from
    the cookie or freshly minted) and handles Set-Cookie on the response for
    new identities — including error responses. Only the SHA-256 hash of the
    token is ever persisted.
    """
    from app.core.security import SESSION_COOKIE_NAME

    token = getattr(request.state, "session_token", None) or request.cookies.get(
        SESSION_COOKIE_NAME
    )
    if not token:  # belt-and-braces; middleware normally guarantees this
        token = new_session_token()
    return Identity.from_token(token)


def rate_limit(bucket: str, limit_attr: str):
    """Dependency factory enforcing per-identity sliding-window limits."""

    def _dependency(
        request: Request,
        bundle: ServiceBundle = Depends(get_bundle),
        identity: Identity = Depends(get_identity),
    ) -> None:
        limit = getattr(bundle.settings, limit_attr)
        bundle.limiter.check(f"{bucket}:{identity.token_hash}", limit)

    return _dependency


def get_request_bundle(request: Request) -> ServiceBundle:
    bundle = getattr(request.app.state, "bundle", None)
    if bundle is None:
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE)
    return bundle
