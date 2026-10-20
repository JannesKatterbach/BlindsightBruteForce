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
UNIT = {"len": "mm", "num": "", "int": "", "text": "", "enum": "", "list": "mm", "listint": "", "liststr": ""}


def parameter_table() -> str:
    rows = ["| Parameter | Bedeutung | Einheit | Grenzen |", "|---|---|---|---|"]
    for m in FIELD_META:
        lim = []
        if m.lo is not None:
            lim.append(("> " if m.strict_lo else ">= ") + f"{m.lo:g}")
        if m.hi is not None and m.hi < 1e9:
            lim.append(f"<= {m.hi:g}")
        if m.options:
            lim = [" / ".join(f"`{o[0]}`" for o in m.options)]
        opt = " (optional)" if m.optional and "optional" not in m.label else ""
        rows.append(f"| `{m.path}` | {m.label}{opt}. {m.tip} | {UNIT.get(m.kind, '')} | {', '.join(lim)} |")
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
