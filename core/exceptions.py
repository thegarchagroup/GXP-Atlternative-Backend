"""Structured error responses: {"error": {"code", "message", "details"}}."""
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

logger = logging.getLogger("hrm.errors")


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, details=None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class WorkflowError(AppError):
    """An invalid state transition or unmet workflow condition."""
    status_code = 409
    code = "INVALID_TRANSITION"


class ValidationFailedError(AppError):
    status_code = 422
    code = "VALIDATION_FAILED"


class TooManyRequestsError(AppError):
    status_code = 429
    code = "TOO_MANY_REQUESTS"


def _body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details), headers=headers)

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException):
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)), headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in err.get("loc", []) if p != "body"), "message": err.get("msg")}
            for err in exc.errors()
        ]
        return JSONResponse(status_code=422, content=_body("VALIDATION_FAILED", "The request contains invalid data.", details))

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, __: StaleDataError):
        return JSONResponse(
            status_code=409,
            content=_body("CONCURRENT_UPDATE", "This record was changed by someone else. Reload and try again."),
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError):
        logger.warning("Integrity error: %s", exc.orig)
        return JSONResponse(status_code=409, content=_body("CONFLICT", "The change conflicts with existing data."))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content=_body("INTERNAL_ERROR", "An unexpected error occurred."))
