"""Registry of the optimization strategies.

Extending. A new strategy is a subclass of ``base.Optimizer`` with a unique ``name``, decorated with
``@register``. Its module must be imported in ``optimizers/__init__.py``, and the name belongs into
the options of ``search.optimizer`` (config.FIELD_META, with catalog texts ``option.search.optimizer.<name>``)
so that validation and UI know it. A test checks that both lists match.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from ..i18n import tr

if TYPE_CHECKING:
    from .base import Optimizer

OPTIMIZERS: dict[str, "type[Optimizer]"] = {}

T = TypeVar("T")


def register(cls: T) -> T:
    """Class decorator. Registers the strategy under its name."""
    name = cls.name  # type: ignore[attr-defined]
    if name in OPTIMIZERS and OPTIMIZERS[name] is not cls:
        raise ValueError(tr("optimizer.duplicate", name=name))
    OPTIMIZERS[name] = cls  # type: ignore[assignment]
    return cls


def get_optimizer(name: str = "pattern_greedy") -> "Optimizer":
    """New instance of the strategy name."""
    try:
        return OPTIMIZERS[name]()
    except KeyError:
        raise ValueError(tr("optimizer.unknown", name=name, known=sorted(OPTIMIZERS))) from None
