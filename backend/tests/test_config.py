"""Tests for the configuration system."""

from __future__ import annotations

from app.config.settings import Settings, get_settings


def test_settings_can_be_instantiated() -> None:
    """Settings should be constructible with default values."""
    settings = Settings()
    assert settings.app_name
    assert settings.api_port > 0
    assert settings.database_url


def test_get_settings_is_cached() -> None:
    """get_settings() should return the same object across calls."""
    first = get_settings()
    second = get_settings()
    assert first is second


def test_cors_origins_parsed_from_comma_separated_string() -> None:
    """A comma-separated CORS origins string should be split into a list."""
    settings = Settings(cors_origins="http://localhost:3000,http://localhost:5173")
    assert settings.cors_origins == ["http://localhost:3000", "http://localhost:5173"]


def test_log_level_is_normalized_to_uppercase() -> None:
    """Log level strings should be normalized to uppercase."""
    settings = Settings(log_level="debug")
    assert settings.log_level == "DEBUG"
