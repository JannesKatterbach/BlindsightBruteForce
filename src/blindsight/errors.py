"""Fehlerklassen mit einer Liste verstaendlicher Meldungen.

Alle Pruefungen sammeln moeglichst viele Probleme auf einmal, statt beim ersten
abzubrechen. Jede Meldung beginnt mit dem Feldpfad (zum Beispiel
``rod.diameter. Muss groesser als 0 sein``), damit die UI sie dem Eingabefeld
zuordnen kann.
"""

from __future__ import annotations


class ValidationError(ValueError):
    """Basisklasse. ``errors`` enthaelt alle gefundenen Probleme."""

    def __init__(self, errors: list[str] | str):
        if isinstance(errors, str):
            errors = [errors]
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class ConfigError(ValidationError):
    """Ungueltige Konfiguration."""


class SketchError(ValidationError):
    """Ungueltige oder nicht loesbare Motor Skizze."""
