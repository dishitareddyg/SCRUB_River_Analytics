"""FastAPI application entrypoint and application factory.

Run locally with:

    uvicorn app.main:app --reload

This module is intentionally the only place that wires together
configuration, logging, middleware, exception handling, routers, and
startup/shutdown behavior. Future modules should extend the system by
adding routers (see :mod:`app.api.routes`) or database models rather
than modifying this file's structure.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import api_router
from app.config.constants import OPENAPI_DESCRIPTION, OPENAPI_TITLE
from app.config.settings import get_settings
from app.database.db import check_database_connection, dispose_engine
from app.utils.exceptions import ApplicationError
from app.utils.logger import configure_logging, get_logger
from app.utils.response import ErrorDetail, ErrorResponse

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown events.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control back to FastAPI while the application is running.
    """
    logger.info(f"Starting {settings.app_name} v{settings.app_version} "
                f"[{settings.environment}]")

    if check_database_connection():
        logger.info("Database connectivity check succeeded.")
    else:
        logger.warning(
            "Database connectivity check failed at startup. "
            "The API will still start; endpoints requiring the "
            "database may report degraded health."
        )

    yield

    logger.info("Shutting down application...")
    dispose_engine()
    logger.info("Shutdown complete.")


def create_application() -> FastAPI:
    """Build and configure the FastAPI application instance.

    This is the application factory. Keeping construction in a
    function (rather than at import time) makes the app easy to
    reconstruct in tests with different settings/overrides.

    Returns:
        A fully configured :class:`FastAPI` instance.
    """
    application = FastAPI(
        title=OPENAPI_TITLE,
        description=OPENAPI_DESCRIPTION,
        version=settings.app_version,
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    _register_middleware(application)
    _register_exception_handlers(application)
    _register_routers(application)

    return application


def _register_middleware(application: FastAPI) -> None:
    """Attach CORS and request-logging middleware.

    Args:
        application: The FastAPI application instance to configure.
    """
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def log_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Log every incoming HTTP request with timing information.

        Args:
            request: The incoming request.
            call_next: The next handler in the middleware chain.

        Returns:
            The response produced by downstream handlers.
        """
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            f'{request.method} {request.url.path} '
            f'status={response.status_code} duration_ms={duration_ms:.2f}'
        )
        return response


def _register_exception_handlers(application: FastAPI) -> None:
    """Register global exception handlers.

    Args:
        application: The FastAPI application instance to configure.
    """

    @application.exception_handler(ApplicationError)
    async def handle_application_error(
        request: Request, exc: ApplicationError
    ) -> JSONResponse:
        """Translate application-specific errors into a JSON envelope.

        Args:
            request: The request during which the error occurred.
            exc: The raised :class:`ApplicationError` (or subclass).

        Returns:
            A JSON response using the standard :class:`ErrorResponse`
            envelope.
        """
        logger.error(f"{exc.__class__.__name__} on {request.url.path}: {exc.message}")
        payload = ErrorResponse(
            error=ErrorDetail(type=exc.__class__.__name__, message=exc.message)
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=payload.model_dump(mode="json"),
        )

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Normalize FastAPI/Pydantic request-validation failures.

        Without this handler, invalid query/path/body parameters
        (e.g. an unparseable date, a value outside its declared
        range) would produce FastAPI's default
        ``{"detail": [...]}`` body instead of this API's standard
        envelope. Every field-level problem is preserved in
        ``error.context.errors``.

        Args:
            request: The request during which validation failed.
            exc: The raised :class:`RequestValidationError`.

        Returns:
            A JSON response using the standard :class:`ErrorResponse`
            envelope with HTTP 422.
        """
        logger.warning(f"Request validation failed on {request.url.path}: {exc.errors()}")
        sanitized_errors = [
            {"loc": list(error.get("loc", [])), "msg": error.get("msg", ""), "type": error.get("type", "")}
            for error in exc.errors()
        ]
        payload = ErrorResponse(
            error=ErrorDetail(
                type="RequestValidationError",
                message="One or more request parameters failed validation.",
                context={"errors": sanitized_errors},
            )
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=payload.model_dump(mode="json"),
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all handler for unexpected, unhandled exceptions.

        Ensures API clients always receive the standard error
        envelope instead of a raw traceback, while the full details
        are still captured in the error log.

        Args:
            request: The request during which the error occurred.
            exc: The unhandled exception.

        Returns:
            A JSON response using the standard :class:`ErrorResponse`
            envelope with HTTP 500.
        """
        logger.exception(f"Unhandled exception on {request.url.path}: {exc}")
        payload = ErrorResponse(
            error=ErrorDetail(
                type="InternalServerError",
                message="An unexpected error occurred. Please try again later.",
            )
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=payload.model_dump(mode="json"),
        )


def _register_routers(application: FastAPI) -> None:
    """Mount the versioned API router.

    Args:
        application: The FastAPI application instance to configure.
    """
    application.include_router(api_router, prefix=settings.api_v1_prefix)


app = create_application()
