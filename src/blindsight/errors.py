"""Error classes carrying a list of understandable messages.

All checks collect as many problems as possible instead of stopping at the first one. Every
message starts with the field path (for example ``rod.diameter. Must be greater than 0``) so the
UI can attach it to the input field. Messages are usually ``i18n.LocalText`` values.
"""

from __future__ import annotations


class ValidationError(ValueError):
    """Base class. ``errors`` holds all problems found."""

    def __init__(self, errors: list[str] | str):
        if isinstance(errors, str):
            errors = [errors]
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class ConfigError(ValidationError):
    """Invalid configuration."""


class SketchError(ValidationError):
    """Invalid or unsolvable motor sketch."""
