"""Shared Pytest fixtures for the backend test suite."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Provide a FastAPI :class:`TestClient` for the application.

    Returns:
        A configured :class:`TestClient` instance bound to ``app``.
    """
    return TestClient(app)
