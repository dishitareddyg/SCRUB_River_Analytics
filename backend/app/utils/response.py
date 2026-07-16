"""Reusable, standardized API response models.

Every endpoint in the platform should respond using one of these
envelope models so that the React dashboard can rely on a single,
predictable response shape across all versions and modules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

from app.config.constants import API_VERSION_1

DataT = TypeVar("DataT")


def _utc_now() -> datetime:
    """Return the current UTC timestamp.

    Returns:
        A timezone-aware :class:`datetime` in UTC.
    """
    return datetime.now(timezone.utc)


class ResponseMeta(BaseModel):
    """Metadata attached to every API response envelope.

    Attributes:
        api_version: Version of the API that produced the response.
        timestamp: UTC timestamp indicating when the response was
            generated.
    """

    api_version: str = Field(default=API_VERSION_1)
    timestamp: datetime = Field(default_factory=_utc_now)


class SuccessResponse(BaseModel, Generic[DataT]):
    """Standard success response envelope.

    Attributes:
        success: Always ``True`` for this model.
        message: Human readable summary of the result.
        data: The actual payload, whose shape depends on the endpoint.
        meta: Standard response metadata.
    """

    success: bool = True
    message: str = "Request completed successfully."
    data: Optional[DataT] = None
    meta: ResponseMeta = Field(default_factory=ResponseMeta)


class ErrorDetail(BaseModel):
    """Structured error detail included in :class:`ErrorResponse`.

    Attributes:
        type: Short machine-readable error category (e.g. the
            exception class name).
        message: Human readable error description.
        context: Optional additional structured context about the
            error, safe to expose to API clients.
    """

    type: str
    message: str
    context: Optional[dict[str, Any]] = None


class ErrorResponse(BaseModel):
    """Standard error response envelope.

    Attributes:
        success: Always ``False`` for this model.
        error: Structured details describing what went wrong.
        meta: Standard response metadata.
    """

    success: bool = False
    error: ErrorDetail
    meta: ResponseMeta = Field(default_factory=ResponseMeta)


class HealthComponent(BaseModel):
    """Health status of a single backend component.

    Attributes:
        name: Component identifier (e.g. "database").
        status: Either "ok" or "degraded".
        detail: Optional human readable detail.
    """

    name: str
    status: str
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    """Response model for the ``/health`` endpoint.

    Attributes:
        success: Whether the overall system is healthy.
        status: Overall status string ("ok" or "degraded").
        app_name: Configured application name.
        app_version: Configured application version.
        environment: Current runtime environment.
        components: Per-component health breakdown (e.g. database).
        meta: Standard response metadata.
    """

    success: bool
    status: str
    app_name: str
    app_version: str
    environment: str
    components: list[HealthComponent] = Field(default_factory=list)
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
