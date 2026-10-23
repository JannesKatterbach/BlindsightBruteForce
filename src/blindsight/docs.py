"""Erzeugt die Parametertabelle der README aus FIELD_META (einzige Quelle der Wahrheit).

  python -m blindsight.docs            gibt die Tabelle aus
  python -m blindsight.docs --update   ersetzt den Block zwischen den Markern in README.md
"""

from __future__ import annotations

import sys
from pathlib import Path

from .config import FIELD_META

BEGIN = "<!-- PARAMS:BEGIN -->"
END = "<!-- PARAMS:END -->"
UNIT = {"len": "mm", "lenlist": "mm", "num": "", "int": "", "text": "", "enum": "", "list": "", "listint": "", "liststr": ""}
NO_UPPER_LIMIT = 1e9  # groessere Obergrenzen sind nur technische Schranken und werden nicht angezeigt


def parameter_table() -> str:
    rows = ["| Parameter | Bedeutung | Einheit | Grenzen |", "|---|---|---|---|"]
    for meta in FIELD_META:
        limits = []
        if meta.lo is not None:
            limits.append(("> " if meta.strict_lo else ">= ") + f"{meta.lo:g}")
        if meta.hi is not None and meta.hi < NO_UPPER_LIMIT:
            limits.append(f"<= {meta.hi:g}")
        if meta.options:
            limits = [" / ".join(f"`{option[0]}`" for option in meta.options)]
        optional = " (optional)" if meta.optional and "optional" not in meta.label else ""
        unit = UNIT.get(meta.kind, "")
        rows.append(f"| `{meta.path}` | {meta.label}{optional}. {meta.tip} | {unit} | {', '.join(limits)} |")
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
