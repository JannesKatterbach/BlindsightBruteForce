"""Kommandozeile. Optimierung ohne UI, zum Testen und Automatisieren.

  python -m blindsight.cli examples/small_hex.json --svg out.svg --json out.json
"""

from __future__ import annotations

import argparse
import sys

from .config import ConfigError, Project
from .export import JsonExporter, SvgExporter, build_geometry
from .layout import Counter
from .model import Model
from .optimizers import run_optimizer
from .optimizers.base import StopToken


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Project Blindsight Optimierer (ohne Web UI)")
    ap.add_argument("config", help="Pfad zur JSON Konfiguration")
    ap.add_argument("--svg", help="SVG Ausgabedatei")
    ap.add_argument("--json", help="JSON Ausgabedatei der Geometrie")
    ap.add_argument("--time", type=float, help="Zeitlimit in Sekunden (ueberschreibt die Konfiguration)")
    ap.add_argument("--seed", type=int, help="Zufalls Seed (ueberschreibt die Konfiguration)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    try:
        project = Project.load(args.config)
        if args.time:
            project.search.time_limit_s = args.time
        if args.seed is not None:
            project.search.seed = args.seed
        model = Model(project)
    except (ConfigError, OSError) as exc:
        print(f"Fehler in der Konfiguration. {exc}", file=sys.stderr)
        return 2

    counter = Counter()
    stop = StopToken(project.search.time_limit_s, project.search.max_candidates, counter)
    last = [0.0]

    def progress(info):
        if not args.quiet and info.elapsed - last[0] > 1.0:
            last[0] = info.elapsed
            print(f"[{info.elapsed:5.1f}s] {info.phase}. Kandidaten {info.candidates}, beste Anzahl {info.best_count}")

    result = run_optimizer(model, progress, stop, counter)
    print(f"Status {result.status}, Kandidaten {result.candidates}, Zeit {result.elapsed:.1f}s")
    print(result.optimality_note)
    for m in result.messages:
        print(" -", m)
    if not result.best:
        return 1
    best = result.best
    print(f"Beste Loesung. {len(best.placements)} von {result.target} Stangen, Score {best.score.total:.3f}")
    for k, v in best.score.terms.items():
        print(f"   {k:11s} {v:.3f} (Gewicht {best.score.weights[k]:.2f})")
    geometry = build_geometry(model, best.placements)
    if args.svg:
        with open(args.svg, "w", encoding="utf-8") as fh:
            fh.write(SvgExporter().export(geometry))
        print("SVG geschrieben.", args.svg)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(JsonExporter().export(geometry))
        print("JSON geschrieben.", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
