"""Register der Optimierungsstrategien.

Erweitern. Eine neue Strategie ist eine Unterklasse von ``base.Optimizer`` mit eindeutigem
``name``, dekoriert mit ``@register``. Ihr Modul muss in ``optimizers/__init__.py`` importiert
werden, und der Name gehoert in die Optionen von ``search.optimizer`` (config.FIELD_META), damit
Validierung und UI ihn kennen. Ein Test prueft, dass beide Listen uebereinstimmen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .base import Optimizer

OPTIMIZERS: dict[str, "type[Optimizer]"] = {}

T = TypeVar("T")


def register(cls: T) -> T:
    """Klassendekorator. Traegt die Strategie unter ihrem Namen ein."""
    name = cls.name  # type: ignore[attr-defined]
    if name in OPTIMIZERS and OPTIMIZERS[name] is not cls:
        raise ValueError(f"Optimierer '{name}' ist bereits registriert")
    OPTIMIZERS[name] = cls  # type: ignore[assignment]
    return cls


def get_optimizer(name: str = "pattern_greedy") -> "Optimizer":
    """Neue Instanz der Strategie name."""
    try:
        return OPTIMIZERS[name]()
    except KeyError:
        raise ValueError(f"Unbekannter Optimierer '{name}'. Verfuegbar. {sorted(OPTIMIZERS)}") from None
