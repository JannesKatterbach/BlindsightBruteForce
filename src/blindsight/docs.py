"""Generates the parameter table of the README from FIELD_META (single source of truth).

The README is German, so the table is rendered in German.

  python -m blindsight.docs            prints the table
  python -m blindsight.docs --update   replaces the block between the markers in README.md
"""

from __future__ import annotations

import sys
from pathlib import Path

from .config import FIELD_META
from .i18n import use_language

BEGIN = "<!-- PARAMS:BEGIN -->"
END = "<!-- PARAMS:END -->"
UNIT = {"len": "mm", "lenlist": "mm", "num": "", "int": "", "text": "", "enum": "", "list": "", "listint": "", "liststr": ""}
NO_UPPER_LIMIT = 1e9  # larger upper limits are only technical bounds and are not shown
README_LANGUAGE = "de"


def parameter_table(language: str = README_LANGUAGE) -> str:
    with use_language(language):
        rows = ["| Parameter | Bedeutung | Einheit | Grenzen |", "|---|---|---|---|"]
        for meta in FIELD_META:
            limits = []
            if meta.lo is not None:
                limits.append(("> " if meta.strict_lo else ">= ") + f"{meta.lo:g}")
            if meta.hi is not None and meta.hi < NO_UPPER_LIMIT:
                limits.append(f"<= {meta.hi:g}")
            if meta.options:
                limits = [" / ".join(f"`{option}`" for option in meta.options)]
            label = str(meta.label)
            optional = " (optional)" if meta.optional and "optional" not in label else ""
            unit = UNIT.get(meta.kind, "")
            rows.append(f"| `{meta.path}` | {label}{optional}. {meta.tip} | {unit} | {', '.join(limits)} |")
    return "\n".join(rows)


def update_readme(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    a, b = text.index(BEGIN), text.index(END)
    path.write_text(text[: a + len(BEGIN)] + "\n" + parameter_table() + "\n" + text[b:], encoding="utf-8")


if __name__ == "__main__":
    if "--update" in sys.argv:
        update_readme(Path(__file__).resolve().parents[2] / "README.md")
    else:
        print(parameter_table())
