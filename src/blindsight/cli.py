"""Kommandozeile. Optimierung ohne UI, zum Testen und Automatisieren.

  blindsight-cli examples/small_hex.json --svg out.svg --json out.json
  python -m blindsight.cli examples/small_hex.json --time 20

Exitcodes
  0  Loesung gefunden (und Dateien geschrieben)
  1  keine gueltige Loesung gefunden
  2  Konfiguration nicht lesbar oder ungueltig (auch nach --time und --seed)
  3  Ausgabedatei konnte nicht geschrieben werden
"""

from __future__ import annotations

import argparse
import sys

from .config import ConfigError, Project
from .export import JsonExporter, SvgExporter, build_geometry
from .layout import Counter
from .model import Model
from .optimizers import run_optimizer
from .optimizers.base import ProgressInfo, StopToken

EXIT_OK, EXIT_NO_SOLUTION, EXIT_CONFIG, EXIT_OUTPUT = 0, 1, 2, 3
PROGRESS_INTERVAL_S = 1.0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Project Blindsight Optimierer (ohne Web UI)")
    ap.add_argument("config", help="Pfad zur JSON Konfiguration")
    ap.add_argument("--svg", help="SVG Ausgabedatei")
    ap.add_argument("--json", help="JSON Ausgabedatei der Geometrie")
    ap.add_argument("--time", type=float, help="Zeitlimit in Sekunden (überschreibt die Konfiguration)")
    ap.add_argument("--seed", type=int, help="Zufalls Seed (überschreibt die Konfiguration)")
    ap.add_argument("--quiet", action="store_true")
    return ap


def _load(args: argparse.Namespace) -> Model:
    """Konfiguration lesen, Ueberschreibungen anwenden und alles gemeinsam pruefen (im Model)."""
    project = Project.load(args.config)
    if args.time is not None:
        project.search.time_limit_s = args.time
    if args.seed is not None:
        project.search.seed = args.seed
    return Model(project)


def _write(path: str, text: str, what: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"{what} geschrieben.", path)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        model = _load(args)
    except (ConfigError, OSError, UnicodeDecodeError) as exc:
        print(f"Fehler in der Konfiguration. {exc}", file=sys.stderr)
        return EXIT_CONFIG
    project = model.project

    counter = Counter()
    stop = StopToken(project.search.time_limit_s, project.search.max_candidates, counter)
    last_report = [0.0]

    def progress(info: ProgressInfo) -> None:
        if not args.quiet and info.elapsed - last_report[0] > PROGRESS_INTERVAL_S:
            last_report[0] = info.elapsed
            print(f"[{info.elapsed:5.1f}s] {info.phase}. Kandidaten {info.candidates}, beste Anzahl {info.best_count}")

    result = run_optimizer(model, progress, stop, counter)
    print(f"Status {result.status}, Kandidaten {result.candidates}, Zeit {result.elapsed:.1f}s")
    print(result.optimality_note)
    for message in result.messages:
        print(" -", message)
    if not result.best:
        return EXIT_NO_SOLUTION
    best = result.best
    print(f"Beste Lösung. {len(best.placements)} von {result.target} Stangen, Score {best.score.total:.3f}")
    for name, value in best.score.terms.items():
        print(f"   {name:11s} {value:.3f} (Gewicht {best.score.weights[name]:.2f})")
    geometry = build_geometry(model, best.placements)
    try:
        if args.svg:
            _write(args.svg, SvgExporter().export(geometry), "SVG")
        if args.json:
            _write(args.json, JsonExporter().export(geometry), "JSON")
    except OSError as exc:
        print(f"Ausgabedatei nicht schreibbar. {exc}", file=sys.stderr)
        return EXIT_OUTPUT
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
