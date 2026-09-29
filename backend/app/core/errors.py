"""Canonical API error model (Database & API Specification §12, Security §11).

Every client-visible failure is an AppError carrying a stable code and a
human-readable message. Nothing else ever escapes to the client: FastAPI
exception handlers convert unexpected exceptions into a generic 500 and log
the details only to protected logs.
"""

from __future__ import annotations

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(str):
    INVALID_REQUEST = "INVALID_REQUEST"          # 400
    UNAUTHENTICATED = "UNAUTHENTICATED"          # 401
    FORBIDDEN = "FORBIDDEN"                      # 403
    NOT_FOUND = "NOT_FOUND"                      # 404
    FILE_TOO_LARGE = "FILE_TOO_LARGE"            # 413
    UNSUPPORTED_MEDIA = "UNSUPPORTED_MEDIA"      # 415
    INVALID_PDF = "INVALID_PDF"                  # 422
    RATE_LIMITED = "RATE_LIMITED"                # 429
    INTERNAL_ERROR = "INTERNAL_ERROR"            # 500
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"  # 503

    # Processing failure codes (stored on documents/jobs, surfaced safely)
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    OCR_UNAVAILABLE = "OCR_UNAVAILABLE"
    EMBEDDING_NOT_CONFIGURED = "EMBEDDING_NOT_CONFIGURED"
    LLM_NOT_CONFIGURED = "LLM_NOT_CONFIGURED"
    LLM_PROVIDER_FAILED = "LLM_PROVIDER_FAILED"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    DELETION_FAILED = "DELETION_FAILED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


_HTTP_STATUS: dict[str, int] = {
    ErrorCode.INVALID_REQUEST: status.HTTP_400_BAD_REQUEST,
    ErrorCode.UNAUTHENTICATED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    # Starlette renamed these constants; support both spellings.
    ErrorCode.FILE_TOO_LARGE: getattr(
        status, "HTTP_413_CONTENT_TOO_LARGE", 413
    ),
    ErrorCode.UNSUPPORTED_MEDIA: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    ErrorCode.INVALID_PDF: getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
    ErrorCode.RATE_LIMITED: status.HTTP_429_TOO_MANY_REQUESTS,
    ErrorCode.INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCode.SERVICE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    # Processing codes surface as 422 on the API that triggered them.
    ErrorCode.EXTRACTION_FAILED: getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
    ErrorCode.OCR_UNAVAILABLE: getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
    ErrorCode.EMBEDDING_NOT_CONFIGURED: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.LLM_NOT_CONFIGURED: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.LLM_PROVIDER_FAILED: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.EMPTY_DOCUMENT: getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
    ErrorCode.DELETION_FAILED: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCode.STORAGE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
}

# Client-facing messages per Security §11 — no internals, no exception text.
_DEFAULT_MESSAGES: dict[str, str] = {
    ErrorCode.INVALID_REQUEST: "The request is malformed or missing a required field.",
    ErrorCode.UNAUTHENTICATED: "Authentication is required.",
    ErrorCode.FORBIDDEN: "You do not have access to this resource.",
    ErrorCode.NOT_FOUND: "The requested resource was not found.",
    ErrorCode.FILE_TOO_LARGE: "The uploaded file exceeds the configured size limit.",
    ErrorCode.UNSUPPORTED_MEDIA: "The uploaded file type is not supported. Please upload a PDF.",
    ErrorCode.INVALID_PDF: "The uploaded file is not a supported PDF.",
    ErrorCode.RATE_LIMITED: "Too many requests. Please slow down and try again shortly.",
    ErrorCode.INTERNAL_ERROR: "An unexpected error occurred. Please try again.",
    ErrorCode.SERVICE_UNAVAILABLE: "The service is temporarily unavailable. Please try again.",
    ErrorCode.EXTRACTION_FAILED: "We couldn't process this PDF. Please try again.",
    ErrorCode.OCR_UNAVAILABLE: (
        "This PDF appears to be scanned (image-only) and text could not be extracted. "
        "OCR is not enabled for this deployment; please upload a text-based PDF."
    ),
    ErrorCode.EMBEDDING_NOT_CONFIGURED: (
        "The processing service is not fully configured (embedding provider missing). "
        "Contact the operator or set the embedding credentials."
    ),
    ErrorCode.LLM_NOT_CONFIGURED: (
        "The answer service is temporarily unavailable (LLM provider not configured)."
    ),
    ErrorCode.LLM_PROVIDER_FAILED: (
        "AI service is temporarily unavailable. Please try again."
    ),
    ErrorCode.EMPTY_DOCUMENT: "This PDF does not contain extractable text.",
    ErrorCode.DELETION_FAILED: "The document could not be deleted. Please try again.",
    ErrorCode.STORAGE_UNAVAILABLE: (
        "The document storage is temporarily unavailable. Please try again."
    ),
}


class AppError(Exception):
    """An error that is safe (and intended) to surface to the client."""

    def __init__(self, code: str, message: str | None = None, http_status: int | None = None):
        self.code = code
        self.message = message or _DEFAULT_MESSAGES.get(code, ErrorCode.INTERNAL_ERROR)
        self.http_status = http_status or _HTTP_STATUS.get(code, 500)
        super().__init__(self.message)

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.http_status,
            content={"error": {"code": self.code, "message": self.message}},
        )


def install_error_handlers(app) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return exc.to_response()

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return AppError(ErrorCode.INVALID_REQUEST).to_response()

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # Details stay in protected logs only; the client gets a generic message.
        import logging

        logging.getLogger("app.errors").exception(
            "unhandled exception on %s %s", request.method, request.url.path
        )
        return AppError(ErrorCode.INTERNAL_ERROR).to_response()
