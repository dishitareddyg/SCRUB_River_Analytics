"""Custom exception hierarchy for the River Intelligence Platform.

All application-specific errors should inherit from
:class:`ApplicationError` so that the global FastAPI exception handler
(registered in ``main.py``) can catch a single base type and still
report a meaningful, category-specific error to API clients.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for all application-specific errors.

    Attributes:
        message: Human readable error message.
        status_code: Suggested HTTP status code to return to clients
            when this error is translated into an API response.
    """

    status_code: int = 500

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        """Initialize the error.

        Args:
            message: Human readable error message.
            status_code: Optional override of the default HTTP status
                code associated with this error class.
        """
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class ConfigurationError(ApplicationError):
    """Raised when application configuration is missing or invalid."""

    status_code = 500


class DatabaseError(ApplicationError):
    """Raised when a database operation fails."""

    status_code = 503


class CommunicationError(ApplicationError):
    """Raised when communication with external hardware/services fails.

    Reserved primarily for the future serial communication module
    (e.g. failure to open the Arduino's COM port), but usable by any
    component that talks to an external system.
    """

    status_code = 502


class ValidationError(ApplicationError):
    """Raised when data fails domain-specific validation rules.

    This is distinct from FastAPI/Pydantic's built-in request
    validation - it is intended for validation that happens deeper in
    the application (e.g. sensor reading range checks in a future
    module).
    """

    status_code = 422


class NotFoundError(ApplicationError):
    """Raised when a requested resource does not exist.

    Typical use: an API request references an unknown sensor name or
    unknown analytics parameter key.
    """

    status_code = 404


class BadRequestError(ApplicationError):
    """Raised when a request is well-formed but logically invalid.

    Distinct from Pydantic's automatic 422 schema validation (wrong
    type, missing field) and from :class:`NotFoundError` (resource
    does not exist) - this is for requests that parse fine but
    conflict with each other or violate a request-level business rule
    (e.g. an end time before the start time, or two mutually exclusive
    query parameters both supplied).
    """

    status_code = 400
