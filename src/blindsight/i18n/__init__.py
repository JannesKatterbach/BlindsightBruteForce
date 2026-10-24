"""Translations of all user visible texts (German, English, French).

Every visible text has a key in the catalogs ``de.json``, ``en.json`` and ``fr.json`` next to this
file. ``tr(key, **params)`` returns a ``LocalText``. It behaves like a ``str`` in the current
language, but remembers key and parameters, so it can be rendered again in another language with
``localize``. The server renders every response in the language of the request, so results of a run
follow a later language switch in the UI.

The current language is a context variable. The server sets it per request (header ``X-Language``,
otherwise ``Accept-Language``), the CLI sets it from ``--lang``. Threads of runs inherit it.

Templates use ``str.format`` syntax, for example ``"{path}. Must be greater than {lo:g}"``.
Parameters may be ``LocalText`` themselves (nested messages) and are rendered in the same language.
List and tuple parameters are rendered as their items joined by ", " (items may be ``LocalText``).
"""

from __future__ import annotations

import contextvars
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

LANGUAGES = ("de", "en", "fr")
DEFAULT_LANGUAGE = "de"
LANGUAGE_NAMES = {"de": "Deutsch", "en": "English", "fr": "Français"}

_CATALOG_DIR = Path(__file__).parent
_catalogs: dict[str, dict[str, str]] = {}
_language: contextvars.ContextVar[str] = contextvars.ContextVar("blindsight_language", default=DEFAULT_LANGUAGE)


def catalog(language: str) -> dict[str, str]:
    """Templates of a language (loaded once)."""
    if language not in _catalogs:
        path = _CATALOG_DIR / f"{language}.json"
        _catalogs[language] = json.loads(path.read_text(encoding="utf-8"))
    return _catalogs[language]


def normalize_language(value: Optional[str]) -> str:
    """Supported language code for a code like "en-GB", otherwise the default."""
    code = (value or "").strip().lower()[:2]
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def negotiate(accept_language: Optional[str]) -> str:
    """First supported language of an Accept-Language header (weights are ignored, order counts)."""
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGUAGES:
            return code
    return DEFAULT_LANGUAGE


def current_language() -> str:
    return _language.get()


def set_language(language: str) -> contextvars.Token:
    return _language.set(normalize_language(language))


@contextmanager
def use_language(language: str) -> Iterator[None]:
    """Temporarily switch the current language."""
    token = set_language(language)
    try:
        yield
    finally:
        _language.reset(token)


def render(key: str, params: dict[str, Any], language: str) -> str:
    """Text of key in language. Missing keys fall back to the default language, then to the key."""
    template = catalog(language).get(key)
    if template is None:
        template = catalog(DEFAULT_LANGUAGE).get(key, key)
    values = {name: _param(value, language) for name, value in params.items()}
    return template.format(**values) if values else template


def _param(value: Any, language: str) -> Any:
    if isinstance(value, LocalText):
        return value.localized(language)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(_param(item, language)) for item in value)
    return value


class LocalText(str):
    """A text in the current language that can be rendered again in another language."""

    def __new__(cls, key: str, params: Optional[dict[str, Any]] = None) -> "LocalText":
        params = dict(params or {})
        obj = super().__new__(cls, render(key, params, current_language()))
        obj.key = key
        obj.params = params
        return obj

    def localized(self, language: str) -> str:
        return render(self.key, self.params, language)

    def __reduce__(self):  # pickling (parallel runs) keeps key and parameters
        return (LocalText, (self.key, self.params))


def tr(key: str, /, **params: Any) -> LocalText:
    """Text for key in the current language (key is positional only, so a parameter may be called key)."""
    return LocalText(key, params)


def localize(obj: Any, language: str) -> Any:
    """Copy of obj (dicts, lists, tuples) with every LocalText rendered in language."""
    if isinstance(obj, LocalText):
        return obj.localized(language)
    if isinstance(obj, dict):
        return {key: localize(value, language) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [localize(value, language) for value in obj]
    return obj


__all__ = [
    "DEFAULT_LANGUAGE", "LANGUAGES", "LANGUAGE_NAMES", "LocalText", "catalog", "current_language", "localize",
    "negotiate", "normalize_language", "render", "set_language", "tr", "use_language",
]
